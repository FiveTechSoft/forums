"""Read forum topics from GitHub Issues.

No third-party deps: uses urllib (same approach as setup-cron.py). Tests use
recorded JSON fixtures, so no network access is needed to run them.
"""
from __future__ import annotations

import json
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
