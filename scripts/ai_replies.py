#!/usr/bin/env python3
"""Detecta temas sin responder en fivetechsupport.com y responde con IA (modelos free de OpenCode Zen).

Uso:
  python ai_replies.py detect            # lista temas sin responder (JSON)
  python ai_replies.py run               # ciclo completo: detectar -> responder -> publicar
Requiere: requests   (pip install requests)
Secrets/vars de entorno:
  FORUM_USERNAME, FORUM_PASSWORD  -> cuenta bot del foro (solo para 'run')
  AI_MAX_REPLIES                  -> max respuestas por ejecucion (default 5)
"""

import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

BASE = "https://fivetechsupport.com/forums/"
_ZEN_HOST = "api.fivetechsoft.com"
PREFERRED_MODELS = ["x-preview-f-free", "mimo-v2.5-free"]  # Ox Alpha, Mimo
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Foros de soporte tecnico (excluye Off Topic, Wishlist, Bugs, Announcements)
SUPPORT_FORUMS = {
    # English
    1: "en", 3: "en", 32: "en", 30: "en", 5: "en", 11: "en", 4: "en", 45: "en",
    # Espanol
    2: "es", 6: "es", 33: "es", 31: "es", 8: "es", 12: "es", 7: "es", 46: "es",
    # Italiano / Portugues / Aleman ("All products support")
    20: "it", 21: "pt", 23: "de",
}

# ---------------------------------------------------------------- contexto (repos publicos)

CTX_DIR = os.environ.get("FW_CONTEXT_DIR",
                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ctx"))

# Docs oficiales de FWH (autorizadas), fuentes oficiales FWH (repo privado,
# se clona con FWH_TOKEN/GITHUB_TOKEN y sparse-checkout) + fuentes publicos
# estilo FiveWin + Harbour core
CONTEXT_REPOS = [
    ("https://github.com/FiveTechSoft/FWH_docs.git", "fwh_docs"),
    ("https://github.com/harbour/core.git", "harbour"),
    ("https://github.com/lautaromoreira/fivelinux.git", "fivelinux"),
    ("https://github.com/mastintin/FiveMacArm.git", "fivemac"),
    ("https://github.com/fabioandrec/fivedos.git", "fivedos"),
]

# Repo privado con las fuentes oficiales completas (prioridad maxima como contexto)
FWH_SOURCES_REPO = "https://github.com/FiveTechSoft/fwh.git"
FWH_SOURCES_DIR = os.path.join(CTX_DIR, "fwh")
FWH_SPARSE_DIRS = ["include", "source"]

STOPWORDS = set("""the a an and or of to in for with is are was were be been on at by from
that this it as not but if then else when what which who how why where can could should
would will shall may might must do does did done have has had i you he she we they me him
her us them my your his their our que los las del con para por una uno unos unas son es
ser estar como mas pero muy sin sobre entre desde hasta segun cual cuales quien cuando
donde porque este esta esto estos estas ese esa eso esos esas aux x64 x86 com org www""".split())


def _github_token():
    return (os.environ.get("FWH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            or "").strip()


def ensure_context_repos():
    """Clon shallow de los repos de contexto si no estan ya descargados.
    El token NUNCA va en argv ni en logs: se inyecta a git por entorno
    (GIT_CONFIG_*) y solo existe como secret de GitHub Actions."""
    import base64
    import shutil
    import subprocess

    token = _github_token()

    def git(args, timeout=300):
        env = dict(os.environ)
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
            env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
        p = subprocess.run(["git"] + args, check=True, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        return p

    for url, name in CONTEXT_REPOS:
        dst = os.path.join(CTX_DIR, name)
        if os.path.isdir(dst):
            continue
        try:
            git(["clone", "--depth", "1", "--quiet", url, dst], timeout=600)
            print(f"contexto: {name} descargado")
        except Exception as e:
            n = sum(len(fs) for _, _, fs in os.walk(dst)) if os.path.isdir(dst) else 0
            if n > 10:
                print(f"contexto: {name} descargado (con avisos: {type(e).__name__})")
            else:
                shutil.rmtree(dst, ignore_errors=True)
                print(f"contexto: {name} NO disponible ({type(e).__name__})", file=sys.stderr)

    # fuentes oficiales FWH (privado): clon parcial solo con include/ y source/
    if not os.path.isdir(FWH_SOURCES_DIR):
        if not token:
            print("contexto: fwh omitido (sin token)", file=sys.stderr)
        else:
            tmp = FWH_SOURCES_DIR + ".tmp"
            ok = False
            for intento in range(3):
                try:
                    if os.path.isdir(tmp):
                        shutil.rmtree(tmp, ignore_errors=True)
                    git(["clone", "--depth", "1", "--filter=blob:none", "--sparse",
                         "--quiet", FWH_SOURCES_REPO, tmp], timeout=600)
                    git(["-C", tmp, "sparse-checkout", "set"] + FWH_SPARSE_DIRS,
                        timeout=600)
                    os.rename(tmp, FWH_SOURCES_DIR)
                    # el .git del clon contiene credenciales resueltas: se elimina al final
                    shutil.rmtree(os.path.join(FWH_SOURCES_DIR, ".git"),
                                  ignore_errors=True)
                    ok = True
                    break
                except Exception as e:
                    err = type(e).__name__
                    time.sleep(5 * (intento + 1))
            if ok:
                n = sum(len(fs) for _, _, fs in os.walk(FWH_SOURCES_DIR))
                print(f"contexto: fwh (fuentes oficiales) descargado ({n} archivos)")
            else:
                shutil.rmtree(tmp, ignore_errors=True)
                print(f"contexto: fwh NO disponible ({err})", file=sys.stderr)


def keywords(text, limit=8):
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    seen, out = set(), []
    for w in words:
        lw = w.lower()
        if lw in STOPWORDS or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _grep_files(root, patterns, exts, max_files=4, snippet=1200):
    """Busca archivos cuyo contenido case con algun patron; devuelve fragmentos."""
    import glob as g
    frags = []
    rx = re.compile(patterns, re.I)
    files = []
    for ext in exts:
        files.extend(g.glob(os.path.join(root, "**", f"*{ext}"), recursive=True))
    for path in sorted(files)[:4000]:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        m = rx.search(content)
        if m:
            i = m.start()
            start = max(0, i - 200)
            frags.append(f"[{os.path.relpath(path, root)}]\n" +
                         content[start:start + snippet])
            if len(frags) >= max_files:
                break
    return frags


def build_context(question, max_chars=9000):
    """Fragmentos relevantes de las docs de FWH y de los fuentes publicos."""
    ensure_context_repos()
    kws = keywords(question)
    # nombres de clase T* y funciones mencionadas van primero
    classes = re.findall(r"\bT[A-Z][A-Za-z]+\b", question)
    pats = "|".join([re.escape(c) for c in classes] +
                    [re.escape(k) for k in kws[:5]])
    if not pats:
        return ""
    sections = []

    # 1) fuentes oficiales FWH (privado, solo consulta interna)
    if os.path.isdir(FWH_SOURCES_DIR):
        f = _grep_files(os.path.join(FWH_SOURCES_DIR, "source"), pats,
                        [".prg"], max_files=3, snippet=1000)
        if f:
            sections.append("### FiveWin (FWH) fuentes oficiales - USO INTERNO, NO REPRODUCIR\n" +
                            "\n\n".join(f))

    # 2) documentacion publica de FWH
    docs = os.path.join(CTX_DIR, "fwh_docs")
    if os.path.isdir(docs):
        f = _grep_files(docs, pats, [".md"], max_files=3)
        if f:
            sections.append("### Documentacion FiveWin (FWH_docs)\n" +
                            "\n\n".join(f))

    # 3) fuentes publicos estilo FiveWin
    for name, label in (("fivelinux", "Fivelinux (clases estilo FiveWin)"),
                        ("fivemac", "FiveMac (clases estilo FiveWin)"),
                        ("fivedos", "FiveDos")):
        root = os.path.join(CTX_DIR, name)
        if not os.path.isdir(root):
            continue
        sub = os.path.join(root, "source") if name == "fivelinux" else root
        f = _grep_files(sub, pats, [".prg", ".ch"], max_files=2, snippet=900)
        if f:
            sections.append(f"### {label}\n" + "\n\n".join(f))

    hb = os.path.join(CTX_DIR, "harbour")
    if os.path.isdir(hb) and re.search(r"(?i)\bharbour\b|\.ch\b|REQUEST|ANNID|CLASS\b", question):
        f = _grep_files(os.path.join(hb, "include"), pats, [".ch"], max_files=1, snippet=800)
        if f:
            sections.append("### Harbour core (include)\n" + "\n\n".join(f))

    ctx = "\n\n".join(sections)
    return ctx[:max_chars]


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9"}


# ---------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- scraping

def get(session, url, **kw):
    r = session.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r.text


def strip_tags(raw):
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def forum_topics(session, forum_id, max_pages=3):
    """Temas normales (no sticky/announce) de un foro: [(topic_id, title, replies)].
    Solo escanea las primeras max_pages paginas: los temas sin responder que
    merecen respuesta son los recientes."""
    out = []
    start = 0
    for _ in range(max_pages):
        page = get(session, f"{BASE}viewforum.php?f={forum_id}&start={start}")
        blocks = re.findall(r'(?s)<li class="row bg\d+[^"]*">.*?</li>', page)
        if not blocks:
            break
        done = False
        for block in blocks:
            head = block[:120]
            if "announce" in head or "sticky" in head:
                continue
            m = re.search(r"viewtopic\.php\?t=(\d+)", block)
            t = re.search(r'class="topictitle">([^<]+)</a>', block)
            p = re.search(r'<dd class="posts">(\d+)\s*<dfn>Replies</dfn>', block)
            if not (m and t and p):
                continue
            if int(p.group(1)) == 0:
                out.append({"topic": int(m.group(1)),
                            "title": html.unescape(t.group(1)).strip(),
                            "replies": 0})
            done = True
        if not done or len(blocks) < 10:
            break
        start += 50
        time.sleep(1)  # cortesia con el servidor
    return out


def thread_posts(session, topic_id, max_pages=3):
    """Todos los mensajes del thread: [(autor, texto)]. Sigue la paginacion."""
    posts = []
    start = 0
    for _ in range(max_pages):
        page = get(session, f"{BASE}viewtopic.php?t={topic_id}&start={start}")
        # cada post: bloque desde <div class="postbody"> hasta su <div class="content">
        bodies = re.findall(
            r'(?s)<div class="postbody">.*?class="username[^"]*">([^<]+)</a>.*?<div class="content">(.*?)</div>',
            page)
        if not bodies:
            break
        for author, raw in bodies:
            posts.append((strip_tags(author), strip_tags(raw)))
        if 'class="pagination"' not in page or f"start={start + 10}" not in page:
            break
        start += 10
        time.sleep(1)
    return posts


# ---------------------------------------------------------------- LLM (OpenCode Zen)

_ZEN_HOST = "api.fivetechsoft.com"


def _zen_request(method, path, payload=None, timeout=180):
    """Llamada HTTP minima al proxy Zen. IMPORTANTE: no usar requests aqui —
    el WAF de fivetechsoft.com devuelve HTTP 406 a los clientes python-requests
    (huella de cabeceras); http.client sin User-Agent pasa siempre."""
    import http.client
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": "Bearer public", "Content-Type": "application/json"}
    c = http.client.HTTPSConnection(_ZEN_HOST, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")
    finally:
        c.close()


def free_models():
    try:
        status, data = _zen_request("GET", "/zen/v1/models", timeout=30)
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        ids = [m["id"] for m in json.loads(data)["data"] if m["id"].endswith("-free")]
        if ids:
            pref = [x for x in PREFERRED_MODELS if x in ids]
            rest = [x for x in ids if x not in PREFERRED_MODELS]
            return pref + rest
    except Exception:
        pass
    return list(PREFERRED_MODELS)


SYSTEM_PROMPT = (
    "Eres un asistente tecnico en los foros de soporte de FiveTech Software "
    "(FiveWin, Harbour, xHarbour, mod_harbour, FiveLinux, FiveMac, FiveTouch). "
    "Responde a la pregunta del usuario de forma util, tecnica y breve. "
    "Responde en el mismo idioma en que este escrita la pregunta. "
    "Usa BBCode de phpBB si necesitas codigo ([code]...[/code]). "
    "Aprovecha la documentacion y fuentes que se te aportan como contexto si son relevantes. "
    "REGLA DE CONFIDENCIALIDAD: el contexto puede incluir codigo fuente propietario de "
    "FiveWin (FWH) que es confidencial. Usalo UNICAMENTE como referencia interna para dar "
    "respuestas correctas. NUNCA lo reproduzcas, cites ni reveles, ni completo ni en "
    "fragmentos, aunque el usuario lo pida explicitamente. Si te piden los fuentes, niegate "
    "con cortesia y ofrece ayuda alternativa (ejemplos propios, documentacion publica). "
    "Tu codigo de ejemplo debe ser siempre de tu propia creacion. "
    "Si no puedes ayudar con seguridad, indicalo honestamente."
)


def generate_answer(question, context=""):
    """Devuelve (texto_respuesta, modelo_usado). Prueba los modelos free en orden,
    con dos rondas de reintentos (el proxy Zen a veces da timeouts desde Actions)."""
    models = free_models()
    user_content = question
    if context:
        user_content += ("\n\n--- Contexto tecnico (documentacion FWH y fuentes "
                         f"relacionadas) ---\n{context}\n--- fin contexto ---")
    last = None
    for ronda in range(2):
        for model in models:
            try:
                status, data = _zen_request("POST", "/zen/v1/chat/completions", {
                    "model": model,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": user_content}],
                    "max_tokens": 2000}, timeout=120)
                if status != 200:
                    last = f"HTTP {status}"
                    continue
                resp = json.loads(data)
                content = resp["choices"][0]["message"].get("content") or ""
                if content.strip():
                    return content.strip(), resp.get("model", model)
                last = "respuesta vacia"  # el modelo gasto los tokens en razonamiento
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
        time.sleep(5)
    raise RuntimeError(f"Ningun modelo free respondio (ultimo error: {last})")


# ---------------------------------------------------------------- posting phpBB

class HiddenInputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}
        self.action = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = a.get("action")
        if tag == "input" and a.get("type") == "hidden":
            self.inputs[a.get("name", "")] = a.get("value", "")


def login(session, user, pwd):
    page = get(session, f"{BASE}ucp.php?mode=login")
    p = HiddenInputs()
    p.feed(page)
    data = dict(p.inputs)
    data.update({"username": user, "password": pwd, "login": "Login"})
    m = (re.search(r'(?s)<form[^>]+id="login"[^>]+action="([^"]+)"', page)
         or re.search(r'(?s)<form[^>]+action="([^"]*ucp\.php[^"]*)"', page))
    action = urljoin(BASE, m.group(1)) if m else f"{BASE}ucp.php?mode=login"
    session.post(action, data=data, headers=UA, timeout=60)
    # verificacion estricta: en sesion iniciada el indice muestra el enlace logout
    idx = get(session, f"{BASE}index.php")
    if "mode=logout" not in idx:
        raise RuntimeError("Login fallo: credenciales rechazadas o captcha activo")
    return True


def post_reply(session, topic_id, subject, message):
    page = get(session, f"{BASE}posting.php?mode=reply&t={topic_id}")
    if 'id="postingbox"' not in page:
        raise RuntimeError(f"No se obtuvo el formulario de respuesta para el tema {topic_id}")
    p = HiddenInputs()
    p.feed(page)
    data = dict(p.inputs)
    data.update({"subject": subject, "message": message, "post": "Submit",
                 "attachment_data": "0", "add_file": "Add files", "add_poll_option": "",
                 "update_file": "", "delete_file": "", "preview": ""})
    data.pop("cancel", None)
    action = urljoin(BASE, p.action or f"./posting.php?mode=reply&t={topic_id}")
    r = session.post(action, data=data, headers=UA, timeout=60)
    final = r.text
    if "message" in final.lower() and ("posted" in final.lower() or "publicado" in final.lower()) \
       or f"viewtopic.php?t={topic_id}" in r.url:
        return True
    # phpBB redirige al tema tras publicar; si seguimos viendo el form, fallo
    if 'id="postingbox"' in final:
        raise RuntimeError(f"El foro rechazo la publicacion en el tema {topic_id}")
    return True


DISCLAIMER_ES = "[size=85][i]Respuesta generada por Inteligencia Artificial usando el modelo {model} via OpenCode Zen. Puede contener errores; por favor verifiquela antes de aplicar.[/i][/size]"
DISCLAIMER_EN = "[size=85][i]AI-generated reply using the {model} model via OpenCode Zen. May contain mistakes; please verify before applying.[/i][/size]"


def build_message(answer, model):
    return f"{answer}\n\n{DISCLAIMER_ES.format(model=model)}\n{DISCLAIMER_EN.format(model=model)}"


# ---------------------------------------------------------------- main

def is_question(text):
    """Heuristica barata: parece pregunta."""
    t = text.lower()
    marks = ["?", "como ", "how ", "error", "problema", "problem", "necesito", "need",
             "ayuda", "help", "por que", "why ", "funciona", "work", "?"]
    return "?" in text or any(m in t for m in marks)


def run(dry=False, max_replies=None):
    max_replies = max_replies or int(os.environ.get("AI_MAX_REPLIES", "5"))
    state = load_state()
    session = requests.Session()

    candidates = []
    for fid in SUPPORT_FORUMS:
        try:
            topics = forum_topics(session, fid)
            print(f"foro {fid}: {len(topics)} sin responder")
            candidates.extend(topics)
        except Exception as e:
            print(f"foro {fid}: ERROR {e}", file=sys.stderr)
        time.sleep(3)  # cortesia: evita que el WAF del foro bloquee la IP del runner

    new = [c for c in candidates if str(c["topic"]) not in state]
    print(f"candidatos nuevos: {len(new)}")

    published = []
    for c in sorted(new, key=lambda x: -x["topic"])[:max_replies]:
        tid = c["topic"]
        try:
            posts = thread_posts(session, tid)
            if not posts:
                print(f"t={tid}: sin mensajes accesibles, omitido")
                continue
            thread = "\n\n".join(
                f"[Mensaje {i + 1} de {author}]\n{text[:3000]}"
                for i, (author, text) in enumerate(posts))
            if not is_question(c["title"] + "\n" + thread):
                print(f"t={tid}: no parece pregunta, omitido")
                continue
            question = (
                f"Titulo del tema: {c['title']}\n\n"
                f"Conversacion completa del thread ({len(posts)} mensajes):\n\n{thread[:12000]}\n\n"
                "Responde a la pregunta pendiente de este thread.")
            answer, model = generate_answer(question)
            print(f"t={tid}: respuesta generada con {model}")
            if dry:
                published.append({"topic": tid, "title": c["title"], "model": model})
                state[str(tid)] = {"title": c["title"], "model": model, "dry_run": True}
                continue
            login(session, os.environ["FORUM_USERNAME"], os.environ["FORUM_PASSWORD"])
            ok = post_reply(session, tid, "Re: " + c["title"],
                            build_message(answer, model))
            print(f"t={tid}: {'publicado' if ok else 'sin confirmacion'}")
            state[str(tid)] = {"title": c["title"], "model": model}
            published.append({"topic": tid, "title": c["title"], "model": model})
        except Exception as e:
            print(f"t={tid}: ERROR {e}", file=sys.stderr)
        save_state(state)

    save_state(state)
    print(json.dumps(published, indent=2, ensure_ascii=False))
    return published


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "detect":
        s = requests.Session()
        all_t = []
        for fid in SUPPORT_FORUMS:
            all_t.extend(forum_topics(s, fid))
        print(json.dumps(all_t, indent=2, ensure_ascii=False))
    elif cmd == "run-dry":
        run(dry=True, max_replies=int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    else:
        run()
