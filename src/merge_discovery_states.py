"""
merge_discovery_states.py

병렬로 돌린 여러 discovery_state_<suffix>.json 파일들을 하나의
discovery_state.json으로 합친다. 각 병렬 작업(GitHub Actions matrix job)이
서로 다른 파일에 쓰기 때문에 git 충돌 없이 병렬 실행이 가능하고, 이
스크립트가 마지막에 한 번만 합쳐서 메인 상태 파일을 만든다.

사용법:
    python merge_discovery_states.py <output_dir>
        output_dir 안의 discovery_state_*.json 전부를 찾아서 병합하고
        discovery_state.json에 저장한다(중복 상점/상품은 자동 제거).
"""

import json
import sys
from pathlib import Path


def merge(output_dir: str):
    out_dir = Path(output_dir)
    partial_files = sorted(out_dir.glob("discovery_state_*.json"))
    print(f"[INFO] 병합할 파일 {len(partial_files)}개: {[f.name for f in partial_files]}")

    main_path = out_dir / "discovery_state.json"
    merged = json.loads(main_path.read_text(encoding="utf-8")) if main_path.exists() else {
        "visited_shops": [], "all_products": [], "shop_urls": [], "pending_keywords": [], "seen_keywords": []
    }

    visited = set(merged["visited_shops"])
    products = {p["goods_no"]: p for p in merged["all_products"]}
    urls = set(merged["shop_urls"])
    seen_kw = set(merged.get("seen_keywords") or [])

    for f in partial_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        visited.update(data.get("visited_shops", []))
        for p in data.get("all_products", []):
            products[p["goods_no"]] = p
        urls.update(data.get("shop_urls", []))
        seen_kw.update(data.get("seen_keywords") or [])

    merged = {
        "visited_shops": list(visited),
        "all_products": list(products.values()),
        "shop_urls": list(urls),
        "pending_keywords": [],  # 병합 후에는 다음 라운드 시드를 새로 정해야 하므로 비움
        "seen_keywords": list(seen_kw),
    }
    main_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] 병합 완료 -> {main_path} (상점 {len(visited)}개, 상품 {len(products)}건)")


if __name__ == "__main__":
    merge(sys.argv[1] if len(sys.argv) > 1 else "../output")
