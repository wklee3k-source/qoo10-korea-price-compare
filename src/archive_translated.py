"""
archive_translated.py

2단계(번역)가 방금 새로 번역한 상품들을, discovery-live 브랜치의
discovery_state.json(1단계 활성 풀)에서 꺼내 archive/로 옮긴다.

[설계] 1단계는 순수 발굴+병합만 하고 번역상태를 전혀 몰라도 되도록,
"번역완료 -> 아카이브 이동" 책임을 여기(2단계)로 옮겼다. 2단계는 이미
번역을 마친 직후라 "무엇이 새로 번역됐는지" 정확히 알고 있으므로, 이
스크립트를 그 직후에 한 번 실행해서 discovery-live를 정리한다.

사용법:
    python archive_translated.py <discovery_output_dir>
        discovery_output_dir/discovery_state.json에서
        output/hwahae_input_39.json(번역완료 목록, 2단계 결과물)에
        있는 goods_no들을 찾아 archive/로 옮기고 discovery_state.json을
        갱신한다.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def archive_translated(discovery_dir: str, translated_path: str):
    disc_dir = Path(discovery_dir)
    state_path = disc_dir / "discovery_state.json"
    archive_dir = disc_dir / "archive"

    if not state_path.exists():
        print(f"[SKIP] {state_path} 없음")
        return

    state = json.loads(state_path.read_text(encoding="utf-8"))
    all_products = {p["goods_no"]: p for p in state.get("all_products", [])}

    translated = json.loads(Path(translated_path).read_text(encoding="utf-8"))
    translated_goods = {x["goods_no"] for x in translated}

    to_archive = {k: v for k, v in all_products.items() if k in translated_goods}
    to_keep = {k: v for k, v in all_products.items() if k not in translated_goods}

    if not to_archive:
        print("[INFO] 새로 아카이브할 항목 없음")
        return

    archive_dir.mkdir(exist_ok=True, parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"discovery_archive_{stamp}.json"
    archive_path.write_text(
        json.dumps(list(to_archive.values()), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    state["all_products"] = list(to_keep.values())
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] {len(to_archive)}건을 {archive_path.name}(으)로 이동, "
          f"활성풀엔 {len(to_keep)}건 유지")


if __name__ == "__main__":
    discovery_dir = sys.argv[1] if len(sys.argv) > 1 else "../discovery_output"
    translated_path = sys.argv[2] if len(sys.argv) > 2 else "../output/hwahae_input_39.json"
    archive_translated(discovery_dir, translated_path)
