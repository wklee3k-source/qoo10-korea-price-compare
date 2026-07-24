"""올리브영 글로벌 개별 브랜드페이지에 한글명이 숨어있는지 확인"""
import re

from playwright.sync_api import sync_playwright

urls = [
    "https://global.oliveyoung.com/global/brands/dalba",
    "https://global.oliveyoung.com/kr/brands/skin1004",
    "https://global.oliveyoung.com/global/brands/abib",
]

korean_re = re.compile(r"[가-힣]{2,}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    for url in urls:
        print(f"=== {url} ===")
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            html = page.content()
            korean_matches = korean_re.findall(html)
            print(f"  한글텍스트 발견: {len(korean_matches)}개")
            print(f"  샘플: {list(set(korean_matches))[:20]}")
            # meta 태그, lang 속성, hreflang 대체링크 확인
            hreflang_links = page.query_selector_all("link[hreflang]")
            for link in hreflang_links:
                print(f"  hreflang: {link.get_attribute('hreflang')} -> {link.get_attribute('href')}")
        except Exception as e:  # noqa: BLE001
            print(f"  오류: {type(e).__name__}: {e}")
    browser.close()
