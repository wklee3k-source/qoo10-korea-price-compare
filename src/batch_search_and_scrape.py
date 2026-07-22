"""
batch_search_and_scrape.py

자동화 영역: 여러 상품(핵심 문구) 목록을 한 번에 처리한다.
각 키워드에 대해:
    1) Qoo10 검색 → 판매자별 리뷰수 정렬 → 최저리뷰 상점의 상품 선택
    2) 그 상품의 상세정보(JSON-LD) 스크랩

사용법:
    python batch_search_and_scrape.py <keywords.txt>

    keywords.txt: 한 줄에 하나씩 "브랜드 + 고유명 + 용량" 형식의 검색 키워드

출력:
    output/search_<키워드>.json      (qoo10_low_review_shop_finder.py와 동일 형식)
    output/items/<goods_no>.json     (qoo10_item_detail_scraper.py와 동일 형식)
    output/batch_summary.json        (키워드 -> 선정된 상점/상품 요약)
"""

import json
import re
import sys
from pathlib import Path

from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_item_detail_scraper import fetch_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def run_batch(keywords: list[str]) -> list[dict]:
    summary = []

    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue

        print(f"\n[STEP] 검색: {keyword}")
        html = search_qoo10(keyword)
        sellers = parse_results(html)

        safe_name = re.sub(r"[^\w]+", "_", keyword)[:50]
        search_path = OUTPUT_DIR / f"search_{safe_name}.json"
        search_path.write_text(json.dumps(sellers, ensure_ascii=False, indent=2), encoding="utf-8")

        if not sellers:
            print(f"[WARN] 검색 결과 없음: {keyword}")
            summary.append({"keyword": keyword, "status": "no_results"})
            continue

        lowest = sellers[0]
        print(
            f"[STEP] 저리뷰 상점 선정: {lowest['shop_name']} ({lowest['shop_id']}), "
            f"review={lowest['review_count']}, goods_no={lowest['goods_no']}"
        )

        print(f"[STEP] 상세정보 스크랩: goods_no={lowest['goods_no']}")
        detail = fetch_item_detail(lowest["goods_no"])
        items_dir = OUTPUT_DIR / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        goods_no = detail.get("goods_no") or lowest["goods_no"]
        (items_dir / f"{goods_no}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        summary.append(
            {
                "keyword": keyword,
                "status": "ok",
                "shop_id": lowest["shop_id"],
                "shop_name": lowest["shop_name"],
                "review_count": lowest["review_count"],
                "goods_no": goods_no,
                "item_name": detail.get("item_name"),
                "price_jpy": detail.get("price_jpy"),
                "image_main_url": detail.get("image_main_url"),
            }
        )

    return summary


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    keywords = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    OUTPUT_DIR.mkdir(exist_ok=True)

    summary = run_batch(keywords)

    summary_path = OUTPUT_DIR / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[DONE] {len(summary)}건 처리 완료 -> {summary_path}")
    ok = sum(1 for s in summary if s["status"] == "ok")
    print(f"[DONE] 성공 {ok}건 / 실패 {len(summary) - ok}건")


if __name__ == "__main__":
    main()
