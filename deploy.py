"""Build the forum site and deploy it to the GitHub Pages branch.

Run on the machine that does the daily phpBB sync, after the dump has been
imported to forums.db. Requires:
  - the FiveTechSoft/forums repo cloned (default: ./forums-repo), on 'main'
  - GITHUB_TOKEN in env (for generate.py issue fetch and for git push)

Usage:
  python deploy.py [--db forums.db] [--repo-dir forums-repo] [--out forums-out] [--no-push]
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

GH_REPO = "FiveTechSoft/forums"
KEEP = {".git", ".github"}  # never overwrite repo metadata or issue templates


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="forums.db")
    ap.add_argument("--repo-dir", default="forums-repo")
    ap.add_argument("--out", default="forums-out")
    ap.add_argument("--no-push", action="store_true",
                    help="build and stage into the repo dir but do not commit/push")
    args = ap.parse_args()

    if not os.path.isdir(os.path.join(args.repo_dir, ".git")):
        sys.exit(f"--repo-dir {args.repo_dir!r} is not a git repository")

    # Clear stale generated pages so a removed topic/forum page cannot be
    # resurrected on the next deploy. The avatars/ subdir and other assets are
    # left intact — generate.py reuses them.
    if os.path.isdir(args.out):
        for stale in glob.glob(os.path.join(args.out, "*.html")):
            os.remove(stale)

    # 1. Build the site (phpBB + GitHub Issues).
    if run([sys.executable, "generate.py", args.db, args.out,
            "--gh-repo", GH_REPO]) != 0:
        sys.exit("generate.py failed")

    # 2. Replace the repo working tree's published content with the new build,
    #    keeping .git and .github intact.
    if run(["git", "-C", args.repo_dir, "checkout", "main"]) != 0:
        sys.exit("could not checkout main in repo dir")
    for name in os.listdir(args.repo_dir):
        if name in KEEP:
            continue
        path = os.path.join(args.repo_dir, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(args.out):
        src = os.path.join(args.out, name)
        dst = os.path.join(args.repo_dir, name)
        shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)

    if args.no_push:
        print("staged build into", args.repo_dir, "(--no-push: not committing)")
        return

    # 3. Commit and push; Pages redeploys on push to main.
    run(["git", "-C", args.repo_dir, "add", "-A"])
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if run(["git", "-C", args.repo_dir, "commit", "-m",
            f"sync: rebuild forum site {stamp}"]) != 0:
        print("no changes to deploy")
        return
    if run(["git", "-C", args.repo_dir, "push", "origin", "main"]) != 0:
        sys.exit("git push failed")
    print("deployed.")


if __name__ == "__main__":
    main()
