"""
iterative_low_review_discovery.py

사용자가 정의한 알고리즘(v2, 명확화됨):

    1. (초기) 검색어로 큐텐 검색 → 리뷰 없음/3개 미만 상점 찾기
    2. 그 상점의 베스트5를 크롤링한다. 크롤링 시점에 카테고리가 색조
       (베이스메이크업/포인트메이크업/메이크업소품 — 반드시 옵션이 생기는
       계열)면 스킵, 옵션이 있으면 스킵. 통과한 상품은 원본 상품명 그대로 저장.
    3. 통과한 상품명에서 핵심단어를 추출한다(괄호/슬래시이후/수량단위/
       잡음단어 제거).
    4. 핵심단어로 재검색해서 리뷰 없음/3개 미만 상점을 또 찾는다.
    5. 그 상점들의 베스트5를 크롤링(2번부터 반복) — 상점은 전체 라운드에
       걸쳐 중복 방문 안 함.

사용법:
    python iterative_low_review_discovery.py "<초기검색어(일본어)>" <목표상품수> <output.xlsx> [최대상점수]
"""

import json
import re
import sys
from pathlib import Path

from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_ranking_scraper import fetch_shop_ranking
from qoo10_item_detail_scraper import fetch_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
STATE_PATH = OUTPUT_DIR / "discovery_state.json"

COLOR_COSMETIC_CATEGORIES = {"120000013", "120000014", "120000016"}
REVIEW_THRESHOLD = 3

STOPWORDS = ["選べる", "NEW", "セット", "公式", "限定", "特価", "お得", r"全\d+種", r"\bor\b", "×"]


def extract_core_keyword(title: str) -> str:
    t = title
    t = re.sub(r"[【\[（(][^】\])）]*[】\])）]", " ", t)
    t = re.split(r"\s*/", t)[0]
    t = re.sub(r"\d+\s*[枚mMｍＭlLｌＬgGｇＧ個点セ回本日%]+", " ", t)
    for sw in STOPWORDS:
        t = re.sub(sw, " ", t)
    t = re.sub(r"[,、]+\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def crawl_shop_best5(shop_id: str) -> list[dict]:
    """상점 베스트5를 크롤링하고, 카테고리(색조)/옵션 필터를 즉시 적용한다.
    통과한 상품만 반환(원본 title 그대로 유지)."""
    try:
        ranking = fetch_shop_ranking(shop_id)
    except Exception:  # noqa: BLE001
        return []
    if not ranking:
        return []

    passed = []
    for item in ranking:
        try:
            detail = fetch_item_detail(item["goods_no"], save_hires_image=False)
        except Exception:  # noqa: BLE001
            continue
        category = detail.get("category_gdlc_cd")
        has_options = detail.get("has_options")
        review_count = detail.get("review_count")
        if category in COLOR_COSMETIC_CATEGORIES:
            print(f"    [스킵-색조] {item['goods_no']} {item['title'][:30]}")
            continue
        if has_options:
            print(f"    [스킵-옵션] {item['goods_no']} {item['title'][:30]}")
            continue
        if review_count is None or review_count >= REVIEW_THRESHOLD:
            print(f"    [스킵-상품리뷰{review_count}] {item['goods_no']} {item['title'][:30]}")
            continue
        item["shop_id"] = shop_id
        item["category_gdlc_cd"] = category
        item["has_options"] = has_options
        item["review_count"] = review_count
        passed.append(item)
        print(f"    [저장] {item['goods_no']} review={review_count} {item['title'][:40]}")
    return passed


def find_low_review_shops(keyword: str, visited_shops: set) -> list[dict]:
    html = search_qoo10(keyword)
    results = parse_results(html)
    low = [r for r in results if r["review_count"] < REVIEW_THRESHOLD]
    seen = {}
    for r in low:
        if r["shop_id"] not in visited_shops:
            seen[r["shop_id"]] = r
    return list(seen.values())


def run(keyword_ja: str, target_products: int, max_shops: int | None = None):
    visited_shops = set()
    all_products = {}
    shop_urls = []

    pending_keywords = [keyword_ja]
    seen_keywords = set()

    while pending_keywords and len(all_products) < target_products:
        if max_shops and len(visited_shops) >= max_shops:
            print(f"\n[STOP] 최대 상점수({max_shops}) 도달")
            break

        kw = pending_keywords.pop(0)
        if kw in seen_keywords:
            continue
        seen_keywords.add(kw)

        print(f"\n[검색] {kw}")
        shops = find_low_review_shops(kw, visited_shops)
        print(f"  -> 신규 저리뷰 상점 {len(shops)}개")

        for shop in shops:
            if max_shops and len(visited_shops) >= max_shops:
                break
            if len(all_products) >= target_products:
                break
            shop_id = shop["shop_id"]
            visited_shops.add(shop_id)
            shop_urls.append(f"https://m.qoo10.jp/shop/{shop_id}")
            print(f"\n  [상점진입] {shop_id} (review={shop['review_count']})")

            passed_items = crawl_shop_best5(shop_id)
            for item in passed_items:
                if len(all_products) >= target_products:
                    break
                all_products[item["goods_no"]] = item
                core = extract_core_keyword(item["title"])
                if core:
                    pending_keywords.append(core)

    print(f"\n[DONE] 상점 {len(visited_shops)}개 방문, 상품 {len(all_products)}건 확보")
    return list(all_products.values()), shop_urls


def export_excel(products: list[dict], out_path: str):
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment

    rows = [
        {
            "큐텐상품번호": p.get("goods_no"),
            "상점ID": p.get("shop_id"),
            "상품명(원본)": p.get("title"),
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
    widths = {"A": 14, "B": 16, "C": 50, "D": 16, "E": 10, "F": 8, "G": 10, "H": 14, "I": 45}
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
    max_shops = int(sys.argv[4]) if len(sys.argv) > 4 else None

    products, shop_urls = run(keyword_ja, target, max_shops)
    export_excel(products, out_path)
    print("\n방문한 상점 URL:")
    for u in shop_urls:
        print(" ", u)


if __name__ == "__main__":
    main()