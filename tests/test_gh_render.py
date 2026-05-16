import os
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
