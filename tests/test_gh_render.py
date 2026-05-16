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
