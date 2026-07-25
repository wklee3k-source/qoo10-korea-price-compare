"""
musinsa_name_corrector.py

hwahae_name_corrector.py와 동일한 인터페이스로 무신사(musinsa.com)에서
검증한다 — 두 소스의 정확도를 비교하기 위한 A/B 테스트용.

[구조] 무신사 검색결과 페이지의 초기 HTML에 React Query 캐시 형태로
상품 데이터(goodsNo/goodsName/brand/brandName/finalPrice)가 이미 박혀
있어서 렌더링 대기 없이 바로 정규식으로 뽑을 수 있다(화해와 달리
__NEXT_DATA__ 구조가 아니라 dehydratedState 형태).

사용법:
    python musinsa_name_corrector.py "<상품명만, 브랜드 없이>" [용량] [브랜드]
"""

import json
import re
import sys
import urllib.parse
from difflib import SequenceMatcher

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# goodsNo/goodsName/brand/brandName/finalPrice가 한 오브젝트 안에 이 순서로
# 나오는 걸 실측으로 확인함(react-query 캐시 JSON)
ITEM_RE = re.compile(
    r'"goodsNo":(\d+),"goodsName":"([^"]+)".*?"isSoldOut":(true|false).*?'
    r'"finalPrice":(\d+).*?"brand":"([^"]*)","brandName":"([^"]+)"'
)


def _fetch_search_page(keyword: str, wait_seconds: float = 2.0) -> str:
    url = f"https://www.musinsa.com/search/musinsa/goods?keyword={urllib.parse.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=15000, wait_until="load")
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        import time

        time.sleep(wait_seconds)
        try:
            content = page.content()
        except Exception:  # noqa: BLE001
            content = ""
        browser.close()
    return content


def _parse_products(html: str) -> list[dict]:
    results = []
    for m in ITEM_RE.finditer(html):
        goods_no, name, sold_out, price, brand_en, brand_kr = m.groups()
        results.append(
            {
                "goods_no": goods_no,
                "brand": brand_kr,
                "product_name": name,
                "price": int(price),
                "sold_out": sold_out == "true",
            }
        )
    return results


def correct_name(product_keyword_only: str, known_volume: str = "", known_brand: str = "") -> dict:
    html = _fetch_search_page(product_keyword_only)
    products = _parse_products(html)
    if not products:
        return {"guessed": product_keyword_only, "brand": None, "corrected": None, "all_candidates": []}

    top = products[0]

    if known_brand:
        brand_matches = [p for p in products if known_brand.lower() in (p["brand"] or "").lower()]
        if brand_matches:
            top = brand_matches[0]
            return {
                "guessed": product_keyword_only,
                "brand": top["brand"],
                "corrected": top["product_name"],
                "sold_out": top["sold_out"],
                "all_candidates": products,
                "matched_by": "brand",
            }
        else:
            return {
                "guessed": product_keyword_only,
                "brand": None,
                "corrected": None,
                "all_candidates": products,
                "matched_by": "brand_mismatch",
            }

    return {
        "guessed": product_keyword_only,
        "brand": top["brand"],
        "corrected": top["product_name"],
        "sold_out": top["sold_out"],
        "all_candidates": products,
        "matched_by": "top_result",
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    known_volume = sys.argv[2] if len(sys.argv) > 2 else ""
    known_brand = sys.argv[3] if len(sys.argv) > 3 else ""
    result = correct_name(sys.argv[1], known_volume=known_volume, known_brand=known_brand)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
