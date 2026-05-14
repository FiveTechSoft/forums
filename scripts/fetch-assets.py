"""Fetch smileys, icons, ranks dirs + prosilver/dark templates. READ-ONLY.

Required env vars: HOST, FTP_USER, FTP_PASS
Optional:          OUT_DIR (default: ./forum-assets)
"""
import ftplib
import os
import sys


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required env var: {name}")
    return v


HOST = _env("HOST")
USER = _env("FTP_USER")
PASS = _env("FTP_PASS")
OUT = os.environ.get("OUT_DIR", "forum-assets")

DIRS = [
    ("/www/forums/images/smilies/", f"{OUT}/smilies/", True),
    ("/www/forums/images/icons/", f"{OUT}/icons/", False),
    ("/www/forums/images/ranks/", f"{OUT}/ranks/", False),
    ("/www/forums/styles/prosilver/template/", f"{OUT}/templates/prosilver/", False),
    ("/www/forums/styles/dark/template/", f"{OUT}/templates/dark/", False),
    ("/www/forums/styles/prosilver/theme/", f"{OUT}/theme/prosilver/", True),
    ("/www/forums/styles/dark/theme/", f"{OUT}/theme/dark/", True),
]

ftp = ftplib.FTP(HOST, timeout=60)
ftp.login(USER, PASS)
ftp.set_pasv(True)


def fetch_dir(remote: str, local: str, recurse: bool) -> int:
    os.makedirs(local, exist_ok=True)
    try:
        ftp.cwd(remote)
    except ftplib.error_perm as e:
        print(f"  cannot cwd {remote}: {e}")
        return 0
    names = ftp.nlst()
    count = 0
    for n in names:
        if n in (".", ".."):
            continue
        rpath = remote + n
        lpath = os.path.join(local, n)
        # try as file first
        try:
            with open(lpath, "wb") as f:
                ftp.retrbinary(f"RETR {n}", f.write)
            count += 1
        except ftplib.error_perm:
            # likely a directory
            os.remove(lpath) if os.path.exists(lpath) and os.path.getsize(lpath) == 0 else None
            if recurse:
                count += fetch_dir(rpath + "/", lpath, recurse)
                ftp.cwd(remote)  # reset cwd after recursion
    return count


for r, l, rec in DIRS:
    n = fetch_dir(r, l, rec)
    print(f"{r} -> {l}: {n} files")

ftp.quit()
