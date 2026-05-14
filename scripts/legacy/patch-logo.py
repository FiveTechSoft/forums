"""In-place patch: add <a class='logo'>...</a> + .header-text wrapper to all topic pages."""
import glob
import os
import sys

REPO = r"C:\tmp\fivetech-forum-demo"

OLD = '<div class="header"><h1>FiveTech Support Forums</h1><div class="sub">FiveWin / Harbour / xBase community</div><button'
NEW = ('<div class="header">'
       '<a class="logo" href="index.html"><img src="site_logo.svg" alt="FiveTech Support Forums" width="200" height="60"></a>'
       '<div class="header-text"><h1>FiveTech Support Forums</h1>'
       '<div class="sub">FiveWin / Harbour / xBase community</div></div>'
       '<button')

patched = 0
skipped = 0
for fn in glob.glob(os.path.join(REPO, "topic-*.html")):
    with open(fn, "r", encoding="utf-8") as f:
        s = f.read()
    if NEW.split("<button")[0] in s:
        skipped += 1
        continue
    if OLD not in s:
        skipped += 1
        continue
    s = s.replace(OLD, NEW)
    with open(fn, "w", encoding="utf-8") as f:
        f.write(s)
    patched += 1
    if patched % 5000 == 0:
        print(f"  {patched} patched...")
print(f"Done. patched={patched} skipped={skipped}")
