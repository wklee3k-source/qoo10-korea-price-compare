"""올리브영 글로벌 브랜드 목록 페이지 구조 조사용 스크립트"""
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://global.oliveyoung.com/display/page/brand", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    html = page.content()
    print("=== HTML 길이:", len(html), "===")
    # 브랜드로 추정되는 링크나 텍스트 패턴 찾기
    links = page.query_selector_all("a")
    print(f"=== 전체 링크 수: {len(links)} ===")
    for i, link in enumerate(links[:60]):
        href = link.get_attribute("href") or ""
        text = (link.inner_text() or "").strip()
        if text and len(text) < 60:
            print(f"[{i}] href={href} text={text}")
    browser.close()
