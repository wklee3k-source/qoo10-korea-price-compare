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


def _fetch_search_page(keyword: str, wait_seconds: float = 2.0) -> str:
    url = f"https://www.hwahae.co.kr/search?q={urllib.parse.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=15000, wait_until="load")
            # 네트워크 요청이 다 끝날 때까지 기다린다(고정 sleep보다 안정적) —
            # 실측으로 확인된 문제: 페이지가 완전히 로딩되기 전에 __NEXT_DATA__를
            # 읽으면 아직 검색결과가 안 채워진 "추천상품 위젯"(예: 메이유어
            # 베일리)을 잘못 파싱하는 경우가 있었다.
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(wait_seconds)  # networkidle 이후에도 약간의 여유를 둔다
        try:
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


def correct_name(product_keyword_only: str, _retry: bool = True) -> dict:
    """브랜드 없이 상품명만으로 검색해서 화해의 1번째 결과(브랜드+상품명+용량)를 가져온다.

    [방어로직] 첫 결과가 검색어와 단어를 하나도 안 겹치면(예: "토너패드"를
    검색했는데 "베일리"가 나오는 경우) 페이지 로딩 타이밍 문제로 추천위젯을
    잘못 읽었을 가능성이 높다고 보고 한 번 더 재시도한다."""
    html = _fetch_search_page(product_keyword_only)
    products = _parse_products(html)
    if not products:
        return {"guessed": product_keyword_only, "brand": None, "corrected": None, "volume": "", "all_candidates": []}

    top = products[0]

    query_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", product_keyword_only.lower()))
    result_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", (top["product_name"] or "").lower()))
    no_overlap = bool(query_tokens) and not (query_tokens & result_tokens)

    if no_overlap and _retry:
        print(f"    [의심] '{product_keyword_only}' 검색결과 '{top['product_name']}'가 단어가 하나도 안 겹침 — 재시도", file=sys.stderr)
        return correct_name(product_keyword_only, _retry=False)

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
