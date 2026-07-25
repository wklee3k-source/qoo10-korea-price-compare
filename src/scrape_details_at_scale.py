"""
scrape_details_at_scale.py

discovery200_summary.json(1단계 결과)에 있는 상품 전체를 대상으로
qoo10_item_detail_scraper.py를 돌려서 2단계(상세정보)+3단계(코드매칭, 스크래퍼에
내장됨)를 완료한다. output/items/<goods_no>.json에 없는 것만 이어서 처리한다
(재실행 시 중복 작업 없이 이어짐).

사용법:
    python scrape_details_at_scale.py <discovery_summary.json>
"""

import json
import sys
from pathlib import Path

from qoo10_item_detail_scraper import fetch_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    products = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    items_dir = OUTPUT_DIR / "items"
    items_dir.mkdir(exist_ok=True, parents=True)

    already_done = {p.stem for p in items_dir.glob("*.json")}
    print(f"[RESUME] 이미 완료된 상품 {len(already_done)}건")

    todo = [p for p in products if p.get("goods_no") not in already_done]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(products)}건")

    done_count = 0
    for p in todo:
        goods_no = p.get("goods_no")
        if not goods_no:
            continue
        try:
            detail = fetch_item_detail(goods_no)
            out_goods_no = detail.get("goods_no") or goods_no
            (items_dir / f"{out_goods_no}.json").write_text(
                json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            done_count += 1
            print(f"[{done_count}/{len(todo)}] {goods_no} -> {detail.get('item_name', '')[:40]}")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {goods_no} 실패: {e}")

    print(f"\n[DONE] 이번 실행에서 {done_count}건 처리, 누적 {len(already_done) + done_count}건")


if __name__ == "__main__":
    main()
