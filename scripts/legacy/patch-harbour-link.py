"""Patch all HTML files in repo root to:
   1. Make 'Harbour' in header subtitle a link to github.com/harbour/core
   2. If a previous (wrong) URL harbour.github.io was already inserted, fix it.
"""
import glob
import os

REPO = r"C:\tmp\fivetech-forum-demo"
GLOB = "*.html"
NEW_URL = "https://github.com/harbour/core"

REPLACEMENTS = [
    # plain text -> linked
    ("FiveWin / Harbour / xBase community",
     f'FiveWin / <a href="{NEW_URL}" target="_blank" rel="noopener">Harbour</a> / xBase community'),
    # stale URL -> new URL (if patched earlier)
    ("https://harbour.github.io/", NEW_URL + "/"),
    # cleanup if double-slash crept in
    (NEW_URL + "/", NEW_URL),
]

patched = skipped = 0
for fn in glob.glob(os.path.join(REPO, GLOB)):
    with open(fn, "rb") as f:
        b = f.read()
    s = b.decode("utf-8", errors="replace")
    orig = s
    for old, new in REPLACEMENTS:
        s = s.replace(old, new)
    if s == orig:
        skipped += 1
        continue
    with open(fn, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    patched += 1
    if patched % 10000 == 0:
        print(f"  {patched} patched...")

print(f"Done. patched={patched} skipped={skipped}")
