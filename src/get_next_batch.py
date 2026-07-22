"""
get_next_batch.py

1단계(크롤링)는 목표치 없이 계속 돌아가면서 output/discovery_state.json의
all_products를 계속 불려나간다. 이 스크립트는 그중 "아직 번역 안 보낸"
상품만 원하는 개수(N)만큼 뽑아준다 — 이미 뽑은 건 output/translated_tracker.json
에 기록해두고 다음에 다시 안 뽑는다.

사용법:
    python get_next_batch.py <N>
        N건을 뽑아서 output/next_batch.json에 저장하고, 그 goods_no들을
        translated_tracker.json에 "뽑음"으로 기록한다.
"""

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
STATE_PATH = OUTPUT_DIR / "discovery_state.json"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
TRACKER_PATH = OUTPUT_DIR / "translated_tracker.json"
BATCH_PATH = OUTPUT_DIR / "next_batch.json"


def _all_products_including_archive() -> list[dict]:
    """메인 상태파일 + 아카이브로 옮겨진 것까지 전부 합쳐서 반환한다
    (아카이브된 상품도 번역 대상에서 빠지면 안 되므로)."""
    products = []
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        products.extend(state.get("all_products", []))
    if ARCHIVE_DIR.exists():
        for f in sorted(ARCHIVE_DIR.glob("discovery_archive_*.json")):
            products.extend(json.loads(f.read_text(encoding="utf-8")))
    return products


def get_next_batch(n: int) -> list[dict]:
    all_products = _all_products_including_archive()

    tracker = set(json.loads(TRACKER_PATH.read_text(encoding="utf-8"))) if TRACKER_PATH.exists() else set()

    untranslated = [p for p in all_products if p["goods_no"] not in tracker]
    batch = untranslated[:n]

    if not batch:
        print(f"[INFO] 뽑을 수 있는 미번역 상품이 없음(전체 {len(all_products)}건 중 {len(tracker)}건 이미 처리)")
        return []

    tracker.update(p["goods_no"] for p in batch)
    TRACKER_PATH.write_text(json.dumps(list(tracker), ensure_ascii=False, indent=2), encoding="utf-8")
    BATCH_PATH.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] {len(batch)}건 뽑음 (전체 {len(all_products)}건 중 미번역 {len(untranslated)}건 있었음)")
    print(f"       -> {BATCH_PATH}")
    return batch


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    n = int(sys.argv[1])
    batch = get_next_batch(n)
    for p in batch:
        print(" ", p["goods_no"], "|", p.get("brand"), "|", p["title"][:40])
