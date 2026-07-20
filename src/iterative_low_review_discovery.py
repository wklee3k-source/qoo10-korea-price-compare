"""
iterative_low_review_discovery.py

사용자가 정의한 알고리즘을 재사용 가능한 스크립트로 구현:

    1. 검색어(한글)를 일본어로 번역해서 큐텐(m.qoo10.jp 모바일)에 검색
    2. 검색결과에서 리뷰 없음 또는 3개 미만인 "상점"에 들어간다
    3. 그 상점의 실판매랭킹 베스트5를 크롤링
    4. 크롤링한 상품 중 리뷰 3개 미만인 것만 필터링
    5. 그 상품명들을 새 검색어로 다시 2번부터 반복
    6. 상점은 전체 라운드에 걸쳐 중복 제외(한 번 방문한 상점은 다시 안 감)
    7. 상품은 "색조 카테고리"(대분류 120000013 베이스메이크업/120000014
       포인트메이크업/120000016 메이크업소품 — 반드시 옵션이 생기는 카테고리)
       또는 has_options=True인 것을 전부 제외
    8. 최종 통과 상품이 목표 개수(target)에 도달할 때까지 반복

사용법:
    python iterative_low_review_discovery.py "<한글 검색어>" <target_count> <output.xlsx>

중단 후 재실행하면 output/discovery_state.json에 저장된 상태(방문한 상점,
확보한 상품)를 이어서 사용한다 — 처음부터 다시 안 함.
"""

import json
import sys
from pathlib import Path

from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_ranking_scraper import fetch_shop_ranking
from qoo10_item_detail_scraper import fetch_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
STATE_PATH = OUTPUT_DIR / "discovery_state.json"

# 색조(반드시 옵션이 생기는) 대분류 코드 — data/qoo10_category_info.csv에서 확인함
COLOR_COSMETIC_CATEGORIES = {"120000013", "120000014", "120000016"}

REVIEW_THRESHOLD = 3  # "없거나 3개 미만"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"visited_shops": [], "passed_products": [], "round": 0}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def find_low_review_shops(keyword: str, visited_shops: set) -> list[dict]:
    """검색해서 리뷰 없음/3개 미만인 상점 중 아직 안 가본 곳만 반환."""
    html = search_qoo10(keyword)
    results = parse_results(html)
    low = [r for r in results if r["review_count"] < REVIEW_THRESHOLD]
    seen_this_call = {}
    for r in low:
        if r["shop_id"] not in visited_shops:
            seen_this_call[r["shop_id"]] = r  # dedupe within this call too
    return list(seen_this_call.values())


def check_product_passes_filters(product: dict) -> tuple[bool, dict]:
    """상품이 리뷰수<3 이면서 색조카테고리도 아니고 옵션도 없으면 True."""
    try:
        detail = fetch_item_detail(product["goods_no"], save_hires_image=False)
    except Exception:  # noqa: BLE001
        return False, {}

    review_count = detail.get("review_count")
    has_options = detail.get("has_options")
    category = detail.get("category_gdlc_cd")

    enriched = {
        **product,
        "review_count": review_count,
        "has_options": has_options,
        "category_gdlc_cd": category,
    }

    if review_count is None or review_count >= REVIEW_THRESHOLD:
        return False, enriched
    if has_options:
        return False, enriched
    if category in COLOR_COSMETIC_CATEGORIES:
        return False, enriched
    return True, enriched


def run(keyword_ja: str, target: int, max_rounds: int = 10):
    state = _load_state()
    visited_shops = set(state["visited_shops"])
    passed_products = {p["goods_no"]: p for p in state["passed_products"]}

    search_keywords = [keyword_ja]
    round_no = state["round"]

    while len(passed_products) < target and round_no < max_rounds and search_keywords:
        round_no += 1
        print(f"\n===== 라운드 {round_no} (검색어 {len(search_keywords)}개) =====")
        next_round_keywords = []

        for kw in search_keywords:
            if len(passed_products) >= target:
                break
            print(f"[검색] {kw}")
            shops = find_low_review_shops(kw, visited_shops)
            print(f"  -> 신규 저리뷰 상점 {len(shops)}개")

            for shop in shops:
                if len(passed_products) >= target:
                    break
                shop_id = shop["shop_id"]
                visited_shops.add(shop_id)
                try:
                    ranking = fetch_shop_ranking(shop_id)
                except Exception:  # noqa: BLE001
                    ranking = None
                if not ranking:
                    continue

                for item in ranking:
                    if len(passed_products) >= target:
                        break
                    if item["goods_no"] in passed_products:
                        continue
                    ok, enriched = check_product_passes_filters(item)
                    if ok:
                        enriched["shop_id"] = shop_id
                        enriched["found_round"] = round_no
                        passed_products[item["goods_no"]] = enriched
                        print(f"    [통과] {item['goods_no']} review={enriched['review_count']} {item['title'][:30]}")
                    elif enriched.get("review_count") is not None and enriched["review_count"] < REVIEW_THRESHOLD:
                        # 리뷰는 3개 미만이지만 옵션/색조라서 탈락한 것도 다음 라운드 검색어 후보로는 쓴다
                        next_round_keywords.append(item["title"])

                # 매 상점마다 상태 저장 (중단돼도 이어서 진행 가능)
                state = {
                    "visited_shops": list(visited_shops),
                    "passed_products": list(passed_products.values()),
                    "round": round_no,
                }
                _save_state(state)

        search_keywords = next_round_keywords[:20]  # 다음 라운드 검색어 폭발 방지용 상한

    print(f"\n[DONE] 최종 통과 상품: {len(passed_products)}건 / 목표 {target}건 / {round_no}라운드 소요")
    return list(passed_products.values())


def export_excel(products: list[dict], out_path: str):
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment

    rows = [
        {
            "큐텐상품번호": p.get("goods_no"),
            "상점ID": p.get("shop_id"),
            "라운드": p.get("found_round"),
            "상품명": p.get("title"),
            "브랜드": p.get("brand"),
            "가격(엔)": p.get("price_jpy"),
            "리뷰수": p.get("review_count"),
            "옵션있음": p.get("has_options"),
            "카테고리코드": p.get("category_gdlc_cd"),
            "상품URL": p.get("item_url"),
        }
        for p in products
    ]
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="저리뷰상품", index=False)

    from openpyxl import load_workbook

    wb = load_workbook(out_path)
    ws = wb.active
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    widths = {"A": 14, "B": 16, "C": 8, "D": 50, "E": 16, "F": 10, "G": 8, "H": 10, "I": 14, "J": 45}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(out_path)
    print(f"[EXCEL] {out_path} 저장 완료 ({len(rows)}행)")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    keyword_ja = sys.argv[1]
    target = int(sys.argv[2])
    out_path = sys.argv[3]

    products = run(keyword_ja, target)
    export_excel(products, out_path)


if __name__ == "__main__":
    main()
