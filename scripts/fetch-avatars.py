"""Download all phpBB avatar uploads via FTP. READ-ONLY.

Required env vars: HOST, FTP_USER, FTP_PASS, AVATAR_SALT
Optional:          OUT_DIR (default: ./avatars-fresh)
"""
import ftplib
import os
import re
import sys


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required env var: {name}")
    return v


HOST = _env("HOST")
USER = _env("FTP_USER")
PASS = _env("FTP_PASS")
REMOTE = "/www/forums/images/avatars/upload/"
LOCAL = os.environ.get("OUT_DIR", "avatars-fresh") + "/"
SALT = _env("AVATAR_SALT")

os.makedirs(LOCAL, exist_ok=True)

ftp = ftplib.FTP(HOST, timeout=60)
ftp.login(USER, PASS)
ftp.set_pasv(True)
ftp.cwd(REMOTE)

names = ftp.nlst()
salt_files = [n for n in names if n.startswith(SALT)]
print(f"Total entries: {len(names)} | Salt-pattern: {len(salt_files)}")

ok = skipped = failed = 0
for n in salt_files:
    base = n[len(SALT):]  # e.g. 1234.jpg
    if not re.match(r"^\d+\.[a-z]+$", base.lower()):
        skipped += 1
        continue
    out = os.path.join(LOCAL, base)
    if os.path.exists(out):
        skipped += 1
        continue
    try:
        with open(out, "wb") as f:
            ftp.retrbinary(f"RETR {n}", f.write)
        ok += 1
        if ok % 50 == 0:
            print(f"  downloaded {ok}/{len(salt_files)}")
    except Exception as e:
        print(f"  FAIL {n}: {e}")
        failed += 1
        try:
            os.remove(out)
        except OSError:
            pass

ftp.quit()
print(f"Done. ok={ok} skipped={skipped} failed={failed}")
print(f"Local count: {len(os.listdir(LOCAL))}")
