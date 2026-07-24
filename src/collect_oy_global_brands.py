"""올리브영 글로벌 브랜드 전체목록(약 2120개)을 수집해서 저장한다."""
import json

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://global.oliveyoung.com/display/page/brand", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for _ in range(8):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(800)
    links = page.query_selector_all("a")
    brands = {}
    for link in links:
        href = link.get_attribute("href") or ""
        text = (link.inner_text() or "").strip()
        if ("/brands/" in href) and text and len(text) < 60:
            slug = href.rstrip("/").split("/")[-1]
            brands[slug] = text
    print(f"수집된 브랜드: {len(brands)}개")
    json.dump(brands, open("../data/oliveyoung_global_brands.json", "w"), ensure_ascii=False, indent=2)
    browser.close()
