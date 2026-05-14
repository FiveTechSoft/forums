"""Check if daily forums_daily.sql.gz dump cron is running.

Required env vars: HOST, FTP_USER, FTP_PASS
"""
import ftplib
import os
import sys
from datetime import datetime, timezone


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required env var: {name}")
    return v


HOST = _env("HOST")
FTP_USER = _env("FTP_USER")
CP_PASS = _env("FTP_PASS")

ftp = ftplib.FTP(HOST, timeout=60)
ftp.login(FTP_USER, CP_PASS)
ftp.set_pasv(True)
print("cwd =", ftp.pwd())

targets = ["forums_daily.sql.gz", "cron-dump.log", "cron-dump.sh", ".my-forums-cron.cnf"]

# MLSD = machine-readable list (gives modify timestamp)
print("\n--- MLSD HOME ---")
files = {}
try:
    for name, facts in ftp.mlsd("."):
        if name in targets:
            files[name] = facts
except Exception as e:
    print("MLSD failed:", e)
    # Fallback: MDTM per file
    for t in targets:
        try:
            resp = ftp.voidcmd(f"MDTM {t}")
            files[t] = {"modify": resp.split()[-1]}
        except Exception as ex:
            print(f"  {t}: MISSING ({ex})")

now = datetime.now(timezone.utc)
for t in targets:
    if t in files:
        f = files[t]
        mod = f.get("modify", "?")
        size = f.get("size", "?")
        try:
            dt = datetime.strptime(mod, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            age_h = (now - dt).total_seconds() / 3600
            print(f"  {t:30s} size={size:>12} mtime={dt.isoformat()} age={age_h:.1f}h")
        except Exception:
            print(f"  {t:30s} size={size:>12} mtime={mod}")
    else:
        print(f"  {t:30s} MISSING")

# Pull cron-dump.log content (small file)
print("\n--- cron-dump.log content ---")
buf = []
try:
    ftp.retrbinary("RETR cron-dump.log", buf.append)
    log = b"".join(buf).decode(errors="replace")
    print(log if log.strip() else "(empty)")
except Exception as e:
    print("could not fetch:", e)

ftp.quit()
