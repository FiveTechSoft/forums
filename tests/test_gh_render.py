import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generate


def test_render_github_body_converts_markdown():
    html = generate.render_github_body("Use `oWnd:Center()` now.")
    assert "<code>oWnd:Center()</code>" in html


def test_render_github_body_redacts_secrets():
    html = generate.render_github_body("token ghp_" + "a" * 36)
    assert "[REDACTED:GITHUB_PAT]" in html
    assert "ghp_aaaa" not in html


def test_render_github_body_handles_empty():
    assert generate.render_github_body("") == ""


def test_render_github_body_strips_script_tags():
    html = generate.render_github_body("hello <script>alert(1)</script> world")
    assert "<script>" not in html
    assert "alert(1)" not in html or "&lt;script&gt;" not in html
    # the surrounding text survives
    assert "hello" in html and "world" in html


def test_render_github_body_neutralizes_javascript_url():
    html = generate.render_github_body("[click](javascript:alert(1))")
    assert "javascript:alert" not in html


def test_render_github_body_fallback_without_markdown(monkeypatch):
    monkeypatch.setattr(generate, "_MD", None)
    html = generate.render_github_body("Use `oWnd:Center()` now.")
    assert html.startswith("<pre>")
    assert "oWnd:Center()" in html
    monkeypatch.setattr(generate, "_MD", None)
    html2 = generate.render_github_body("<b>bold</b>")
    assert "&lt;b&gt;" in html2


def _sample_topic():
    return {
        "source": "github",
        "number": 12,
        "forum_id": 1,
        "title": "How to center a window",
        "author": "octocat",
        "author_url": "https://github.com/octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
        "created_ts": 1715767200,
        "updated_ts": 1715851800,
        "url": "https://github.com/FiveTechSoft/forums/issues/12",
        "state": "open",
        "body_md": "I want to center my window.",
        "comments": [
            {
                "author": "contributor",
                "author_url": "https://github.com/contributor",
                "avatar_url": "https://avatars.githubusercontent.com/u/2?v=4",
                "created_ts": 1715851800,
                "body_md": "Use `oWnd:Center()`.",
            }
        ],
    }


def _mini_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE phpbb_forums (forum_id INT, forum_name TEXT);
        CREATE TABLE phpbb_topics (
            topic_id INT, topic_title TEXT, topic_poster INT,
            topic_first_poster_name TEXT, topic_first_poster_colour TEXT,
            topic_time INT, topic_last_post_id INT, topic_last_poster_id INT,
            topic_last_poster_name TEXT, topic_last_post_time INT,
            topic_views INT, topic_type INT, topic_moved_id INT, forum_id INT);
        CREATE TABLE phpbb_posts (post_id INT, topic_id INT, post_time INT);
        INSERT INTO phpbb_forums VALUES (1, 'FiveWin');
        INSERT INTO phpbb_topics VALUES
            (100,'Old phpBB topic',1,'phpbbuser','555',1715000000,
             900,1,'phpbbuser',1715000000,5,0,0,1);
        INSERT INTO phpbb_posts VALUES (900,100,1715000000);
        """
    )
    conn.commit()
    return conn


def test_render_forum_merges_github_topics(tmp_path):
    db = str(tmp_path / "mini.db")
    conn = _mini_db(db)
    try:
        gh_topics = [_sample_topic()]  # updated_ts 1715851800 > phpBB 1715000000
        generate.render_forum(conn, str(tmp_path), 1, gh_topics=gh_topics)
        content = (tmp_path / "forum-1.html").read_text(encoding="utf-8")
        assert "Old phpBB topic" in content
        assert "How to center a window" in content
        assert 'href="gh-topic-12.html"' in content
        # GitHub topic is newer, so it sorts above the phpBB one.
        assert content.index("gh-topic-12.html") < content.index("topic-100.html")
    finally:
        conn.close()


def test_render_github_topic_no_comments(tmp_path):
    topic = _sample_topic()
    topic["comments"] = []
    generate.render_github_topic(topic, "FiveWin", str(tmp_path))
    content = (tmp_path / "gh-topic-12.html").read_text(encoding="utf-8")
    assert "How to center a window" in content
    assert "Reply on GitHub" in content
    # only the issue body block, no "Re:" comment blocks
    assert "Re: How to center a window" not in content


def test_render_github_topic_writes_page(tmp_path):
    generate.render_github_topic(_sample_topic(), "FiveWin", str(tmp_path))
    page = tmp_path / "gh-topic-12.html"
    assert page.exists()
    content = page.read_text(encoding="utf-8")
    assert "How to center a window" in content
    assert "octocat" in content
    assert "<code>oWnd:Center()</code>" in content
    # Reply path for GitHub topics is a link to the issue, not Giscus.
    assert "https://github.com/FiveTechSoft/forums/issues/12" in content
    assert "giscus.app" not in content


def test_render_active_topics_includes_github(tmp_path):
    db = str(tmp_path / "active.db")
    conn = sqlite3.connect(db)
    # Schema must carry every column render_active_topics' SQL selects.
    conn.executescript(
        """
        CREATE TABLE phpbb_forums (forum_id INT, forum_name TEXT);
        CREATE TABLE phpbb_topics (
            topic_id INT, forum_id INT, topic_title TEXT,
            topic_poster INT, topic_first_poster_name TEXT,
            topic_first_poster_colour TEXT, topic_time INT, topic_views INT,
            topic_last_post_id INT, topic_last_poster_id INT,
            topic_last_poster_name TEXT, topic_last_post_time INT,
            topic_moved_id INT, topic_visibility INT);
        CREATE TABLE phpbb_posts (post_id INT, topic_id INT, post_time INT);
        INSERT INTO phpbb_forums VALUES (1,'FiveWin');
        INSERT INTO phpbb_topics VALUES
            (100,1,'Old phpBB topic',1,'phpbbuser','555',1715000000,5,
             900,1,'phpbbuser',1715000000,0,1);
        INSERT INTO phpbb_posts VALUES (900,100,1715000000);
        """
    )
    conn.commit()
    try:
        generate.render_active_topics(conn, str(tmp_path), gh_topics=[_sample_topic()])
        content = (tmp_path / "active-topics.html").read_text(encoding="utf-8")
        assert "How to center a window" in content
        assert 'href="gh-topic-12.html"' in content
        # GitHub topic (updated 1715851800) is newer than the phpBB one.
        assert content.index("gh-topic-12.html") < content.index("topic-100.html")
    finally:
        conn.close()


def test_render_index_counts_github_topics(tmp_path):
    db = str(tmp_path / "mini2.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE phpbb_forums
            (forum_id INT, forum_name TEXT, parent_id INT, left_id INT,
             forum_desc TEXT, forum_topics_approved INT, forum_posts_approved INT);
        CREATE TABLE phpbb_topics
            (topic_id INT, topic_last_post_id INT, topic_last_poster_id INT,
             topic_last_poster_name TEXT, topic_last_post_time INT, forum_id INT);
        INSERT INTO phpbb_forums VALUES (0,'Category',0,1,'',0,0);
        INSERT INTO phpbb_forums VALUES (1,'FiveWin',0,2,'desc',3,7);
        """
    )
    conn.commit()
    try:
        gh_by_forum = {1: [_sample_topic()]}  # 1 GitHub topic, 1 comment
        generate.render_index(conn, str(tmp_path), gh_by_forum=gh_by_forum)
        content = (tmp_path / "index.html").read_text(encoding="utf-8")
        # phpBB 3 topics + 1 GitHub topic = 4
        assert '<td class="num" data-label="Topics">4</td>' in content
        # the GitHub topic is the only activity, so it owns the last-activity cell
        assert 'href="gh-topic-12.html"' in content
        assert "octocat" in content
    finally:
        conn.close()
