"""
Generate static phpBB-style site from imported SQLite.

Outputs to ./out/ alongside copying style.css from ../static/.

Usage:
  python generate.py <db.sqlite> <out_dir> [--limit-forum FORUM_ID] [--limit-topics N]

The Giscus snippet is embedded on each viewtopic page using mapping=pathname so
each topic gets its own Discussion automatically when the first reply lands.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:
    import markdown as md_lib
    _MD = md_lib.Markdown(extensions=["fenced_code", "tables", "nl2br"], output_format="html5")
except ImportError:
    _MD = None

GISCUS_REPO = "FiveTechSoft/forums-demo"
GISCUS_REPO_ID = "R_kgDOSYw8Sw"
GISCUS_CATEGORY = "General"
GISCUS_CATEGORY_ID = "DIC_kwDOSYw8S84C8qKa"

NEW_THREAD_BASE = (
    "https://github.com/FiveTechSoft/forums-demo/discussions/new?category=general"
)


# ----------------------------- BBCode -> HTML ---------------------------------
# Strip phpBB :uid markers like [b:abcd1234] -> [b]
RE_UID = re.compile(r":[a-z0-9]{4,8}(?=[\]:])", re.IGNORECASE)


RE_SMILEY_COMMENT = re.compile(r"<!--\s*s[^>]*?-->", re.IGNORECASE)
RE_SMILEY_IMG = re.compile(r'<img\s+src="\{SMILIES_PATH\}/([^"]+)"[^>]*?/?>', re.IGNORECASE)
RE_NUMERIC_ENTITY = re.compile(r"&#(\d+);")
RE_MERMAID_BB = re.compile(r"\[mermaid\](.*?)\[/mermaid\]", re.IGNORECASE | re.DOTALL)
RE_MERMAID_FENCE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def render_post_body(text: str, enable_markdown: int, enable_bbcode: int) -> str:
    """Dispatch to BBCode or Markdown renderer based on per-post flags. Both can extract
    Mermaid blocks before/after main rendering so they survive untouched."""
    if not text:
        return ""
    # Stash mermaid blocks (BBCode form first, then markdown fenced if md path)
    placeholders: list[str] = []

    def stash_bb(m: re.Match[str]) -> str:
        placeholders.append(m.group(1).strip())
        return f"\x00MERMAID{len(placeholders)-1}\x00"

    text2 = RE_MERMAID_BB.sub(stash_bb, text)

    if enable_markdown and _MD is not None:
        # Stash markdown-fence mermaid too
        def stash_md(m: re.Match[str]) -> str:
            placeholders.append(m.group(1).strip())
            return f"\x00MERMAID{len(placeholders)-1}\x00"
        text2 = RE_MERMAID_FENCE.sub(stash_md, text2)
        _MD.reset()
        body = _MD.convert(text2)
    else:
        body = bbcode_to_html(text2)

    # Restore mermaid blocks as <pre class="mermaid">
    def restore(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return f'<pre class="mermaid">{html.escape(placeholders[idx])}</pre>'

    return re.sub(r"\x00MERMAID(\d+)\x00", restore, body)


def _decode_entities_in_url(m: re.Match[str]) -> str:
    raw = m.group(0)
    # Decode numeric HTML entities used by phpBB to mangle URLs (no magic_url)
    return RE_NUMERIC_ENTITY.sub(lambda x: chr(int(x.group(1))), raw)


def bbcode_to_html(text: str) -> str:
    if not text:
        return ""
    s = RE_UID.sub("", text)
    # Strip phpBB smiley wrappers + smiley imgs entirely
    s = RE_SMILEY_COMMENT.sub("", s)
    s = RE_SMILEY_IMG.sub("", s)
    rules: list[tuple[str, str]] = [
        (r"\[b\](.*?)\[/b\]", r"<strong>\1</strong>"),
        (r"\[i\](.*?)\[/i\]", r"<em>\1</em>"),
        (r"\[u\](.*?)\[/u\]", r'<span style="text-decoration:underline">\1</span>'),
        (r"\[s\](.*?)\[/s\]", r"<del>\1</del>"),
        (r"\[color=([^\]]+)\](.*?)\[/color\]", r'<span style="color:\1">\2</span>'),
        (r"\[size=(\d+)\](.*?)\[/size\]", r'<span style="font-size:\1%">\2</span>'),
        (r"\[url=([^\]]+)\](.*?)\[/url\]", r'<a href="\1" rel="noopener">\2</a>'),
        (r"\[url\](.*?)\[/url\]", r'<a href="\1" rel="noopener">\1</a>'),
        (r"\[img\](.*?)\[/img\]", r'<img src="\1" alt="" loading="lazy">'),
        (r"\[email\](.*?)\[/email\]", r'<a href="mailto:\1">\1</a>'),
        (r"\[quote=&quot;([^&]+)&quot;\]", r'<blockquote><cite>\1 wrote:</cite>'),
        (r"\[quote=\"([^\"]+)\"\]", r'<blockquote><cite>\1 wrote:</cite>'),
        (r"\[quote\]", r"<blockquote>"),
        (r"\[/quote\]", r"</blockquote>"),
        # [code] and [code=lang] both supported. Wrap in codebox with select-all + toggle.
        (r"\[code(?:=[^\]]*)?\](.*?)\[/code\]",
         r'<div class="codebox"><div class="codehead"><span>Code:</span> '
         r'<a href="#" class="cb-select">Select all</a> '
         r'<a href="#" class="cb-toggle">Collapse</a></div>'
         r'<pre><code>\1</code></pre></div>'),
        (r"\[list\]", r"<ul>"),
        (r"\[list=1\]", r"<ol>"),
        (r"\[/list\]", r"</ul>"),
        (r"\[\*\](.*?)(?=\[\*\]|\[/list\]|\[/list=|$)", r"<li>\1</li>"),
        (r"\[youtube\](.*?)\[/youtube\]",
         r'<iframe width="560" height="315" src="https://www.youtube.com/embed/\1" frameborder="0" allowfullscreen></iframe>'),
        (r"\[attachment=\d+\](.*?)\[/attachment\]", r'<span class="attach">📎 \1</span>'),
    ]
    for pat, repl in rules:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE | re.DOTALL)
    # Decode numeric entities inside href="..." and src="..." (phpBB obfuscates URLs)
    s = re.sub(r'(href|src)="([^"]*)"',
               lambda m: f'{m.group(1)}="{RE_NUMERIC_ENTITY.sub(lambda x: chr(int(x.group(1))), m.group(2))}"',
               s)
    # Convert newlines to <br> outside <pre>/<code>
    parts = re.split(r"(<pre>.*?</pre>)", s, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if part.startswith("<pre>"):
            continue
        parts[i] = part.replace("\r\n", "\n").replace("\n", "<br>\n")
    return "".join(parts)


def fmt_time(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%a %b %d, %Y %I:%M %p")


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


# ----------------------------- HTML templates ---------------------------------

STYLE_HREF = "style.css"


def page_header(title: str, depth: int = 0) -> str:
    css = ("../" * depth) + STYLE_HREF
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{css}">
<script>
(function() {{
  var t = localStorage.getItem('forum-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
}})();
</script>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>FiveTech Support Forums</h1>
    <div class="sub">FiveWin / Harbour / xBase community</div>
    <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">🌓</button>
  </div>
  <div class="navbar">
    <a href="{('../' * depth) or ''}index.html">Board index</a>
    <a href="https://github.com/{GISCUS_REPO}/discussions" target="_blank">All discussions</a>
    <a href="https://github.com/login" target="_blank">Login (GitHub)</a>
  </div>
"""


def page_footer() -> str:
    return """
  <div class="footer">
    Static archive · New replies & topics via GitHub Discussions
  </div>
</div>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
  var theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';
  mermaid.initialize({ startOnLoad: true, theme: theme, securityLevel: 'strict' });
  window.__mermaid = mermaid;
</script>
<script>
// Theme toggle
(function() {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', function() {
    var cur = document.documentElement.getAttribute('data-theme');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('forum-theme', next);
    if (window.__mermaid) {
      // Re-render mermaid blocks in new theme
      document.querySelectorAll('pre.mermaid').forEach(function(el) {
        if (el.dataset.src) el.textContent = el.dataset.src;
        else el.dataset.src = el.textContent;
        el.removeAttribute('data-processed');
      });
      window.__mermaid.initialize({ startOnLoad:false, theme: next === 'dark' ? 'dark' : 'default' });
      window.__mermaid.run();
    }
  });
})();
// Code block: select all + collapse/expand
document.addEventListener('click', function(e) {
  var t = e.target;
  if (t.classList && t.classList.contains('cb-select')) {
    e.preventDefault();
    var pre = t.closest('.codebox').querySelector('pre');
    var range = document.createRange();
    range.selectNodeContents(pre);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    try { document.execCommand('copy'); t.textContent = 'Copied!';
      setTimeout(function(){ t.textContent = 'Select all'; }, 1500); }
    catch(_) {}
  } else if (t.classList && t.classList.contains('cb-toggle')) {
    e.preventDefault();
    var box = t.closest('.codebox');
    var pre = box.querySelector('pre');
    if (pre.style.display === 'none') {
      pre.style.display = '';
      t.textContent = 'Collapse';
    } else {
      pre.style.display = 'none';
      t.textContent = 'Expand';
    }
  }
});
</script>
</body>
</html>
"""


def render_index(conn: sqlite3.Connection, out_dir: str) -> None:
    cur = conn.cursor()
    # categories (parent_id=0, type=0 means category)
    cats = cur.execute(
        "SELECT forum_id, forum_name FROM phpbb_forums WHERE parent_id=0 ORDER BY left_id"
    ).fetchall()
    body = []
    for cat_id, cat_name in cats:
        body.append(f'  <div class="cat">{esc(cat_name)}</div>')
        body.append('  <table class="forumlist">')
        body.append("    <thead><tr><th>Forum</th><th class=\"num\">Topics</th><th class=\"num\">Posts</th><th class=\"lastpost\">Last activity</th></tr></thead>")
        body.append("    <tbody>")
        children = cur.execute(
            "SELECT forum_id, forum_name, forum_desc, forum_topics_approved, forum_posts_approved "
            "FROM phpbb_forums WHERE parent_id=? ORDER BY left_id",
            (cat_id,),
        ).fetchall()
        for fid, fname, fdesc, ft, fp in children:
            last = cur.execute(
                "SELECT topic_last_poster_name, topic_last_post_time FROM phpbb_topics "
                "WHERE forum_id=? ORDER BY topic_last_post_time DESC LIMIT 1",
                (fid,),
            ).fetchone()
            last_str = ""
            if last and last[1]:
                last_str = f"by {esc(last[0])}<br>{fmt_time(last[1])}"
            body.append(
                f'      <tr><td><span class="forum-icon"></span>&nbsp;'
                f'<a class="forum-title" href="forum-{fid}.html">{esc(fname)}</a>'
                f'<div class="forum-desc">{esc(strip_xml(fdesc))}</div></td>'
                f'<td class="num">{ft}</td><td class="num">{fp}</td>'
                f'<td class="lastpost">{last_str}</td></tr>'
            )
        body.append("    </tbody></table>")
    out = page_header("FiveTech Support Forums") + "\n".join(body) + page_footer()
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)


def strip_xml(s: str) -> str:
    if not s:
        return ""
    # phpBB stores forum_desc with surrounding <t>...</t> XML; strip basic tags
    return re.sub(r"<[^>]+>", "", s)


def render_forum(conn: sqlite3.Connection, out_dir: str, forum_id: int, page_size: int = 50) -> None:
    cur = conn.cursor()
    forum = cur.execute(
        "SELECT forum_name FROM phpbb_forums WHERE forum_id=?", (forum_id,)
    ).fetchone()
    if not forum:
        return
    fname = forum[0]
    # All visible topics, exclude moved (topic_moved_id != 0 means shadow)
    topics = cur.execute(
        "SELECT topic_id, topic_title, topic_first_poster_name, topic_first_poster_colour, "
        "topic_time, topic_last_poster_name, topic_last_post_time, topic_views, topic_type "
        "FROM phpbb_topics WHERE forum_id=? AND COALESCE(topic_moved_id,0)=0 "
        "ORDER BY topic_type DESC, topic_last_post_time DESC",
        (forum_id,),
    ).fetchall()
    pages = max(1, (len(topics) + page_size - 1) // page_size)
    for p in range(pages):
        chunk = topics[p * page_size : (p + 1) * page_size]
        rows = []
        for t in chunk:
            tid, title, poster, colour, ttime, lname, ltime, views, ttype = t
            sticky = " [sticky]" if ttype and ttype >= 1 else ""
            rows.append(
                f'      <tr><td><span class="forum-icon"></span>&nbsp;'
                f'<a class="forum-title" href="topic-{tid}.html">{esc(title)}</a>{sticky}'
                f'<div class="forum-desc">by <span style="color:#{esc(colour or "555")}">{esc(poster)}</span> · {fmt_time(ttime)}</div></td>'
                f'<td class="num">{views}</td>'
                f'<td class="lastpost">by {esc(lname)}<br>{fmt_time(ltime)}</td></tr>'
            )
        page_links = ""
        if pages > 1:
            page_links = " ".join(
                f'<a href="forum-{forum_id}-page-{i+1}.html">{i+1}</a>' if i != p
                else f"<strong>{i+1}</strong>"
                for i in range(pages)
            )
        new_topic_btn = (
            f'<a class="newbtn" href="{NEW_THREAD_BASE}" target="_blank">+ New topic on GitHub Discussions</a>'
        )
        body = [
            f'  <div class="crumbs"><a href="index.html">Board index</a> {esc(fname)}</div>',
            f'  <div class="cat">{esc(fname)}{new_topic_btn}</div>',
            '  <table class="forumlist">',
            "    <thead><tr><th>Topics</th><th class=\"num\">Views</th><th class=\"lastpost\">Last post</th></tr></thead>",
            "    <tbody>",
            "\n".join(rows),
            "    </tbody></table>",
            f'  <div class="pagination">Page: {page_links}</div>' if page_links else "",
        ]
        fn = f"forum-{forum_id}.html" if p == 0 else f"forum-{forum_id}-page-{p+1}.html"
        out = page_header(f"{fname} - FiveTech Support Forums") + "\n".join(body) + page_footer()
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(out)


POSTS_PER_PAGE = 15


def render_topic(conn: sqlite3.Connection, out_dir: str, topic_id: int,
                 user_cache: dict[int, tuple] | None = None) -> None:
    cur = conn.cursor()
    topic = cur.execute(
        "SELECT topic_title, forum_id FROM phpbb_topics WHERE topic_id=?", (topic_id,)
    ).fetchone()
    if not topic:
        return
    title, forum_id = topic
    forum_name = cur.execute(
        "SELECT forum_name FROM phpbb_forums WHERE forum_id=?", (forum_id,)
    ).fetchone()
    forum_name = forum_name[0] if forum_name else ""
    posts = cur.execute(
        "SELECT post_id, poster_id, post_username, post_subject, post_text, post_time, "
        "bbcode_uid, COALESCE(enable_markdown,0), COALESCE(enable_bbcode,1) "
        "FROM phpbb_posts WHERE topic_id=? ORDER BY post_time, post_id",
        (topic_id,),
    ).fetchall()
    if not posts:
        return
    pages = max(1, (len(posts) + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)
    og_key = f"topic-{topic_id}"

    for p in range(pages):
        chunk = posts[p * POSTS_PER_PAGE : (p + 1) * POSTS_PER_PAGE]
        rendered: list[str] = []
        for pid, uid, uname, subj, ptext, ptime, bbcode_uid, en_md, en_bb in chunk:
            if user_cache is not None and uid in user_cache:
                display, colour, posts_count, regdate, avatar = user_cache[uid]
            else:
                u = cur.execute(
                    "SELECT username, user_colour, user_posts, user_regdate, user_avatar FROM phpbb_users WHERE user_id=?",
                    (uid,),
                ).fetchone()
                if u and u[0]:
                    display, colour, posts_count, regdate, avatar = u
                else:
                    display, colour, posts_count, regdate, avatar = uname or "Guest", "", 0, 0, ""
            body_html = render_post_body(ptext or "", en_md, en_bb)
            if avatar:
                avatar_html = f'<img class="avatar avatar-img" src="avatars/{uid}.{avatar}" alt="" loading="lazy">'
            else:
                avatar_html = '<div class="avatar"></div>'
            rendered.append(f"""  <div class="post" id="p{pid}">
    <div class="poster">
      <div class="name" style="color:#{esc(colour or '105289')}">{esc(display)}</div>
      <div class="rank">Posts: {posts_count}</div>
      {avatar_html}
      Joined: {fmt_time(regdate) if regdate else 'unknown'}
    </div>
    <div class="body">
      <div class="meta">
        <span class="subject">{esc(subj or title)}</span><br>
        Posted: {fmt_time(ptime)}
      </div>
      <div class="content">{body_html}</div>
    </div>
  </div>""")

        # Pagination bar
        nav = ""
        if pages > 1:
            links = []
            for i in range(pages):
                fn = f"topic-{topic_id}.html" if i == 0 else f"topic-{topic_id}-page-{i+1}.html"
                if i == p:
                    links.append(f"<strong>{i+1}</strong>")
                else:
                    links.append(f'<a href="{fn}">{i+1}</a>')
            nav = f'<div class="pagination">Page: {" ".join(links)} ({len(posts)} posts)</div>'

        giscus = f"""
  <div class="giscus-wrap">
    <h3>Continue the discussion</h3>
    <script src="https://giscus.app/client.js"
      data-repo="{GISCUS_REPO}"
      data-repo-id="{GISCUS_REPO_ID}"
      data-category="{GISCUS_CATEGORY}"
      data-category-id="{GISCUS_CATEGORY_ID}"
      data-mapping="og:title"
      data-strict="0"
      data-reactions-enabled="1"
      data-emit-metadata="0"
      data-input-position="bottom"
      data-theme="preferred_color_scheme"
      data-lang="es"
      data-loading="lazy"
      crossorigin="anonymous"
      async></script>
    <noscript>JavaScript required to load Giscus comments.</noscript>
  </div>
"""
        body = (
            f'  <div class="crumbs"><a href="index.html">Board index</a> '
            f'<a href="forum-{forum_id}.html">{esc(forum_name)}</a> {esc(title)}</div>\n'
            + nav
            + "\n".join(rendered)
            + nav
            + (giscus if p == pages - 1 else "")
        )
        # custom header with og:title for stable Giscus mapping across pages
        head = (
            f'<!doctype html>\n<html lang="es">\n<head>\n'
            f'<meta charset="utf-8">\n'
            f'<title>{esc(title)} - FiveTech Support Forums</title>\n'
            f'<meta property="og:title" content="{og_key}">\n'
            f'<link rel="stylesheet" href="style.css">\n'
            f'<script>(function() {{ var t = localStorage.getItem("forum-theme") || "dark"; '
            f'document.documentElement.setAttribute("data-theme", t); }})();</script>\n'
            f'</head>\n<body>\n<div class="wrap">\n'
            f'  <div class="header"><h1>FiveTech Support Forums</h1>'
            f'<div class="sub">FiveWin / Harbour / xBase community</div>'
            f'<button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">🌓</button></div>\n'
            f'  <div class="navbar">'
            f'<a href="index.html">Board index</a>'
            f'<a href="https://github.com/{GISCUS_REPO}/discussions" target="_blank">All discussions</a>'
            f'<a href="https://github.com/login" target="_blank">Login (GitHub)</a></div>\n'
        )
        out = head + body + page_footer()
        fn = f"topic-{topic_id}.html" if p == 0 else f"topic-{topic_id}-page-{p+1}.html"
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out_dir")
    ap.add_argument("--limit-forum", type=int, default=0,
                    help="Generate only this forum_id (and its topics)")
    ap.add_argument("--limit-topics", type=int, default=0,
                    help="Generate at most N topics per forum")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    # copy style.css
    src_css = os.path.join(os.path.dirname(__file__), "..", "style.css")
    if os.path.exists(src_css):
        with open(src_css, "r", encoding="utf-8") as f:
            css = f.read()
        # add a couple of extra rules used in generated pages
        css += """
.cat .newbtn { float:right; font-weight:normal; background:#fff; color:#0d4a72;
  padding:2px 8px; border-radius:3px; font-size:11px; text-decoration:none; }
.pagination { padding:8px; font-size:11px; }
blockquote { background:#f4f4f4; border-left:3px solid #b9c7d2; padding:6px 10px;
  margin:6px 0; }
blockquote cite { display:block; font-style:italic; color:#777; font-size:10px; }
.attach { background:#fffbe6; padding:1px 4px; border:1px solid #f0d000; }
.codebox { background:#fff; border:1px solid #b9c7d2; margin:6px 0; }
.codebox .codehead { background:#ecf3f7; border-bottom:1px solid #b9c7d2;
  padding:3px 8px; font-size:10px; color:#536482; }
.codebox .codehead span { font-weight:bold; }
.codebox .codehead a { margin-left:10px; color:#105289; cursor:pointer; }
.codebox pre { margin:0; padding:8px 10px; max-height:400px; overflow:auto;
  background:#fafafa; font-family:Consolas, "Courier New", monospace; font-size:11px;
  white-space:pre-wrap; word-break:break-word; }
img.avatar-img { width:80px; height:80px; object-fit:cover; border:2px solid #fff;
  outline:1px solid #b9c7d2; margin:6px 0; display:block; }
html[data-theme="dark"] img.avatar-img { border-color:#1f3047; outline-color:#1f3047; }
.theme-toggle { position:absolute; top:18px; right:18px; background:rgba(255,255,255,0.15);
  color:#fff; border:1px solid rgba(255,255,255,0.4); border-radius:4px;
  padding:4px 10px; cursor:pointer; font-size:14px; }
.theme-toggle:hover { background:rgba(255,255,255,0.3); }
.header { position:relative; }
pre.mermaid { background:#fff; border:1px solid #b9c7d2; padding:10px; text-align:center;
  white-space:normal; }

/* ==================== DARK THEME ==================== */
html[data-theme="dark"] body {
  background:#0e1620 url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="1" height="200"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%23142030"/><stop offset="1" stop-color="%230e1620"/></linearGradient></defs><rect width="1" height="200" fill="url(%23g)"/></svg>') repeat-x top;
  color:#c8d4e0;
}
html[data-theme="dark"] a { color:#5cb0ff; }
html[data-theme="dark"] a:hover { color:#ff7a8c; }
html[data-theme="dark"] .header { background:linear-gradient(180deg,#1a4a78 0%,#0a2742 100%);
  border-color:#082135; }
html[data-theme="dark"] .navbar { background:#142030; border-color:#1f3047; color:#c8d4e0; }
html[data-theme="dark"] .crumbs { color:#7aa6d0; }
html[data-theme="dark"] .cat { background:linear-gradient(180deg,#1a4a78 0%,#0a2742 100%);
  border-color:#082135; }
html[data-theme="dark"] table.forumlist { background:#162130; border-color:#1f3047; color:#c8d4e0; }
html[data-theme="dark"] table.forumlist th { background:#1d2d42; color:#9cb8d8;
  border-color:#1f3047; }
html[data-theme="dark"] table.forumlist td { border-color:#1a2638; }
html[data-theme="dark"] table.forumlist tr:nth-child(even) td { background:#192536; }
html[data-theme="dark"] .num, html[data-theme="dark"] table.forumlist th { color:#9cb8d8; }
html[data-theme="dark"] .forum-desc, html[data-theme="dark"] .footer { color:#7a8a9e; }
html[data-theme="dark"] .post { background:#162130; border-color:#1f3047; }
html[data-theme="dark"] .poster { background:#1a2638; border-color:#1f3047; }
html[data-theme="dark"] .body .meta { border-color:#1f3047; color:#7a8a9e; }
html[data-theme="dark"] .body .content { color:#c8d4e0; }
html[data-theme="dark"] .body .content code { background:#1a2638; border-color:#1f3047;
  color:#e8a86f; }
html[data-theme="dark"] .codebox { background:#162130; border-color:#1f3047; }
html[data-theme="dark"] .codebox .codehead { background:#1a2638; border-color:#1f3047;
  color:#9cb8d8; }
html[data-theme="dark"] .codebox .codehead a { color:#5cb0ff; }
html[data-theme="dark"] .codebox pre { background:#0e1620; color:#c8d4e0; }
html[data-theme="dark"] blockquote { background:#1a2638; border-color:#5cb0ff; }
html[data-theme="dark"] .footer { background:#142030; border-color:#1f3047; }
html[data-theme="dark"] pre.mermaid { background:#162130; border-color:#1f3047; }
html[data-theme="dark"] .body .content pre { background:#0e1620; border-color:#1f3047;
  color:#c8d4e0; }
"""
        with open(os.path.join(args.out_dir, "style.css"), "w", encoding="utf-8") as f:
            f.write(css)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA query_only = 1")

    print("[1/3] index...")
    render_index(conn, args.out_dir)

    print("[2/3] forums...")
    cur = conn.cursor()
    if args.limit_forum:
        forums = [(args.limit_forum,)]
    else:
        forums = cur.execute(
            "SELECT forum_id FROM phpbb_forums WHERE forum_type=1 ORDER BY left_id"
        ).fetchall()
    for (fid,) in forums:
        render_forum(conn, args.out_dir, fid)

    print("[3/3] topics...")
    print("   loading user cache...")
    # Scan avatars dir to map user_id -> ext (if avatars present)
    avatar_dir = os.path.join(args.out_dir, "avatars")
    avatar_map: dict[int, str] = {}
    if os.path.isdir(avatar_dir):
        for fn in os.listdir(avatar_dir):
            base, ext = os.path.splitext(fn)
            try:
                avatar_map[int(base)] = ext.lstrip(".")
            except ValueError:
                pass
    print(f"   {len(avatar_map)} avatars found")
    user_cache = {
        row[0]: (row[1], row[2], row[3], row[4], avatar_map.get(row[0], ""))
        for row in cur.execute(
            "SELECT user_id, username, user_colour, user_posts, user_regdate, user_avatar FROM phpbb_users"
        )
    }
    print(f"   {len(user_cache)} users cached")
    n = 0
    t0 = time.time()
    for (fid,) in forums:
        q = "SELECT topic_id FROM phpbb_topics WHERE forum_id=? AND COALESCE(topic_moved_id,0)=0"
        params: tuple = (fid,)
        if args.limit_topics:
            q += " ORDER BY topic_last_post_time DESC LIMIT ?"
            params = (fid, args.limit_topics)
        for (tid,) in cur.execute(q, params).fetchall():
            render_topic(conn, args.out_dir, tid, user_cache=user_cache)
            n += 1
            if n % 500 == 0:
                print(f"   {n} topics in {time.time()-t0:.1f}s")
    print(f"Done. {n} topics generated.")


if __name__ == "__main__":
    main()
