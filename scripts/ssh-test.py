"""SSH test: run cron-dump.sh now to verify it works. READ-ONLY ELSE — no deletes.

Required env vars: SSH_HOST, SSH_USER, SSH_PASS
"""
import os
import sys

import paramiko


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required env var: {name}")
    return v


cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(_env("SSH_HOST"), port=22, username=_env("SSH_USER"),
            password=_env("SSH_PASS"), look_for_keys=False, allow_agent=False, timeout=15)

def run(cmd):
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=120)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out: print(out.rstrip())
    if err: print("STDERR:", err.rstrip())
    print(f"[exit={rc}]")
    return rc

run("whoami; pwd; uname -a")
run("ls -la $HOME/cron-dump.sh $HOME/.my-forums-cron.cnf 2>&1")
run("crontab -l 2>&1 | head -10")
run("bash $HOME/cron-dump.sh && echo DUMP_OK")
run("ls -la $HOME/forums_daily.sql.gz")
run("gunzip -t $HOME/forums_daily.sql.gz && echo GZIP_OK")

cli.close()
