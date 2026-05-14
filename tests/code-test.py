"""Verify Select all + Collapse on live code blocks."""
from playwright.sync_api import sync_playwright

URL = "https://fivetechsoft.github.io/forums/topic-37145.html"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle")

    n = page.locator(".codebox").count()
    print(f"codebox count: {n}")
    if n == 0:
        print("NO CODEBOXES FOUND")
        browser.close(); exit(1)

    box = page.locator(".codebox").first
    pre = box.locator("pre")
    sel = box.locator("a.cb-select")
    tog = box.locator("a.cb-toggle")

    # ---- SELECT ALL ----
    pre_text_before = pre.text_content()
    sel.click()
    page.wait_for_timeout(300)
    selected = page.evaluate("window.getSelection().toString()")
    sel_text_after = sel.text_content()
    try:
        clip = page.evaluate("navigator.clipboard.readText()")
    except Exception as e:
        clip = f"ERR: {e}"
    print(f"select.click  | selected_chars={len(selected)}  link_text={sel_text_after!r}")
    print(f"              | clipboard_match={selected==clip if isinstance(clip,str) else clip}")

    # ---- COLLAPSE ----
    pre_visible_before = pre.is_visible()
    tog.click()
    page.wait_for_timeout(200)
    pre_visible_after = pre.is_visible()
    tog_text_after = tog.text_content()
    print(f"toggle.click1 | pre.visible {pre_visible_before} -> {pre_visible_after}  link={tog_text_after!r}")

    # ---- EXPAND ----
    tog.click()
    page.wait_for_timeout(200)
    pre_visible_again = pre.is_visible()
    tog_text_again = tog.text_content()
    print(f"toggle.click2 | pre.visible -> {pre_visible_again}  link={tog_text_again!r}")

    browser.close()
