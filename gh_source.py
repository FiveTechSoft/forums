"""Read forum topics from GitHub Issues.

No third-party deps: uses urllib (same approach as setup-cron.py). Tests use
recorded JSON fixtures, so no network access is needed to run them.
"""
from __future__ import annotations

import calendar
import json
import time as _time
import urllib.request
from dataclasses import dataclass


@dataclass
class ForumMap:
    entries: list[dict]
    label_to_forum_id: dict[str, int]


def load_forum_map(path: str) -> ForumMap:
    """Load forum-map.json into a ForumMap (entry list + label lookup)."""
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    label_to_forum_id = {e["label"]: e["forum_id"] for e in entries}
    return ForumMap(entries=entries, label_to_forum_id=label_to_forum_id)


API_ROOT = "https://api.github.com"
_UA = "fivetech-forum-sync"


def iso_to_ts(s: str) -> int:
    """Convert a GitHub ISO8601 UTC timestamp (e.g. 2024-05-15T10:00:00Z) to int unix seconds."""
    if not s:
        return 0
    parsed = _time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    return calendar.timegm(parsed)


def _api_get(url: str, token: str) -> tuple[list[dict], str | None]:
    """GET a GitHub API URL. Returns (parsed JSON list, next-page URL or None)."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", _UA)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        link = resp.headers.get("Link", "")
    next_url = None
    for part in link.split(","):
        if 'rel="next"' in part:
            next_url = part[part.find("<") + 1 : part.find(">")]
    return data, next_url


def fetch_repo_issues(repo: str, token: str) -> list[dict]:
    """Fetch every issue (all states, all pages) for repo 'owner/name'."""
    url = f"{API_ROOT}/repos/{repo}/issues?state=all&per_page=100"
    out: list[dict] = []
    while url:
        data, url = _api_get(url, token)
        out.extend(data)
    return out


def parse_issues(raw_issues: list[dict], fmap: ForumMap) -> list[dict]:
    """Convert raw issue JSON into normalized topic records.

    Skips pull requests and issues without a known forum label. Comments are
    left empty here; Task 3 fills them in.
    """
    topics: list[dict] = []
    for issue in raw_issues:
        if "pull_request" in issue:
            continue
        forum_id = None
        for label in issue.get("labels", []):
            forum_id = fmap.label_to_forum_id.get(label["name"])
            if forum_id is not None:
                break
        if forum_id is None:
            continue
        user = issue.get("user") or {}
        topics.append({
            "source": "github",
            "number": issue["number"],
            "forum_id": forum_id,
            "title": issue.get("title", ""),
            "author": user.get("login", "unknown"),
            "author_url": user.get("html_url", ""),
            "avatar_url": user.get("avatar_url", ""),
            "created_ts": iso_to_ts(issue.get("created_at", "")),
            "updated_ts": iso_to_ts(issue.get("updated_at", "")),
            "url": issue.get("html_url", ""),
            "state": issue.get("state", "open"),
            "body_md": issue.get("body") or "",
            "comments": [],
        })
    return topics


def parse_comments(raw_comments: list[dict]) -> list[dict]:
    """Convert raw issue-comment JSON into normalized comment records."""
    out: list[dict] = []
    for c in raw_comments:
        user = c.get("user") or {}
        out.append({
            "author": user.get("login", "unknown"),
            "author_url": user.get("html_url", ""),
            "avatar_url": user.get("avatar_url", ""),
            "created_ts": iso_to_ts(c.get("created_at", "")),
            "body_md": c.get("body") or "",
        })
    return out


def fetch_issue_comments(repo: str, number: int, token: str) -> list[dict]:
    """Fetch all comments for one issue."""
    url = f"{API_ROOT}/repos/{repo}/issues/{number}/comments?per_page=100"
    out: list[dict] = []
    while url:
        data, url = _api_get(url, token)
        out.extend(data)
    return out


def build_topics(repo: str, token: str, fmap: ForumMap) -> list[dict]:
    """Full pipeline: fetch issues + comments, return normalized topic records.

    This is the only function that hits the network end to end; unit tests
    exercise parse_issues / parse_comments directly with fixtures instead.
    """
    raw_issues = fetch_repo_issues(repo, token)
    topics = parse_issues(raw_issues, fmap)
    for t in topics:
        raw_comments = fetch_issue_comments(repo, t["number"], token)
        t["comments"] = parse_comments(raw_comments)
    return topics
