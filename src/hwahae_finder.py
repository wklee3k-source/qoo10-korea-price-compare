"""
hwahae_finder.py

4단계(한국 원가 매칭) — 화해(hwahae.co.kr) 버전 (#24).

[구조] 화해 검색결과 카드 텍스트는
    "only화해 코스알엑스 [only화해] 더 6 펩타이드... 4.64 4,372 46,000 원 35 29,900 원"
형태로, 브랜드+상품명+평점+리뷰수+정가+할인율+판매가가 한 덩어리 텍스트로
붙어있다. 정가/판매가 두 숫자 중 더 낮은 쪽(할인 적용된 실제 판매가)을
price_krw로 쓴다.

사용법:
    python hwahae_finder.py "<검색어>"
"""

import json
import re
import sys
import time
import urllib.parse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

import korea_price_finder as _danawa  # UA_POOL 재사용

PRICE_RE = re.compile(r"([\d,]{4,})\s*원")


def parse_hwahae_candidates(html: str, max_results: int = 5) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_links = set()

    for link in soup.select('a[href*="/goods/"]'):
        href = link.get("href")
        if not href or href in seen_links:
            continue
        seen_links.add(href)

        container = link
        text = None
        for _ in range(3):
            container = container.parent
            if container is None:
                break
            candidate_text = container.get_text(" ", strip=True)
            if PRICE_RE.search(candidate_text) and 20 < len(candidate_text) < 300:
                text = candidate_text
                break
        if not text:
            continue

        prices = [int(p.replace(",", "")) for p in PRICE_RE.findall(text)]
        if not prices:
            continue
        price = min(prices)  # 정가/판매가 중 더 낮은 쪽(할인 반영된 실제 판매가)

        # 첫 "가격원" 패턴이 시작되는 위치 앞부분을 상품명으로 취급
        # (단순히 첫 숫자에서 자르면 "6펩타이드"처럼 상품명 중간의 숫자에서
        # 잘못 잘리므로, 반드시 PRICE_RE 매치 위치를 기준으로 잘라야 한다)
        first_price_match = PRICE_RE.search(text)
        name_part = text[: first_price_match.start()].strip()
        # 끝에 남은 평점+리뷰수(예: "4.64 4,372")를 반복적으로 제거
        for _ in range(3):
            new_name = re.sub(r"\s+[\d][\d.,]*\s*$", "", name_part).strip()
            if new_name == name_part:
                break
            name_part = new_name
        name_part = re.sub(r"^only화해\s*", "", name_part).strip()

        full_link = "https://www.hwahae.co.kr" + href if href.startswith("/") else href
        results.append(
            {
                "name": name_part,
                "price_krw": price,
                "link": full_link,
                "source": "hwahae",
            }
        )
        if len(results) >= max_results:
            break
    return results


class HwahaeSession:
    def __init__(self, wait_seconds: float = 3.0, max_retries: int = 3):
        self.wait_seconds = wait_seconds
        self.max_retries = max_retries
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=_danawa.random_ua(), ignore_https_errors=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def search(self, keyword: str, max_results: int = 5) -> list[dict]:
        url = f"https://www.hwahae.co.kr/search?q={urllib.parse.quote(keyword)}"
        page = self._context.new_page()
        delay, html = 1.0, ""
        try:
            for attempt in range(1, self.max_retries + 1):
                try:
                    page.goto(url, timeout=15000, wait_until="load")
                    time.sleep(self.wait_seconds)
                    html = page.content()
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt < self.max_retries:
                        print(f"    [RETRY {attempt}/{self.max_retries}] {e}", file=sys.stderr)
                        time.sleep(delay)
                        delay *= 2
        finally:
            page.close()
        return parse_hwahae_candidates(html, max_results) if html else []


def find_price(keyword: str, max_results: int = 5) -> list[dict]:
    with HwahaeSession() as session:
        return session.search(keyword, max_results)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print(json.dumps(find_price(sys.argv[1]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
