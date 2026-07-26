"""
merge_fullcatalog_states.py

12워커가 각자 쓴 fullcatalog_state_<0~11>.json(전체상품 수확 결과)을
fullcatalog_state.json 하나로 합친다. discovery_state.json(발굴 병합본)과는
완전히 별도로 저장하되, 중복 상품(goods_no가 같은 것)이 있으면 발굴 쪽을
우선시켜서 수확본에서는 제외한다 — "발굴이 이미 갖고 있는 상품을 수확본이
또 들고 있을 필요는 없다"는 원칙.

사용법:
    python merge_fullcatalog_states.py <output_dir> <discovery_state_json_path>
        output_dir 안의 fullcatalog_state_*.json 전부를 병합해서
        fullcatalog_state.json으로 저장한다. discovery_state_json_path에
        있는 파일의 all_products와 goods_no가 겹치면 그 상품은 수확본에서
        제외한다(발굴 우선).
"""

import json
import sys
from pathlib import Path


def merge(output_dir: str, discovery_state_path: str | None):
    out_dir = Path(output_dir)
    partial_files = sorted(out_dir.glob("fullcatalog_state_*.json"))
    print(f"[INFO] 병합할 파일 {len(partial_files)}개: {[f.name for f in partial_files]}")

    # 발굴(discovery) 쪽에 이미 있는 goods_no는 수확본에서 제외한다(발굴 우선).
    discovery_goods_no = set()
    if discovery_state_path and Path(discovery_state_path).exists():
        try:
            d = json.loads(Path(discovery_state_path).read_text(encoding="utf-8"))
            discovery_goods_no = {p["goods_no"] for p in d.get("all_products", [])}
            print(f"[INFO] 발굴본 상품 {len(discovery_goods_no)}건과 대조해서 중복 제외")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 발굴본을 못 읽어서 중복제외 없이 진행: {e}", file=sys.stderr)

    main_path = out_dir / "fullcatalog_state.json"
    merged = json.loads(main_path.read_text(encoding="utf-8")) if main_path.exists() else {
        "harvested_shops": [], "all_products": {},
    }

    harvested = set(merged.get("harvested_shops", []))
    # all_products는 기존엔 dict(goods_no->item)로 저장했었다. 과거 포맷이
    # list였을 경우도 방어적으로 처리한다.
    products = merged.get("all_products", {})
    if isinstance(products, list):
        products = {p["goods_no"]: p for p in products}

    excluded_count = 0
    for f in partial_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        harvested.update(data.get("harvested_shops", []))
        shard_products = data.get("all_products", {})
        if isinstance(shard_products, list):
            shard_products = {p["goods_no"]: p for p in shard_products}
        for gno, p in shard_products.items():
            if gno in discovery_goods_no:
                excluded_count += 1
                continue  # 발굴 우선 — 이미 발굴본에 있으면 수확본엔 안 넣는다
            products[gno] = p

    result = {
        "harvested_shops": list(harvested),
        "all_products": products,
    }
    main_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[DONE] 수확 병합 완료 -> {main_path} "
        f"(수확상점 {len(harvested)}개, 수확전용상품 {len(products)}건, "
        f"발굴과 중복돼서 제외된 건수 {excluded_count}건)"
    )


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "../output"
    discovery_path = sys.argv[2] if len(sys.argv) > 2 else None
    merge(out_dir, discovery_path)
