"""
hwahae_name_corrector.py (v2)

상품명(용량/브랜드 뺀 순수 한글 추측번역)만 화해(hwahae.co.kr)에서 검색해서,
화해가 갖고 있는 정확한 "브랜드+정식 상품명"을 가져온다.

[v1과 다른 점] 이전엔 meta description 텍스트를 정규식으로 긁었는데,
실제로는 페이지에 __NEXT_DATA__라는 Next.js JSON 블록이 있고 그 안에
brand/productName/reviewCount가 전부 구조화되어 들어있다는 걸 확인했다
(예: {"brand": "달바 (d'Alba)", "productName": "판테놀... 선세럼", ...}).
이걸 직접 파싱하면 정규식보다 훨씬 안정적이고, 브랜드까지 정확히 얻는다.

[검색 전략] 브랜드명을 넣고 검색하면 오역된 브랜드명(예: "만나자") 때문에
검색 자체가 0건이 되는 경우가 실측으로 확인됐다. 그래서 이 버전은 상품명
핵심어만으로 검색하고, 브랜드는 화해가 반환한 값을 그대로 채택한다.

사용법:
    python hwahae_name_corrector.py "<상품명만, 브랜드 없이>"
"""

import json
import re
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NEXT_DATA_RE = re.compile(r'__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
VOLUME_FROM_BUYINFO_RE = re.compile(r"([\d.]+\s*(?:mL|ml|g)\b)")


def _fetch_search_page(keyword: str, wait_seconds: float = 3.0) -> str:
    url = f"https://www.hwahae.co.kr/search?q={urllib.parse.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=15000, wait_until="load")
            time.sleep(wait_seconds)
            content = page.content()
        except Exception:  # noqa: BLE001
            content = ""
        browser.close()
    return content


def _parse_products(html: str) -> list[dict]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []

    try:
        products = data["props"]["pageProps"]["products"]["products"]
    except (KeyError, TypeError):
        return []

    results = []
    for p in products:
        buy_info = p.get("buyInfo") or ""
        vol_m = VOLUME_FROM_BUYINFO_RE.search(buy_info)
        results.append(
            {
                "brand": p.get("brand"),
                "product_name": p.get("productName"),
                "review_count": p.get("reviewCount"),
                "volume": vol_m.group(1).replace(" ", "") if vol_m else "",
            }
        )
    return results


def correct_name(product_keyword_only: str) -> dict:
    """브랜드 없이 상품명만으로 검색해서 화해의 1번째 결과(브랜드+상품명+용량)를 가져온다."""
    html = _fetch_search_page(product_keyword_only)
    products = _parse_products(html)
    if not products:
        return {"guessed": product_keyword_only, "brand": None, "corrected": None, "volume": "", "all_candidates": []}

    top = products[0]
    return {
        "guessed": product_keyword_only,
        "brand": top["brand"],
        "corrected": top["product_name"],
        "volume": top["volume"],
        "all_candidates": products,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    result = correct_name(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
