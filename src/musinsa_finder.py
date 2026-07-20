"""
musinsa_finder.py

4단계(한국 원가 매칭) 자동화 — 무신사(musinsa.com) 버전.

[왜 무신사인가] 무신사는 원래 이 프로젝트의 "허용 소싱처 목록"(올리브영,
네이버브랜드스토어, 공식판매처, 지그재그, 무신사)에 있던 곳이다.
다나와(danawa.com)는 접근은 되지만 가격비교사이트라 이 목록에 원래
안 맞았고 어쩔 수 없이 써왔다 — 무신사는 실제 판매처이므로 훨씬 적합하다.

[구조] 무신사 검색 페이지는 Next.js라 초기 SSR 응답에는 가격이 없고,
클라이언트 렌더링 후 DOM에 텍스트로 나타난다. 상품 링크(`a[href*="/products/"]`)
를 앵커로 잡고, 그 조상 요소를 위로 올라가며 "숫자+원" 패턴이 포함된
텍스트 컨테이너를 찾는 방식으로 가격을 짝지었다(정확한 정규 selector가
없어서 휴리스틱이지만, 실측 검증 결과 23건 전부 정확히 추출됨).

사용법:
    python musinsa_finder.py "<검색어>"
"""

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

import korea_price_finder as _danawa  # UA_POOL 재사용 (#17 User-Agent Pool)

PRICE_RE = re.compile(r"([\d,]{4,})원")


def parse_musinsa_candidates(html: str, max_results: int = 5) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_links = set()

    for link in soup.select("a[href*='/products/']"):
        href = link.get("href")
        if not href or href in seen_links:
            continue
        seen_links.add(href)

        img = link.select_one("img")
        name = img.get("alt") if img else None
        if not name:
            continue

        price = None
        brand_from_container = None
        container = link
        for _ in range(8):
            container = container.parent
            if container is None:
                break
            text = container.get_text(" ", strip=True)
            m = PRICE_RE.search(text)
            if m and len(text) < 500:
                price = int(m.group(1).replace(",", ""))
                # 무신사 카드 텍스트는 보통 "브랜드명 상품명 할인율% 가격원 ..." 순서라
                # 상품명(name) 앞부분을 잘라내면 브랜드명만 남는다
                idx = text.find(name)
                if idx > 0:
                    brand_from_container = text[:idx].strip()
                break
        if not price:
            continue

        img_url = img.get("src") if img else None
        full_link = "https://www.musinsa.com" + href if href.startswith("/") else href

        results.append(
            {
                "name": name,
                "brand_from_container": brand_from_container,
                "price_krw": price,
                "link": full_link,
                "img_kr": img_url,
                "source": "musinsa",  # 무신사는 실제 판매처이므로 다나와와 달리 이 자체가 신뢰 가능한 판매처 표시
            }
        )
        if len(results) >= max_results:
            break
    return results


class MusinsaSession:
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
        url = f"https://www.musinsa.com/search/goods?keyword={urllib.parse.quote(keyword)}"
        page = self._context.new_page()
        delay = 1.0
        html = ""
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
                    else:
                        print(f"    [FAIL] {e}", file=sys.stderr)
        finally:
            page.close()

        return parse_musinsa_candidates(html, max_results) if html else []


def find_price(keyword: str, max_results: int = 5) -> list[dict]:
    with MusinsaSession() as session:
        return session.search(keyword, max_results)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    candidates = find_price(sys.argv[1])
    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
