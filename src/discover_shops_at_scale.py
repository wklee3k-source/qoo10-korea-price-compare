"""
discover_shops_at_scale.py

카테고리 단위 검색으로 저리뷰 상점을 대량 발굴한다(1단계 확장판).
각 카테고리 키워드로 검색 → 최저리뷰 상점 선정 → 중복 제거 → 상점 목록 확보.
그 다음 qoo10_ranking_scraper.py로 각 상점의 판매랭킹 TOP5를 긁어서
목표 상품 수(--target)에 도달할 때까지 상점을 계속 추가한다.

사용법:
    python discover_shops_at_scale.py <category_keywords.txt> <target_count>
"""

import json
import sys
from pathlib import Path

from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_ranking_scraper import fetch_shop_ranking

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def load_existing_products() -> tuple[set, list]:
    """이미 처리된 상점(shops200/*.json)과 그 상품들을 불러와 이어서 진행할 수 있게 한다."""
    shops_dir = OUTPUT_DIR / "shops200"
    shops_dir.mkdir(exist_ok=True, parents=True)
    seen = set()
    products = []
    for p in shops_dir.glob("*.json"):
        shop_id = p.stem
        seen.add(shop_id)
        items = json.loads(p.read_text(encoding="utf-8"))
        products.extend(items)
    return seen, products


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    keywords = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    target = int(sys.argv[2])

    OUTPUT_DIR.mkdir(exist_ok=True)
    shops_dir = OUTPUT_DIR / "shops200"
    shops_dir.mkdir(exist_ok=True)

    seen_shops, all_products = load_existing_products()
    print(f"[RESUME] 이미 처리된 상점 {len(seen_shops)}개, 상품 {len(all_products)}건부터 이어서 진행")
    summary_path = OUTPUT_DIR / "discovery200_summary.json"

    for kw in keywords:
        kw = kw.strip()
        if not kw or len(all_products) >= target:
            continue

        print(f"[STEP] 카테고리 검색: {kw}")
        html = search_qoo10(kw)
        sellers = parse_results(html)
        if not sellers:
            continue

        for seller in sellers[:5]:
            shop_id = seller["shop_id"]
            if shop_id in seen_shops or len(all_products) >= target:
                continue
            seen_shops.add(shop_id)

            print(f"  [SHOP] {shop_id} ({seller['shop_name']}) review={seller['review_count']}")
            ranking = fetch_shop_ranking(shop_id)
            if not ranking:
                continue

            (shops_dir / f"{shop_id}.json").write_text(
                json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for item in ranking:
                item["shop_id"] = shop_id
                item["shop_name"] = seller["shop_name"]
                item["shop_review_count"] = seller["review_count"]
                item["source_keyword"] = kw
                all_products.append(item)

            # 매 상점마다 즉시 저장 (타임아웃/중단에도 진행상황 보존)
            summary_path.write_text(json.dumps(all_products, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    -> {len(ranking)}건 추가 (누적 {len(all_products)}건)")

    summary_path.write_text(json.dumps(all_products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[DONE] 상점 {len(seen_shops)}개, 상품 {len(all_products)}건 -> {summary_path}")


if __name__ == "__main__":
    main()
