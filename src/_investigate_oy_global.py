"""올리브영 글로벌 브랜드 목록 페이지 구조 조사용 스크립트"""
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://global.oliveyoung.com/display/page/brand", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    # 무한스크롤/지연로딩 대비: 아래로 여러 번 스크롤
    for _ in range(5):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1000)
    html = page.content()
    print("=== HTML 길이:", len(html), "===")
    links = page.query_selector_all("a")
    print(f"=== 전체 링크 수: {len(links)} ===")
    brand_links = []
    for link in links:
        href = link.get_attribute("href") or ""
        text = (link.inner_text() or "").strip()
        if "/brands/" in href or "/brand/" in href.lower():
            brand_links.append((href, text))
    print(f"=== 브랜드패턴 링크 수: {len(brand_links)} ===")
    for href, text in brand_links[:80]:
        print(f"{href} | {text}")
    browser.close()

