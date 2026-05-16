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
