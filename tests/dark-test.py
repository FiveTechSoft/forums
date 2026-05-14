"""Verify dark mode on the live site using Playwright."""
from playwright.sync_api import sync_playwright

URL = "https://fivetechsoft.github.io/forums/topic-37145.html"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded")

    # 1) Default theme
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    fg = page.evaluate("getComputedStyle(document.body).color")
    print(f"[default]    data-theme={theme!r}  bg={bg}  fg={fg}")

    # 2) hljs sheet states
    hljs_dark = page.evaluate("(()=>{var e=document.getElementById('hljs-theme-dark');return e?{href:e.href,disabled:e.disabled}:null})()")
    hljs_light = page.evaluate("(()=>{var e=document.getElementById('hljs-theme-light');return e?{href:e.href,disabled:e.disabled}:null})()")
    print(f"[hljs-dark]  {hljs_dark}")
    print(f"[hljs-light] {hljs_light}")

    # 3) Click toggle
    page.click("#theme-toggle")
    page.wait_for_timeout(200)
    theme2 = page.evaluate("document.documentElement.getAttribute('data-theme')")
    bg2 = page.evaluate("getComputedStyle(document.body).backgroundColor")
    stored = page.evaluate("localStorage.getItem('forum-theme')")
    print(f"[after click] data-theme={theme2!r}  bg={bg2}  localStorage={stored!r}")

    # 4) Reload, verify persistence
    page.reload(wait_until="domcontentloaded")
    theme3 = page.evaluate("document.documentElement.getAttribute('data-theme')")
    bg3 = page.evaluate("getComputedStyle(document.body).backgroundColor")
    print(f"[after reload] data-theme={theme3!r}  bg={bg3}")

    # 5) Screenshot dark vs light
    page.evaluate("localStorage.setItem('forum-theme','dark'); document.documentElement.setAttribute('data-theme','dark')")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path="c:/tmp/screenshot-dark.png", full_page=False)
    page.evaluate("localStorage.setItem('forum-theme','light'); document.documentElement.setAttribute('data-theme','light')")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path="c:/tmp/screenshot-light.png", full_page=False)
    print("Screenshots: c:/tmp/screenshot-dark.png  c:/tmp/screenshot-light.png")

    browser.close()
