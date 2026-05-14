"""Set up daily mysqldump cron via FTP + cPanel UAPI. ADDS ONLY, NEVER DELETES.

Required env vars:
  FTP_USER   e.g. fivetec1@fivetechsupport.com
  CP_USER    e.g. fivetec1
  CP_PASS    cPanel password (also used for FTP login)
  HOST       e.g. fivetechsupport.com
  DB_CREDS   path to db-creds.json (default: ./db-creds.json)
"""
import ftplib
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import ssl
import http.cookiejar


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required env var: {name}")
    return v


FTP_USER = _env("FTP_USER")
CP_USER = _env("CP_USER")
CP_PASS = _env("CP_PASS")
HOST = _env("HOST")

with open(os.environ.get("DB_CREDS", "db-creds.json")) as f:
    db = json.load(f)

dbhost = db["host"] or "localhost"
dbport = db["port"] or "3306"

# MySQL defaults file content (avoids password on command line).
# Note: phpBB's password may contain shell-special chars — defaults-file is safer.
mycnf = f"""[mysqldump]
host={dbhost}
port={dbport}
user={db["user"]}
password="{db["pass"]}"
"""

# Cron script: dumps to fixed file (overwrites daily, no accumulation).
cron_sh = """#!/bin/bash
# Daily phpBB dump for FiveTechSoft/forums GitHub mirror.
# Auto-managed by setup-cron.py — safe to delete if no longer needed.
set -eu
CNF="$HOME/.my-forums-cron.cnf"
OUT="$HOME/forums_daily.sql.gz"
TMP="$HOME/.forums_daily.sql.gz.tmp"
""" + f"""DBNAME='{db["name"]}'
""" + r"""mysqldump --defaults-extra-file="$CNF" --single-transaction --quick --skip-lock-tables \
  "$DBNAME" 2>/dev/null | gzip -9 > "$TMP"
mv "$TMP" "$OUT"
"""

print("[1/5] FTP upload .my-forums-cron.cnf and cron-dump.sh")
ftp = ftplib.FTP(HOST, timeout=60)
ftp.login(FTP_USER, CP_PASS)
ftp.set_pasv(True)

# Confirm we're at home dir
print("       cwd =", ftp.pwd())

ftp.storbinary("STOR .my-forums-cron.cnf", io.BytesIO(mycnf.encode()))
print("       wrote .my-forums-cron.cnf")

ftp.storbinary("STOR cron-dump.sh", io.BytesIO(cron_sh.encode()))
print("       wrote cron-dump.sh")

# Permissions: cnf must be 600 (passwords), sh 700.
print("[2/5] CHMOD via SITE CHMOD")
ftp.voidcmd("SITE CHMOD 600 .my-forums-cron.cnf")
ftp.voidcmd("SITE CHMOD 700 cron-dump.sh")
print("       chmod ok")
ftp.quit()

# ---- cPanel login + UAPI ----
print("[3/5] cPanel session login")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPCookieProcessor(cj),
)
data = urllib.parse.urlencode({"user": CP_USER, "pass": CP_PASS}).encode()
req = urllib.request.Request(f"https://{HOST}:2083/login/?login_only=1", data=data)
with opener.open(req, timeout=20) as r:
    body = json.loads(r.read())
sec = body.get("security_token", "")
print("       got security_token:", sec[:15] + "..." if sec else "FAILED")
if not sec:
    sys.exit("login failed")

# ---- list existing cron lines (READ-ONLY check) ----
print("[4/5] Current cron list (read-only)")
url = f"https://{HOST}:2083{sec}/execute/Cron/list_lines"
with opener.open(url, timeout=20) as r:
    listing = json.loads(r.read())
existing = listing.get("data") or []
print(f"       existing entries: {len(existing)}")
for e in existing:
    cmd = (e.get("command") or "")[:60]
    print(f"         min={e.get('minute')} hr={e.get('hour')} cmd={cmd}")

# Skip if our cron already added (idempotent)
already = any("forums_daily.sql.gz" in (e.get("command") or "") or
              "cron-dump.sh" in (e.get("command") or "")
              for e in existing)
if already:
    print("       cron already present — skipping add")
else:
    print("[5/5] Adding cron line via legacy API2")
    params = {
        "cpanel_jsonapi_user": CP_USER,
        "cpanel_jsonapi_apiversion": "2",
        "cpanel_jsonapi_module": "Cron",
        "cpanel_jsonapi_func": "add_line",
        "command": "$HOME/cron-dump.sh > $HOME/cron-dump.log 2>&1",
        "minute": "0",
        "hour": "4",
        "day": "*",
        "month": "*",
        "weekday": "*",
    }
    url = f"https://{HOST}:2083{sec}/json-api/cpanel?" + urllib.parse.urlencode(params)
    with opener.open(url, timeout=20) as r:
        result = json.loads(r.read())
    print("       result:", json.dumps(result, indent=2)[:600])

# Verify
print()
print("[verify] Re-listing cron after change:")
url = f"https://{HOST}:2083{sec}/execute/Cron/list_lines"
with opener.open(url, timeout=20) as r:
    listing = json.loads(r.read())
for e in listing.get("data") or []:
    cmd = (e.get("command") or "")[:80]
    print(f"   min={e.get('minute')} hr={e.get('hour')} cmd={cmd}")

print()
print("DONE.")
