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
VOLUME_FROM_BUYINFO_RE = re.compile(r"([\d.]+\s*(?:mL|ml|g|L)\b)")


def _normalize_volume_ml(vol_text: str) -> float | None:
    """'1L', '1000ml', '110ml' 등을 전부 ml 기준 숫자로 통일해서 비교 가능하게 만든다."""
    if not vol_text:
        return None
    m = re.search(r"([\d.]+)\s*(mL|ml|g|L)", vol_text)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2).lower()
    return num * 1000 if unit == "l" else num


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
                "obsolete": p.get("obsolete"),  # 단종여부
                "sale": p.get("sale"),  # 판매중여부
            }
        )
    return results


def correct_name(product_keyword_only: str, _retry: bool = True, known_volume: str = "", known_brand: str = "") -> dict:
    """브랜드 없이 상품명만으로 검색해서 화해의 1번째 결과(브랜드+상품명+용량)를 가져온다.

    [방어로직 1] 첫 결과가 검색어와 단어를 하나도 안 겹치면(예: "토너패드"를
    검색했는데 "베일리"가 나오는 경우) 페이지 로딩 타이밍 문제로 추천위젯을
    잘못 읽었을 가능성이 높다고 보고 한 번 더 재시도한다.

    [방어로직 2 — 용량매칭] 큐텐 원본에서 이미 알고 있는 용량(known_volume,
    예: "1L")이 있으면, 화해 후보들 중 그 용량과 일치하는 것을 우선
    채택한다.

    [방어로직 3 — 브랜드매칭] 큐텐 원본 브랜드의 정확한 한글명을 이미 알고
    있으면(known_brand, 예: "베르가모"), 화해 후보들 중 브랜드가 일치하는
    것을 우선 채택한다. 실측 사례: "Verish 실리콘 데미누브라"를 검색했는데
    화해가 "프라나롬 씨큐라롬 젤"(완전히 다른 브랜드)을 1등으로 줬다 —
    검색어에 브랜드가 분명히 있었는데도 그걸 검증하는 로직이 없어서
    그대로 통과됐던 문제. 브랜드 일치 여부를 확인하면 이런 명백한 오탐을
    걸러낼 수 있다."""
    html = _fetch_search_page(product_keyword_only)
    products = _parse_products(html)
    if not products:
        return {"guessed": product_keyword_only, "brand": None, "corrected": None, "volume": "", "all_candidates": []}

    top = products[0]

    # 브랜드매칭: known_brand가 있으면 그것과 일치하는 후보를 최우선으로 채택
    if known_brand:
        brand_matches = [p for p in products if known_brand.lower() in (p["brand"] or "").lower()]
        if brand_matches:
            # 브랜드가 일치하는 후보들 중에서는 용량도 맞으면 더 우선
            known_ml = _normalize_volume_ml(known_volume) if known_volume else None
            if known_ml is not None:
                vol_and_brand = [p for p in brand_matches if _normalize_volume_ml(p["volume"]) == known_ml]
                if vol_and_brand:
                    brand_matches = vol_and_brand
            top = brand_matches[0]
            return {
                "guessed": product_keyword_only,
                "brand": top["brand"],
                "corrected": top["product_name"],
                "volume": top["volume"],
                "obsolete": top.get("obsolete"),
                "sale": top.get("sale"),
                "all_candidates": products,
                "matched_by": "brand",
            }
        else:
            # 브랜드가 일치하는 후보가 아예 없으면 정직하게 실패로 처리한다
            # (엉뚱한 브랜드를 억지로 정답으로 채택하지 않는다)
            print(f"    [브랜드불일치] '{product_keyword_only}' — known_brand='{known_brand}'와 일치하는 후보 없음, 매칭실패 처리", file=sys.stderr)
            return {
                "guessed": product_keyword_only,
                "brand": None,
                "corrected": None,
                "volume": "",
                "obsolete": None,
                "sale": None,
                "all_candidates": products,
                "matched_by": "brand_mismatch",
            }

    # 용량매칭: known_volume이 있으면 그것과 일치하는 후보를 최우선으로 채택
    known_ml = _normalize_volume_ml(known_volume) if known_volume else None
    if known_ml is not None:
        volume_matches = [p for p in products if _normalize_volume_ml(p["volume"]) == known_ml]
        if volume_matches:
            top = volume_matches[0]
            return {
                "guessed": product_keyword_only,
                "brand": top["brand"],
                "corrected": top["product_name"],
                "volume": top["volume"],
                "obsolete": top.get("obsolete"),
                "sale": top.get("sale"),
                "all_candidates": products,
                "matched_by": "volume",
            }

    query_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", product_keyword_only.lower()))
    result_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", (top["product_name"] or "").lower()))
    no_overlap = bool(query_tokens) and not (query_tokens & result_tokens)

    if no_overlap and _retry:
        print(f"    [의심] '{product_keyword_only}' 검색결과 '{top['product_name']}'가 단어가 하나도 안 겹침 — 재시도", file=sys.stderr)
        return correct_name(product_keyword_only, _retry=False, known_volume=known_volume, known_brand=known_brand)

    return {
        "guessed": product_keyword_only,
        "brand": top["brand"],
        "corrected": top["product_name"],
        "volume": top["volume"],
        "obsolete": top.get("obsolete"),
        "sale": top.get("sale"),
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
