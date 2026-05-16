import os
import gh_source

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
MAP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "forum-map.json")


def test_load_forum_map_returns_entries_and_label_index():
    fmap = gh_source.load_forum_map(MAP_PATH)
    assert fmap.entries[0]["forum_id"] == 1
    assert fmap.label_to_forum_id["forum:fivewin"] == 1
    assert fmap.label_to_forum_id["forum:harbour"] == 2
