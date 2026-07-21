"""
hwahae_verify_batch.py

사전 준비된 (goods_no, 클로드가 번역한 한글 핵심어) 목록을 받아서, 각각을
화해(hwahae.co.kr)에 검색해 정식 브랜드+상품명+용량으로 검증한다.
GitHub Actions 백그라운드 실행을 염두에 두고 매 건마다 즉시 저장한다
(타임아웃 걸려도 이어서 진행 가능).

사용법:
    python hwahae_verify_batch.py <input.json> <output.json>
        input.json: [{"goods_no": "...", "translated_kr": "..."}, ...]
        output.json: [{"goods_no":..., "translated_kr":..., "hwahae_brand":...,
                        "hwahae_name":..., "hwahae_volume":...}, ...]
"""

import json
import sys
from pathlib import Path

from hwahae_name_corrector import correct_name


def run_batch(input_path: str, output_path: str, max_new: int | None = None):
    items = json.loads(Path(input_path).read_text(encoding="utf-8"))

    out_path = Path(output_path)
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {r["goods_no"] for r in results}
    print(f"[INFO] 전체 {len(items)}건 중 이미 처리된 {len(done)}건부터 이어서 진행")

    processed_this_call = 0
    for item in items:
        if item["goods_no"] in done:
            continue
        if max_new is not None and processed_this_call >= max_new:
            print(f"[STOP] 이번 호출分({max_new}건) 처리 완료 — 나머지는 다음 호출에서 이어서")
            break
        kw = item["translated_kr"]
        known_volume = item.get("volume", "")
        print(f"[검색] {item['goods_no']}: {kw}" + (f" (용량:{known_volume})" if known_volume else ""))
        try:
            r = correct_name(kw, known_volume=known_volume)
        except Exception as e:  # noqa: BLE001
            print(f"    [실패] {e}")
            r = {"brand": None, "corrected": None, "volume": ""}

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw,
            "hwahae_brand": r.get("brand"),
            "hwahae_name": r.get("corrected"),
            "hwahae_volume": r.get("volume"),
        }
        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["hwahae_name"] or "매칭실패"
        print(f"    -> {entry['hwahae_brand']} {status} {entry['hwahae_volume']}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
