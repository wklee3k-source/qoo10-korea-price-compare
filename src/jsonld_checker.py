"""
jsonld_checker.py

권고사항 #11: JSON-LD/schema.org 메타데이터 기반 공식몰·재고·가격 확인.

[배경] 상품 페이지에 `<script type="application/ld+json">`로 schema.org
Product 구조화 데이터가 있으면, 그 안의 `offers.availability`
(InStock/OutOfStock)와 `offers.price`, `brand.name`이 화면 텍스트를
직접 읽는 것보다 훨씬 신뢰도 높다(사이트 마크업이 바뀌어도 잘 안 깨짐).

[실측 확인] cafe24 기반 사이트 중 일부는 있고(예: banila.com — 정확한
InStock/price 확인됨) 일부는 없다(예: celimax.co.kr). 그래서 이건
"있으면 우선 사용, 없으면 기존 방식(stock_checker.py의 화면 텍스트
휴리스틱)으로 자동 대체"하는 보강 계층으로 설계했다 — 완전 대체가 아님.

사용법:
    python jsonld_checker.py "<상품 URL>"
"""

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


def _normalize_availability(raw: str | None) -> bool | None:
    if not raw:
        return None
    raw = raw.lower()
    if "instock" in raw:
        return True
    if "outofstock" in raw or "soldout" in raw:
        return False
    return None


def parse_jsonld_product(html: str) -> dict | None:
    """페이지 HTML에서 schema.org Product JSON-LD를 찾아 가격/재고/브랜드를 뽑는다.
    여러 개의 script 태그가 있을 수 있고, 배열로 감싸져 있을 수도 있어서
    유연하게 파싱한다."""
    for m in JSONLD_RE.finditer(html):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:  # noqa: BLE001
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "Product":
                continue

            offers = item.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            elif not isinstance(offers, dict):
                offers = {}

            brand = item.get("brand")
            brand_name = brand.get("name") if isinstance(brand, dict) else brand

            return {
                "price_krw": offers.get("price"),
                "in_stock": _normalize_availability(offers.get("availability")),
                "brand_name": brand_name,
                "product_name": item.get("name"),
                "found": True,
            }
    return None


def check_url(url: str, wait_seconds: float = 2.0) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=15000, wait_until="load")
            time.sleep(wait_seconds)
            html = page.content()
        except Exception as e:  # noqa: BLE001
            browser.close()
            return {"found": False, "error": str(e)}
        browser.close()

    result = parse_jsonld_product(html)
    return result or {"found": False}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    result = check_url(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
