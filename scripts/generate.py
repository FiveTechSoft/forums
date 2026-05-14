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


# Secret redaction. Patterns match common live-credential formats. We replace the
# match with [REDACTED:type] so the post still reads sensibly but no functional
# secret leaks. Original DB stays untouched — this only sanitizes generated HTML.
SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-[A-Za-z0-9]{20,}", "OPENAI_KEY"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}", "OPENAI_KEY"),
    (r"AIza[A-Za-z0-9_\-]{35}", "GOOGLE_API_KEY"),
    (r"\bsk\.[A-Za-z0-9_\-]{40,}\b", "MAPBOX_SECRET"),
    (r"\bpk\.eyJ[A-Za-z0-9._\-]{60,}", "MAPBOX_PUBLIC"),
    (r"\b\d{8,12}:[A-Za-z0-9_\-]{30,40}\b", "TELEGRAM_BOT"),
    (r"AKIA[0-9A-Z]{16}", "AWS_ACCESS_KEY"),
    (r"ghp_[A-Za-z0-9]{36}", "GITHUB_PAT"),
    (r"github_pat_[A-Za-z0-9_]{60,}", "GITHUB_PAT"),
    (r"gho_[A-Za-z0-9]{36}", "GITHUB_OAUTH"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "SLACK_TOKEN"),
    (r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----", "PRIVATE_KEY_BLOCK"),
]
SECRET_REGEX = [(re.compile(p), tag) for p, tag in SECRET_PATTERNS]


def redact_secrets(text: str) -> str:
    if not text:
        return text
    for rx, tag in SECRET_REGEX:
        text = rx.sub(f"[REDACTED:{tag}]", text)
    return text

GISCUS_REPO = "FiveTechSoft/forums"
GISCUS_REPO_ID = "R_kgDOSYw8Sw"
GISCUS_CATEGORY = "General"
GISCUS_CATEGORY_ID = "DIC_kwDOSYw8S84C8qKa"

NEW_THREAD_BASE = (
    "https://github.com/FiveTechSoft/forums/discussions/new?category=general"
)


# ----------------------------- BBCode -> HTML ---------------------------------
# Strip phpBB :uid markers like [b:abcd1234] -> [b]
RE_UID = re.compile(r":[a-z0-9]{4,8}(?=[\]:])", re.IGNORECASE)


RE_SMILEY_COMMENT = re.compile(r"<!--\s*s[^>]*?-->", re.IGNORECASE)
RE_SMILEY_IMG = re.compile(r'<img\s+src="\{SMILIES_PATH\}/([^"]+?)"[^>]*?/?>', re.IGNORECASE)
RE_NUMERIC_ENTITY = re.compile(r"&#(\d+);")
RE_FW_DIV = re.compile(r'<div\s+class="fw"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE)


def _build_css() -> str:
    return r"""/* FiveTech Support Forums - prosilver-derived palette + dark/light themes */
* { box-sizing: border-box; }
:root {
  --c01:#1e90ff; --c02:#fff; --c03:#eee; --c04:#ddd; --c05:#ccc;
  --c06:#bbb; --c07:#aaa; --c08:#a5a5a5; --c09:#d31141; --c10:#ead4d9;
  --c11:#000; --c12:#333; --c13:#444; --c14:#fff; --c15:#fff;
  --bg:        var(--c02);
  --fg:        var(--c11);
  --fg-muted:  var(--c12);
  --row-alt:   #f9f9f9;
  --border:    var(--c04);
  --header-bg: linear-gradient(180deg,#12a3eb 0%,#00608f 100%);
  --header-fg: #fff;
  --link:      #105289;
  --link-hover:#d31141;
  --pre-bg:    #fafafa;
  --quote-bg:  #f4f4f4;
}
html[data-theme="dark"] {
  --c02:#222; --c03:#333; --c04:#444; --c05:#555;
  --c06:#666; --c07:#6b6b6b; --c08:#7a7a7a; --c10:#6a1b2e;
  --c11:#fff; --c12:#ccc; --c13:#ddd; --c14:#000;
  --bg:#0e1620;
  --fg:#c8d4e0;
  --fg-muted:#9cb8d8;
  --row-alt:#192536;
  --border:#1f3047;
  --header-bg:linear-gradient(180deg,#1a4a78 0%,#0a2742 100%);
  --pre-bg:#0e1620;
  --quote-bg:#1a2638;
  --link:#5cb0ff;
  --link-hover:#ff7a8c;
  --user-hi:#ffd166;
  --date-hi:#e8eef6;
}
html[data-theme="dark"] .lastpost { color: var(--date-hi); }
html[data-theme="dark"] .lastpost a { color: var(--date-hi); }
html[data-theme="dark"] .lastpost a:hover { color: var(--link-hover); }
html[data-theme="dark"] .forum-desc a[href^="user-"],
html[data-theme="dark"] .lastpost a[href^="user-"],
html[data-theme="dark"] .forum-desc span[style*="color"],
html[data-theme="dark"] .lastpost span[style*="color"] { color: var(--user-hi) !important; font-weight:bold; }
html[data-theme="dark"] .poster .name a,
html[data-theme="dark"] .poster .name span { color: var(--user-hi) !important; }
body {
  margin:0; font-family: Verdana, Arial, Helvetica, sans-serif; font-size:12px;
  background: var(--bg); color: var(--fg);
}
a { color: var(--link); text-decoration:none; }
a:hover { color: var(--link-hover); text-decoration:underline; }
img { max-width:100%; height:auto; }
.wrap { max-width:1100px; margin:0 auto; padding:8px; }
.header {
  position:relative;
  background: var(--header-bg); color: var(--header-fg);
  padding:14px 20px; border-radius:6px 6px 0 0;
  display:flex; align-items:center; gap:18px;
}
.header .logo img { display:block; max-height:60px; width:auto; }
.header .header-text { flex:1; }
.header h1 { margin:0; font-size:22px; font-weight:bold; letter-spacing:0.3px; }
.header .sub { font-size:11px; opacity:0.9; margin-top:3px; }
.theme-toggle { background:rgba(255,255,255,0.15); color:#fff;
  border:1px solid rgba(255,255,255,0.4); border-radius:4px;
  padding:4px 10px; cursor:pointer; font-size:14px; }
.theme-toggle:hover { background:rgba(255,255,255,0.3); }
.navbar {
  background: var(--bg); border:1px solid var(--border); border-top:none;
  padding:6px 12px; font-size:11px;
}
.navbar a { margin-right:14px; font-weight:bold; }
.crumbs { padding:8px 0; font-size:11px; color: var(--fg-muted); }
.crumbs a::after { content:" »"; color: var(--c06); }
.cat {
  background: var(--header-bg); color:#fff;
  padding:6px 10px; font-weight:bold; font-size:12px;
  border:1px solid var(--border); border-radius:4px 4px 0 0;
  margin-top:14px; position:relative;
}
.cat .newbtn { position:absolute; right:8px; top:4px; background: var(--c02);
  color: var(--link); padding:2px 8px; border-radius:3px; font-size:11px;
  text-decoration:none; font-weight:normal; }
table.forumlist { width:100%; border-collapse:collapse; background: var(--c02);
  border:1px solid var(--border); }
table.forumlist th { background: var(--c03); padding:5px 8px; text-align:left;
  border-bottom:1px solid var(--border); font-size:11px; color: var(--fg-muted); }
table.forumlist td { padding:8px 10px; border-bottom:1px solid var(--border); vertical-align:middle; }
table.forumlist tr:nth-child(even) td { background: var(--row-alt); }
.forum-icon { width:24px; height:24px; background: var(--c01); border-radius:50%;
  display:inline-block; vertical-align:middle; box-shadow:inset 0 -2px 4px rgba(0,0,0,0.2); }
.forum-title { font-weight:bold; font-size:12px; }
.forum-desc { color: var(--fg-muted); font-size:11px; margin-top:2px; }
.num { text-align:center; width:80px; font-weight:bold; color: var(--fg-muted); }
.lastpost { width:240px; font-size:11px; }
.pagination { padding:8px 0; font-size:11px; }
.pagination a, .pagination strong { padding:2px 6px; border:1px solid var(--border);
  margin-right:3px; background: var(--c02); border-radius:3px; }
.pagination strong { background: var(--c01); color:#fff; border-color: var(--c01); }

/* posts */
.post { background: var(--c02); border:1px solid var(--border); margin:8px 0;
  display:grid; grid-template-columns:180px 1fr; }
.poster { background: var(--c03); padding:12px; border-right:1px solid var(--border);
  font-size:11px; color: var(--fg); }
.poster .name { font-weight:bold; font-size:13px; }
.poster .rank { color: var(--fg-muted); font-style:italic; margin:4px 0; }
.poster .joined, .poster .location { color: var(--fg-muted); margin-top:4px; }
.body { padding:12px 16px; color: var(--fg); }
.body .meta { border-bottom:1px solid var(--border); padding-bottom:6px; margin-bottom:10px;
  font-size:11px; color: var(--fg-muted); }
.body .subject { font-weight:bold; color: var(--link); font-size:12px; }
.body .content { font-size:13px; line-height:1.55; color: var(--fg); word-wrap:break-word; }
.body .content p { margin:0 0 10px 0; }
.body .content code { background: var(--c03); border:1px solid var(--border);
  padding:1px 4px; font-family:Consolas, monospace; font-size:11px; }
.body .content pre { background: var(--pre-bg); border:1px solid var(--border);
  padding:8px; overflow-x:auto; font-family:Consolas, monospace; font-size:11px;
  white-space:pre-wrap; }
.body .content img { max-width:100%; }
.signature { border-top:1px solid var(--border); margin-top:14px; padding-top:8px;
  font-size:11px; color: var(--fg-muted); }

/* avatars */
img.avatar-img { width:90px; height:90px; object-fit:cover; border:1px solid var(--border);
  margin:6px 0; display:block; }
.poster .avatar { width:80px; height:80px; background: var(--c01); border:1px solid var(--border);
  margin:6px 0; }

/* smileys */
img.smiley { vertical-align:middle; max-height:18px; width:auto; display:inline; }

/* code box (BBCode [code]) */
.codebox { background: var(--c02); border:1px solid var(--border); margin:6px 0; }
.codebox .codehead { background: var(--c03); border-bottom:1px solid var(--border);
  padding:3px 8px; font-size:10px; color: var(--fg-muted); }
.codebox .codehead span { font-weight:bold; }
.codebox .codehead a { margin-left:10px; cursor:pointer; }
.codebox pre { margin:0; padding:8px 10px; max-height:400px; overflow:auto;
  background: var(--pre-bg); font-family:Consolas, monospace; font-size:11px;
  white-space:pre-wrap; word-break:break-word; color: var(--fg); }

/* quote */
blockquote { background: var(--quote-bg); border-left:3px solid var(--c01);
  padding:6px 10px; margin:6px 0; }
blockquote cite { display:block; font-style:italic; color: var(--fg-muted); font-size:10px; }

/* horizontal rule from markdown --- (was rendering as faux strikethrough) */
.body .content hr { border:0; border-top:1px solid var(--border);
  margin:14px 0; height:0; background:transparent; }

/* mermaid */
pre.mermaid { background: var(--c02); border:1px solid var(--border); padding:10px;
  text-align:center; white-space:normal; }

.attach { background:#fffbe6; padding:1px 4px; border:1px solid #f0d000; color:#000; }

/* giscus */
.giscus-wrap { background: var(--c02); border:1px solid var(--border); margin-top:14px;
  padding:12px; }
.giscus-wrap h3 { margin:0 0 10px 0; color: var(--fg-muted); font-size:13px;
  border-bottom:1px solid var(--border); padding-bottom:6px; }

/* footer */
.footer { background: var(--c03); border:1px solid var(--border); border-top:none;
  padding:10px; font-size:10px; color: var(--fg-muted); text-align:center;
  border-radius:0 0 6px 6px; }

/* user profile (head of user-{id}.html) */
.userprofile { background: var(--c02); border:1px solid var(--border); margin:8px 0;
  border-top:none; padding:12px 16px; }
.userprofile-meta { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.userprofile-meta .name { font-weight:bold; font-size:14px; }
.userprofile-meta .rank, .userprofile-meta .joined {
  color: var(--fg-muted); font-size:11px; }
.userprofile-meta img.avatar-img { margin:0; }
.userprofile-meta .avatar { margin:0; }

/* memberlist */
.memberlist { width:100%; border-collapse:collapse; background: var(--c02);
  border:1px solid var(--border); margin-top:8px; }
.memberlist th { background: var(--c03); padding:5px 8px; text-align:left;
  border-bottom:1px solid var(--border); font-size:11px; color: var(--fg-muted); }
.memberlist td { padding:6px 10px; border-bottom:1px solid var(--border); }
.memberlist tr:nth-child(even) td { background: var(--row-alt); }
.memberlist img.avatar-img { width:40px; height:40px; }

@media (max-width:700px) {
  .header { flex-direction:column; align-items:flex-start; }
  .post { grid-template-columns:1fr; }
  .poster { border-right:none; border-bottom:1px solid var(--border); }
  .num, .lastpost { display:none; }
}
"""


_LANG_MAP = {
    "fw": "harbour", "fwh": "harbour", "harbour": "harbour", "xharbour": "harbour",
    "clipper": "harbour", "prg": "harbour",
    "c": "c", "cpp": "cpp", "c++": "cpp",
    "js": "javascript", "javascript": "javascript",
    "py": "python", "python": "python",
    "sql": "sql", "html": "html", "css": "css", "json": "json",
    "sh": "bash", "bash": "bash", "shell": "bash",
    "php": "php", "ini": "ini", "xml": "xml", "yaml": "yaml",
}


def _emit_codebox(body: str, lang_hint: str) -> str:
    body = _flatten_fw_block(body)
    body = body.lstrip("\r\n").rstrip()
    lang = _LANG_MAP.get(lang_hint.lower().strip(), "harbour" if not lang_hint else lang_hint.lower().strip())
    safe = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<div class="codebox"><div class="codehead">'
        f'<span>Code{f" ({lang_hint})" if lang_hint else ""}:</span> '
        '<a href="#" class="cb-select">Select all</a> '
        '<a href="#" class="cb-toggle">Collapse</a></div>'
        f'<pre><code class="language-{lang}">{safe}</code></pre></div>'
    )


def _flatten_fw_block(body: str) -> str:
    """phpBB stores [code=fw] bodies as pre-rendered HTML with inline color spans,
    &nbsp;, &#40; and <br/>. Convert back to plain code text so highlight.js can
    do its own coloring matching the active theme."""
    m = RE_FW_DIV.search(body)
    if m:
        body = m.group(1)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</?span[^>]*>", "", body, flags=re.IGNORECASE)
    # decode named + numeric entities
    body = body.replace("&nbsp;", " ").replace("&quot;", '"')
    body = body.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    body = RE_NUMERIC_ENTITY.sub(lambda m: chr(int(m.group(1))), body)
    return body
RE_MERMAID_BB = re.compile(r"\[mermaid\](.*?)\[/mermaid\]", re.IGNORECASE | re.DOTALL)
RE_MERMAID_FENCE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

# phpBB 3.2+ stores every post_text wrapped in either <r>...</r> (rich — BBCode
# already parsed to s9e/text-formatter XML) or <t>...</t> (plain text, no markup).
# Older dumps stored raw BBCode with no wrapper. The renderer below detects the
# wrapper and walks the XML into HTML directly; without it the XML tags leaked
# into the output as literal text and `<URL url=...>` lost its hyperlink.
_RE_XML_WRAPPER = re.compile(r'^\s*<([rt])(?:\s[^>]*)?>(.*)</\1>\s*$', re.DOTALL)


def _phpbb_xml_to_html(inner: str) -> str:
    """Convert the contents of a phpBB <r> rich-XML wrapper into HTML.
    Caller already stripped the outer <r>...</r>. Mermaid placeholders inserted
    upstream pass through untouched."""
    # s9e marks each BBCode token's source range with <s>[tag]</s> / <e>[/tag]</e>
    # and inserts <i>...</i> for insignificant whitespace. None of it carries
    # semantic content — strip before walking the real elements.
    inner = re.sub(r'<s>[^<]*</s>', '', inner)
    inner = re.sub(r'<e>[^<]*</e>', '', inner)
    inner = re.sub(r'<i>[^<]*</i>', '', inner)
    inner = re.sub(r'<br\s*/>', '<br>', inner)

    # URL / EMAIL / IMG / LINK_TEXT — restore hyperlinks lost when the s9e tags
    # were left raw. Fall back to the URL itself when the rendered label is empty.
    def _url(m: re.Match[str]) -> str:
        href = html.unescape(m.group(1))
        label = m.group(2).strip() or html.escape(href)
        return f'<a href="{html.escape(href, quote=True)}" rel="noopener">{label}</a>'

    inner = re.sub(r'<URL url="([^"]+)"[^>]*>(.*?)</URL>', _url, inner, flags=re.DOTALL)
    inner = re.sub(
        r'<EMAIL email="([^"]+)"[^>]*>(.*?)</EMAIL>',
        lambda m: f'<a href="mailto:{html.escape(html.unescape(m.group(1)), quote=True)}">'
                  f'{m.group(2).strip() or html.escape(html.unescape(m.group(1)))}</a>',
        inner, flags=re.DOTALL,
    )
    inner = re.sub(
        r'<IMG src="([^"]+)"[^>]*>.*?</IMG>',
        lambda m: f'<img src="{html.escape(html.unescape(m.group(1)), quote=True)}" alt="" loading="lazy">',
        inner, flags=re.DOTALL,
    )
    inner = re.sub(
        r'<LINK_TEXT text="([^"]+)"[^>]*>(.*?)</LINK_TEXT>',
        lambda m: f'<a href="{html.escape(html.unescape(m.group(1)), quote=True)}" rel="noopener">'
                  f'{m.group(2).strip() or html.escape(html.unescape(m.group(1)))}</a>',
        inner, flags=re.DOTALL,
    )

    # Inline formatting. phpBB uses uppercase element names for BBCode-derived
    # tags, so the match is case-sensitive (lowercase <i> above is whitespace).
    inner = re.sub(r'<B>(.*?)</B>', r'<strong>\1</strong>', inner, flags=re.DOTALL)
    inner = re.sub(r'<I>(.*?)</I>', r'<em>\1</em>', inner, flags=re.DOTALL)
    inner = re.sub(r'<U>(.*?)</U>',
                   r'<span style="text-decoration:underline">\1</span>',
                   inner, flags=re.DOTALL)
    inner = re.sub(r'<S>(.*?)</S>', r'<del>\1</del>', inner, flags=re.DOTALL)
    inner = re.sub(
        r'<COLOR color="([^"]+)"[^>]*>(.*?)</COLOR>',
        lambda m: f'<span style="color:{html.escape(html.unescape(m.group(1)), quote=True)}">{m.group(2)}</span>',
        inner, flags=re.DOTALL,
    )
    inner = re.sub(
        r'<SIZE size="([^"]+)"[^>]*>(.*?)</SIZE>',
        lambda m: f'<span style="font-size:{html.escape(html.unescape(m.group(1)), quote=True)}%">{m.group(2)}</span>',
        inner, flags=re.DOTALL,
    )

    # Emoticon wrapper — keep the literal ":-)" / ":wink:" inside.
    inner = re.sub(r'<E>([^<]*)</E>', r'\1', inner)

    # QUOTE — author attribute populates the cite line.
    inner = re.sub(
        r'<QUOTE author="([^"]+)"[^>]*>(.*?)</QUOTE>',
        lambda m: f'<blockquote><cite>{html.escape(html.unescape(m.group(1)))} wrote:</cite>{m.group(2)}</blockquote>',
        inner, flags=re.DOTALL,
    )
    inner = re.sub(r'<QUOTE[^>]*>(.*?)</QUOTE>', r'<blockquote>\1</blockquote>', inner, flags=re.DOTALL)

    # Lists. `type="decimal"` (or "1") = ordered.
    inner = re.sub(r'<LIST\s+type="(?:decimal|1)"[^>]*>(.*?)</LIST>', r'<ol>\1</ol>', inner, flags=re.DOTALL)
    inner = re.sub(r'<LIST[^>]*>(.*?)</LIST>', r'<ul>\1</ul>', inner, flags=re.DOTALL)
    inner = re.sub(r'<LI[^>]*>(.*?)</LI>', r'<li>\1</li>', inner, flags=re.DOTALL)
    inner = re.sub(r'<\*>(.*?)</\*>', r'<li>\1</li>', inner, flags=re.DOTALL)

    # Attachment — display label only; the actual file lives outside the archive.
    inner = re.sub(
        r'<ATTACHMENT[^>]*>(.*?)</ATTACHMENT>',
        r'<span class="attach">📎 \1</span>',
        inner, flags=re.DOTALL,
    )

    # CODE: phpBB pre-renders the body to HTML inside the <CODE> element (often
    # with a div.fw wrapper). Run it through the same flattener the BBCode path
    # uses so highlight.js can re-colour against the active theme.
    def _xml_code(m: re.Match[str]) -> str:
        lang = (m.group(1) or "").strip()
        return _emit_codebox(m.group(2), lang)

    inner = re.sub(r'<CODE(?:\s+lang="([^"]*)")?[^>]*>(.*?)</CODE>',
                   _xml_code, inner, flags=re.DOTALL)

    # YouTube — accept either bare id or full URL inside.
    inner = re.sub(
        r'<YOUTUBE[^>]*>([^<]+)</YOUTUBE>',
        r'<iframe width="560" height="315" src="https://www.youtube.com/embed/\1"'
        r' frameborder="0" allowfullscreen></iframe>',
        inner,
    )

    return inner


def render_post_body(text: str, enable_markdown: int, enable_bbcode: int) -> str:
    """Render stored post_text to HTML. Detection order:
       1. phpBB 3.2+ s9e XML wrapper (<r>/<t>) — converted directly to HTML.
       2. BBCode (if [tag] markers present) — legacy bbcode_to_html path.
       3. Markdown — when enable_markdown=1 and no BBCode markers exist.
    Mermaid blocks survive every path via placeholder substitution."""
    if not text:
        return ""
    text = redact_secrets(text)
    placeholders: list[str] = []

    def stash_bb(m: re.Match[str]) -> str:
        placeholders.append(m.group(1).strip())
        return f"\x00MERMAID{len(placeholders)-1}\x00"

    text2 = RE_MERMAID_BB.sub(stash_bb, text)

    body: str | None = None
    wrap = _RE_XML_WRAPPER.match(text2)
    if wrap:
        kind, inner = wrap.group(1), wrap.group(2)
        if kind == "r":
            body = _phpbb_xml_to_html(inner)
        else:
            # <t> is plain text. Convert <br/> back to real newlines so the
            # downstream markdown/BBCode path treats the post normally.
            text2 = re.sub(r'<br\s*/?>', '\n', inner)

    if body is None:
        has_bbcode = bool(re.search(r"\[(code|quote|url|img|b|i|color|size|list|attachment)",
                                    text2, re.IGNORECASE))
        if enable_markdown and not has_bbcode and _MD is not None:
            def stash_md(m: re.Match[str]) -> str:
                placeholders.append(m.group(1).strip())
                return f"\x00MERMAID{len(placeholders)-1}\x00"

            text2 = RE_MERMAID_FENCE.sub(stash_md, text2)
            _MD.reset()
            body = _MD.convert(text2)
        else:
            body = bbcode_to_html(text2)

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
    # Replace phpBB smiley imgs with relative URL pointing to bundled smilies dir.
    s = RE_SMILEY_COMMENT.sub("", s)
    s = RE_SMILEY_IMG.sub(r'<img class="smiley" src="smilies/\1" alt=":-)" loading="lazy">', s)
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
        # placeholder — code blocks get post-processed below to flatten & language-tag.
        (r"\[code(?:=([^\]]*))?\](.*?)\[/code\]",
         lambda m: _emit_codebox(m.group(2), m.group(1) or "")),
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


POSTS_PER_PAGE = 15
USER_POSTS_PER_PAGE = 50


def fmt_time(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%a %b %d, %Y %I:%M %p")


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


# Cache of {topic_id: {post_id: page_within_topic}} so each topic's post ordering
# is computed once and reused for every "jump to last post" / "user posts" link.
# Keyed on POSTS_PER_PAGE which is constant; if it ever varies we'd key the cache too.
_topic_pages_cache: dict[int, dict[int, int]] = {}


def get_post_page(cur: sqlite3.Cursor, topic_id: int, post_id: int) -> int:
    """Return 1-based page that post_id lives on inside topic_id."""
    if not topic_id or not post_id:
        return 1
    pages = _topic_pages_cache.get(topic_id)
    if pages is None:
        rows = cur.execute(
            "SELECT post_id FROM phpbb_posts WHERE topic_id=? ORDER BY post_time, post_id",
            (topic_id,),
        ).fetchall()
        pages = {pid: (i // POSTS_PER_PAGE) + 1 for i, (pid,) in enumerate(rows)}
        _topic_pages_cache[topic_id] = pages
    return pages.get(post_id, 1)


def topic_post_url(topic_id: int, post_id: int, page: int) -> str:
    fn = f"topic-{topic_id}.html" if page == 1 else f"topic-{topic_id}-page-{page}.html"
    return f"{fn}#p{post_id}"


# Username -> user_id resolver, populated once in main(). Used as a fallback for
# rows whose poster_id column was 0/missing (e.g. older dumps lacking the column).
_name_to_uid: dict[str, int] = {}


def resolve_uid(uid: int, name: str) -> int:
    if uid and uid > 0:
        return uid
    if name:
        return _name_to_uid.get(name, 0)
    return 0


def user_link(uid: int, name: str, colour: str = "") -> str:
    """Render a username, linked to user-{uid}.html when we know the uid.
    Falls back to a styled span (no link) for guests or unknown users."""
    safe = esc(name or "Guest")
    style = f' style="color:#{esc(colour or "105289")}"'
    if uid and uid > 0:
        return f'<a href="user-{uid}.html"{style}>{safe}</a>'
    return f'<span{style}>{safe}</span>'


# ----------------------------- HTML templates ---------------------------------

STYLE_HREF = "style.css"


def page_header(title: str, depth: int = 0) -> str:
    css = ("../" * depth) + STYLE_HREF
    base = ("../" * depth) or ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<link rel="icon" href="{base}favicon.ico">
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
    <a class="logo" href="{base}index.html"><img src="{base}site_logo.svg" alt="FiveTech Support Forums" width="200" height="60"></a>
    <div class="header-text"><h1>FiveTech Support Forums</h1>
    <div class="sub"><a href="https://fivetechsoft.github.io/" target="_blank" rel="noopener">FiveWin</a> / <a href="https://github.com/harbour/core" target="_blank" rel="noopener">Harbour</a> / xBase community</div></div>
    <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">🌓</button>
  </div>
  <div class="navbar">
    <a href="{base}index.html">Board index</a>
    <a href="{base}active-topics.html">Active topics</a>
    <a href="{base}search.html">Search</a>
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
<link id="hljs-theme-dark" rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github-dark.min.css">
<link id="hljs-theme-light" rel="stylesheet" disabled
      href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/core.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/c.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/cpp.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/javascript.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/python.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/sql.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/bash.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/php.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/languages/xml.min.js"></script>
<script>
// Custom Harbour/xBase/Clipper/FiveWin language for highlight.js
hljs.registerLanguage('harbour', function(hljs) {
  var KEYWORDS = {
    keyword: 'function procedure return local static public private memvar parameters '
      + 'if else elseif endif do while loop exit for next case otherwise endcase '
      + 'class endclass method var data inherit from self super hb_codeblock '
      + 'begin sequence end recover using try catch finally throw '
      + 'with object endwith iif and or not is in declare external dynamic field '
      + 'request announce',
    literal: 'nil true false .t. .f. .y. .n.',
    built_in: 'msginfo msgalert msgyesno msgstop msgwarning xbrowse tdialog '
      + 'tbutton tbrush tbar tbtnbmp tdatabase tcontrol twindow tget tsay '
      + 'getdc setcolor messagebox alert msgbox dbusearea dbgotop dbskip '
      + 'dbeval valtype empty len str val alltrim left right substr upper lower '
      + 'eval if hb_aparams hb_hhaskey heval setget pcount valtype'
  };
  return {
    name: 'Harbour',
    aliases: ['hbr', 'hrb', 'fw', 'fwh', 'prg', 'clipper', 'xharbour', 'xbase'],
    case_insensitive: true,
    keywords: KEYWORDS,
    contains: [
      hljs.COMMENT('//', '$'),
      hljs.COMMENT('/\\*', '\\*/'),
      hljs.COMMENT('\\*', '$'),
      { className: 'string', begin: '"', end: '"' },
      { className: 'string', begin: "'", end: "'" },
      { className: 'meta', begin: '#\\s*\\w+' },
      { className: 'number', begin: '\\b\\d+(\\.\\d+)?\\b' },
      { className: 'operator', begin: ':=|==|!=|<>|<=|>=|->' },
    ]
  };
});
hljs.highlightAll();
</script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
  var theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';
  mermaid.initialize({ startOnLoad: true, theme: theme, securityLevel: 'strict' });
  window.__mermaid = mermaid;
</script>
<script>
// Theme toggle (incl. highlight.js stylesheets + mermaid theme)
function applyHljsTheme(theme) {
  var dark = document.getElementById('hljs-theme-dark');
  var light = document.getElementById('hljs-theme-light');
  if (dark)  dark.disabled = (theme !== 'dark');
  if (light) light.disabled = (theme === 'dark');
}
applyHljsTheme(document.documentElement.getAttribute('data-theme'));
(function() {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', function() {
    var cur = document.documentElement.getAttribute('data-theme');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('forum-theme', next);
    applyHljsTheme(next);
    if (window.__mermaid) {
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
  var t = e.target.closest('a.cb-select, a.cb-toggle');
  if (!t) return;
  e.preventDefault();
  var box = t.closest('.codebox');
  var pre = box && box.querySelector('pre');
  if (!pre) return;

  if (t.classList.contains('cb-select')) {
    var text = pre.innerText;
    // 1) visible selection so user sees what was copied
    var range = document.createRange();
    range.selectNodeContents(pre);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    // 2) write to clipboard (async). Fallback to execCommand for old browsers.
    var done = function(ok) {
      t.textContent = ok ? 'Copied!' : 'Select failed';
      t.classList.toggle('copy-ok', ok);
      setTimeout(function(){ t.textContent = 'Select all';
        t.classList.remove('copy-ok'); }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function(){done(true);}, function(){
        try { done(document.execCommand('copy')); } catch(_) { done(false); }
      });
    } else {
      try { done(document.execCommand('copy')); } catch(_) { done(false); }
    }
  } else if (t.classList.contains('cb-toggle')) {
    var hidden = pre.style.display === 'none';
    pre.style.display = hidden ? '' : 'none';
    t.textContent = hidden ? 'Collapse' : 'Expand';
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
                "SELECT topic_id, topic_last_post_id, "
                "COALESCE(topic_last_poster_id,0), topic_last_poster_name, "
                "topic_last_post_time "
                "FROM phpbb_topics WHERE forum_id=? "
                "ORDER BY topic_last_post_time DESC LIMIT 1",
                (fid,),
            ).fetchone()
            last_str = ""
            if last and last[4]:
                ltid, lpid, lpuid, lpname, ltime = last
                lpuid = resolve_uid(lpuid, lpname)
                name_html = user_link(lpuid, lpname)
                page = get_post_page(cur, ltid, lpid) if lpid else 1
                href = topic_post_url(ltid, lpid, page) if lpid else f"topic-{ltid}.html"
                last_str = (
                    f'by {name_html}<br>'
                    f'<a href="{href}" title="Go to last post">{fmt_time(ltime)}</a>'
                )
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
        "SELECT topic_id, topic_title, topic_poster, topic_first_poster_name, "
        "topic_first_poster_colour, topic_time, "
        "topic_last_post_id, COALESCE(topic_last_poster_id,0), topic_last_poster_name, "
        "topic_last_post_time, topic_views, topic_type "
        "FROM phpbb_topics WHERE forum_id=? AND COALESCE(topic_moved_id,0)=0 "
        "ORDER BY topic_type DESC, topic_last_post_time DESC",
        (forum_id,),
    ).fetchall()
    pages = max(1, (len(topics) + page_size - 1) // page_size)
    for p in range(pages):
        chunk = topics[p * page_size : (p + 1) * page_size]
        rows = []
        for t in chunk:
            (tid, title, p_uid, poster, colour, ttime,
             lpid, lp_uid, lname, ltime, views, ttype) = t
            sticky = " [sticky]" if ttype and ttype >= 1 else ""
            p_uid = resolve_uid(p_uid, poster)
            lp_uid = resolve_uid(lp_uid, lname)
            poster_html = user_link(p_uid, poster, colour or "555")
            last_name_html = user_link(lp_uid, lname)
            if lpid:
                lpage = get_post_page(cur, tid, lpid)
                last_href = topic_post_url(tid, lpid, lpage)
            else:
                last_href = f"topic-{tid}.html"
            rows.append(
                f'      <tr><td><span class="forum-icon"></span>&nbsp;'
                f'<a class="forum-title" href="topic-{tid}.html">{esc(title)}</a>{sticky}'
                f'<div class="forum-desc">by {poster_html} · {fmt_time(ttime)}</div></td>'
                f'<td class="num">{views}</td>'
                f'<td class="lastpost">by {last_name_html}<br>'
                f'<a href="{last_href}" title="Go to last post">{fmt_time(ltime)}</a></td></tr>'
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
            sig_html = ""
            location = ""
            if user_cache is not None and uid in user_cache:
                display, colour, posts_count, regdate, avatar, sig_raw, location = user_cache[uid]
            else:
                u = cur.execute(
                    "SELECT username, user_colour, user_posts, user_regdate, user_avatar, "
                    "COALESCE(user_sig,''), '' FROM phpbb_users WHERE user_id=?",
                    (uid,),
                ).fetchone()
                if u and u[0]:
                    display, colour, posts_count, regdate, avatar, sig_raw, location = u
                else:
                    display, colour, posts_count, regdate, avatar, sig_raw, location = uname or "Guest", "", 0, 0, "", "", ""
            body_html = render_post_body(ptext or "", en_md, en_bb)
            if sig_raw:
                sig_html = f'<div class="signature">{render_post_body(sig_raw, 0, 1)}</div>'
            if avatar:
                avatar_html = f'<img class="avatar avatar-img" src="avatars/{uid}.{avatar}" alt="" loading="lazy">'
            else:
                avatar_html = '<div class="avatar"></div>'
            loc_html = f'<div class="location">{esc(location)}</div>' if location else ""
            display_html = user_link(resolve_uid(uid, display), display, colour or "105289")
            rendered.append(f"""  <div class="post" id="p{pid}">
    <div class="poster">
      <div class="name">{display_html}</div>
      <div class="rank">Posts: {posts_count}</div>
      {avatar_html}
      <div class="joined">Joined: {fmt_time(regdate) if regdate else 'unknown'}</div>
      {loc_html}
    </div>
    <div class="body">
      <div class="meta">
        <span class="subject">{esc(subj or title)}</span><br>
        Posted: {fmt_time(ptime)}
      </div>
      <div class="content">{body_html}</div>
      {sig_html}
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
            f'<link rel="icon" href="favicon.ico">\n'
            f'<link rel="stylesheet" href="style.css">\n'
            f'<script>(function() {{ var t = localStorage.getItem("forum-theme") || "dark"; '
            f'document.documentElement.setAttribute("data-theme", t); }})();</script>\n'
            f'</head>\n<body>\n<div class="wrap">\n'
            f'  <div class="header">'
            f'<a class="logo" href="index.html"><img src="site_logo.svg" alt="FiveTech Support Forums" width="200" height="60"></a>'
            f'<div class="header-text"><h1>FiveTech Support Forums</h1>'
            f'<div class="sub"><a href="https://fivetechsoft.github.io/" target="_blank" rel="noopener">FiveWin</a> / <a href="https://github.com/harbour/core" target="_blank" rel="noopener">Harbour</a> / xBase community</div></div>'
            f'<button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle theme">🌓</button></div>\n'
            f'  <div class="navbar">'
            f'<a href="index.html">Board index</a>'
            f'<a href="active-topics.html">Active topics</a>'
            f'<a href="https://github.com/{GISCUS_REPO}/discussions" target="_blank">All discussions</a>'
            f'<a href="https://github.com/login" target="_blank">Login (GitHub)</a></div>\n'
        )
        out = head + body + page_footer()
        fn = f"topic-{topic_id}.html" if p == 0 else f"topic-{topic_id}-page-{p+1}.html"
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(out)


ACTIVE_TOPICS_LIMIT = 100


def render_active_topics(conn: sqlite3.Connection, out_dir: str) -> None:
    """Top N most-recently-active topics across all forums, newest first."""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT t.topic_id, t.forum_id, t.topic_title, "
        "t.topic_poster, t.topic_first_poster_name, t.topic_first_poster_colour, "
        "t.topic_time, t.topic_views, "
        "t.topic_last_post_id, COALESCE(t.topic_last_poster_id,0), "
        "t.topic_last_poster_name, t.topic_last_post_time, "
        "f.forum_name, "
        "(SELECT COUNT(*) FROM phpbb_posts p WHERE p.topic_id=t.topic_id) AS nposts "
        "FROM phpbb_topics t JOIN phpbb_forums f USING(forum_id) "
        "WHERE COALESCE(t.topic_moved_id,0)=0 AND COALESCE(t.topic_visibility,1)=1 "
        "ORDER BY t.topic_last_post_time DESC LIMIT ?",
        (ACTIVE_TOPICS_LIMIT,),
    ).fetchall()
    items = []
    for (tid, fid, title, p_uid, poster, colour, ttime, views,
         lpid, lp_uid, lname, ltime, fname, nposts) in rows:
        p_uid = resolve_uid(p_uid, poster)
        lp_uid = resolve_uid(lp_uid, lname)
        poster_html = user_link(p_uid, poster, colour or "555")
        last_name_html = user_link(lp_uid, lname)
        if lpid:
            lpage = get_post_page(cur, tid, lpid)
            last_href = topic_post_url(tid, lpid, lpage)
        else:
            last_href = f"topic-{tid}.html"
        items.append(
            f'      <tr><td><span class="forum-icon"></span>&nbsp;'
            f'<a class="forum-title" href="topic-{tid}.html">{esc(title)}</a>'
            f'<div class="forum-desc">in <a href="forum-{fid}.html">{esc(fname)}</a> '
            f'· by {poster_html} · {fmt_time(ttime)} · {nposts} posts</div></td>'
            f'<td class="num">{views}</td>'
            f'<td class="lastpost">by {last_name_html}<br>'
            f'<a href="{last_href}" title="Go to last post">{fmt_time(ltime)}</a></td></tr>'
        )
    body = [
        '  <div class="crumbs"><a href="index.html">Board index</a> Active topics</div>',
        f'  <div class="cat">Active topics (latest {ACTIVE_TOPICS_LIMIT})</div>',
        '  <table class="forumlist">',
        '    <thead><tr><th>Topic</th><th class="num">Views</th>'
        '<th class="lastpost">Last post</th></tr></thead>',
        '    <tbody>',
        "\n".join(items),
        '    </tbody></table>',
    ]
    out = page_header("Active topics - FiveTech Support Forums") + "\n".join(body) + page_footer()
    with open(os.path.join(out_dir, "active-topics.html"), "w", encoding="utf-8") as f:
        f.write(out)


def render_user(conn: sqlite3.Connection, out_dir: str, uid: int,
                user_cache: dict[int, tuple],
                forum_names: dict[int, str],
                posts: list[tuple]) -> None:
    """Render user-{uid}.html (paginated) listing every post by this user, newest first.
    `posts` is a list of (post_id, topic_id, post_time, post_subject, forum_id, topic_title)
    already sorted DESC by (post_time, post_id) so we don't re-query per user."""
    info = user_cache.get(uid)
    if not info or not info[0]:
        return
    username, colour, posts_count, regdate, avatar, _sig, _location = info
    if not posts:
        return
    cur = conn.cursor()
    pages = max(1, (len(posts) + USER_POSTS_PER_PAGE - 1) // USER_POSTS_PER_PAGE)
    avatar_html = (
        f'<img class="avatar avatar-img" src="avatars/{uid}.{avatar}" alt="" loading="lazy">'
        if avatar else '<div class="avatar"></div>'
    )

    for p in range(pages):
        chunk = posts[p * USER_POSTS_PER_PAGE : (p + 1) * USER_POSTS_PER_PAGE]
        list_rows = []
        for pid, tid, ptime, subj, fid, ttitle in chunk:
            page = get_post_page(cur, tid, pid)
            href = topic_post_url(tid, pid, page)
            fname = forum_names.get(fid, "")
            list_rows.append(
                f'      <tr><td><a class="forum-title" href="{href}">{esc(subj or ttitle)}</a>'
                f'<div class="forum-desc">in <a href="forum-{fid}.html">{esc(fname)}</a> &middot; '
                f'<a href="topic-{tid}.html">{esc(ttitle)}</a></div></td>'
                f'<td class="lastpost">{fmt_time(ptime)}</td></tr>'
            )
        page_links = ""
        if pages > 1:
            page_links = " ".join(
                f'<a href="user-{uid}-page-{i+1}.html">{i+1}</a>' if i != p
                else f"<strong>{i+1}</strong>"
                for i in range(pages)
            )
        body = [
            f'  <div class="crumbs"><a href="index.html">Board index</a> '
            f'User: {esc(username)}</div>',
            '  <div class="userprofile">',
            '    <div class="userprofile-meta">',
            f'      {avatar_html}',
            f'      <div class="name" style="color:#{esc(colour or "105289")}">{esc(username)}</div>',
            f'      <div class="rank">Posts: {posts_count}</div>',
            f'      <div class="joined">Joined: {fmt_time(regdate) if regdate else "unknown"}</div>',
            '    </div>',
            '  </div>',
            f'  <div class="cat">Posts by {esc(username)} ({len(posts)} total)</div>',
            '  <table class="forumlist">',
            '    <thead><tr><th>Post</th><th class="lastpost">Posted</th></tr></thead>',
            '    <tbody>',
            "\n".join(list_rows),
            '    </tbody></table>',
            f'  <div class="pagination">Page: {page_links}</div>' if page_links else "",
        ]
        fn = f"user-{uid}.html" if p == 0 else f"user-{uid}-page-{p+1}.html"
        out = page_header(f"Posts by {username} - FiveTech Support Forums") + "\n".join(body) + page_footer()
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
    # Write fresh CSS using prosilver-style palette via CSS variables.
    css = _build_css()
    with open(os.path.join(args.out_dir, "style.css"), "w", encoding="utf-8") as f:
        f.write(css)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA query_only = 1")
    cur = conn.cursor()

    # Load user data first — index/forum pages now link usernames so we need
    # the username->uid map populated before any rendering step runs.
    print("[1/4] loading user cache...")
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
        row[0]: (row[1], row[2], row[3], row[4], avatar_map.get(row[0], ""), row[5] or "", "")
        for row in cur.execute(
            "SELECT user_id, username, user_colour, user_posts, user_regdate, "
            "COALESCE(user_sig, '') FROM phpbb_users"
        )
    }
    print(f"   {len(user_cache)} users cached")
    # Populate username -> uid lookup for legacy rows lacking poster_id.
    for uid, info in user_cache.items():
        nm = info[0]
        if nm and nm not in _name_to_uid:
            _name_to_uid[nm] = uid

    print("[2/4] index + forums + active topics...")
    render_index(conn, args.out_dir)
    render_active_topics(conn, args.out_dir)
    if args.limit_forum:
        forums = [(args.limit_forum,)]
    else:
        forums = cur.execute(
            "SELECT forum_id FROM phpbb_forums WHERE forum_type=1 ORDER BY left_id"
        ).fetchall()
    for (fid,) in forums:
        render_forum(conn, args.out_dir, fid)

    print("[3/4] topics...")
    n = 0
    t0 = time.time()
    topic_ids: list[int] = []
    for (fid,) in forums:
        q = "SELECT topic_id FROM phpbb_topics WHERE forum_id=? AND COALESCE(topic_moved_id,0)=0"
        params: tuple = (fid,)
        if args.limit_topics:
            q += " ORDER BY topic_last_post_time DESC LIMIT ?"
            params = (fid, args.limit_topics)
        topic_ids.extend(tid for (tid,) in cur.execute(q, params).fetchall())
    for tid in topic_ids:
        render_topic(conn, args.out_dir, tid, user_cache=user_cache)
        n += 1
        if n % 500 == 0:
            print(f"   {n} topics in {time.time()-t0:.1f}s")
    print(f"   {n} topics generated.")

    print("[4/4] user pages...")
    # Bulk-fetch every post grouped by author. Sorted so each user's slice is
    # already newest-first; we just slice into pages of USER_POSTS_PER_PAGE.
    # Filter posts to topics we actually generated (respect --limit-forum/--limit-topics).
    forum_names = {fid: name for fid, name in
                   cur.execute("SELECT forum_id, forum_name FROM phpbb_forums")}
    allowed_topics: set[int] | None = None
    if args.limit_forum or args.limit_topics:
        allowed_topics = set(topic_ids)
    posts_by_user: dict[int, list[tuple]] = {}
    rows = cur.execute(
        "SELECT p.poster_id, p.post_id, p.topic_id, p.post_time, p.post_subject, "
        "p.forum_id, t.topic_title "
        "FROM phpbb_posts p JOIN phpbb_topics t ON t.topic_id=p.topic_id "
        "WHERE p.poster_id > 0 AND COALESCE(t.topic_moved_id,0)=0 "
        "ORDER BY p.poster_id, p.post_time DESC, p.post_id DESC"
    )
    skipped = 0
    for poster_id, pid, tid, ptime, subj, fid, ttitle in rows:
        if allowed_topics is not None and tid not in allowed_topics:
            skipped += 1
            continue
        posts_by_user.setdefault(poster_id, []).append((pid, tid, ptime, subj, fid, ttitle))
    print(f"   {len(posts_by_user)} authors, {sum(len(v) for v in posts_by_user.values())} posts")
    u = 0
    t1 = time.time()
    for uid, plist in posts_by_user.items():
        render_user(conn, args.out_dir, uid, user_cache, forum_names, plist)
        u += 1
        if u % 200 == 0:
            print(f"   {u} users in {time.time()-t1:.1f}s")
    print(f"Done. {n} topics, {u} user pages generated.")


if __name__ == "__main__":
    main()
