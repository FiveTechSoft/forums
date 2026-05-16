import json
import os
import gh_source

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
MAP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "forum-map.json")


def test_load_forum_map_returns_entries_and_label_index():
    fmap = gh_source.load_forum_map(MAP_PATH)
    assert fmap.entries[0]["forum_id"] == 1
    assert fmap.label_to_forum_id["forum:fivewin"] == 1
    assert fmap.label_to_forum_id["forum:harbour"] == 2


def test_iso_to_ts_parses_utc():
    assert gh_source.iso_to_ts("2024-05-15T10:00:00Z") == 1715767200


def test_parse_issues_filters_prs_and_unlabeled():
    fmap = gh_source.load_forum_map(MAP_PATH)
    with open(os.path.join(FIXTURES, "issues.json"), encoding="utf-8") as f:
        raw = json.load(f)
    topics = gh_source.parse_issues(raw, fmap)
    assert len(topics) == 1
    t = topics[0]
    assert t["number"] == 12
    assert t["source"] == "github"
    assert t["forum_id"] == 1
    assert t["author"] == "octocat"
    assert t["created_ts"] == 1715767200
    assert t["comments"] == []
