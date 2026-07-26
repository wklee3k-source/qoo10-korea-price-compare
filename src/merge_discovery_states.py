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
            gno = p["goods_no"]
            existing = products.get(gno)
            # [치명버그 수정] 워커 파일(discovery_state_<N>.json)은 번역을
            # 절대 가지고 있지 않다 — 번역은 오직 이 중앙 병합본에서만
            # 일어난다. 그런데 여기서 워커 파일 내용으로 무조건 덮어쓰면,
            # 방금 번역해둔 translated_kr/known_brand가 지워진다. 워커
            # 파일은 상품을 절대 안 지우므로, 이 상품이 존재하는 한 병합
            # 때마다(매시간) 영원히 반복해서 지워지는 사고였다(실측 확인:
            # 16:57에 1,630건 번역완료 -> 바로 다음 정각 병합에서 0건으로
            # 초기화, 이후 6번의 병합에서도 계속 0건).
            # 기존에 번역이 있고 워커파일엔 없으면, 번역 필드만 보존한다.
            if existing and existing.get("translated_kr") and not p.get("translated_kr"):
                p = {**p, "translated_kr": existing["translated_kr"], "known_brand": existing.get("known_brand", p.get("known_brand", ""))}
            products[gno] = p
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
