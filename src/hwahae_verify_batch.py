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
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# 검색어에서 용량 표기("110ml", "1L" 등)를 제거하는 정규식 — 실측으로 확인된
# 근본원인: 화해 검색엔진은 "숫자+단위"가 섞인 검색어를 받으면 결과가 불안정해진다
# (예: "BERGAMO 24K 럭셔리 골드 앰플 110ml" 검색 → 완전 무관한 상품이 나옴,
#  같은 검색어에서 "110ml"만 뺀 "BERGAMO 24K 럭셔리 골드 앰플"은 항상 정답).
# 용량은 이미 known_volume 파라미터로 따로 전달하고 있으니 검색어엔 필요없다.
VOLUME_IN_QUERY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL|ml|g|L)\b")


def _correct_name_isolated(keyword: str, known_volume: str) -> dict:
    """완전히 새 파이썬 서브프로세스에서 실행한다(사용자 제안 반영).
    개별 실행에서는 '베일리' 오탐이 재현이 안 되고, 같은 프로세스 안에서
    Playwright sync_playwright()를 반복 시작/종료할 때만 발생하는 것으로
    보여서, 매 검색을 완전히 격리된 프로세스로 돌려 검증해본다."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "hwahae_name_corrector.py"), keyword, known_volume],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(proc.stdout)
    except Exception as e:  # noqa: BLE001
        return {"brand": None, "corrected": None, "volume": "", "_error": str(e)}


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
        kw_raw = item["translated_kr"]
        known_volume = item.get("volume", "")
        kw = VOLUME_IN_QUERY_RE.sub("", kw_raw).strip()  # 검색어에서 용량 제거(근본원인 수정)
        print(f"[검색-격리실행] {item['goods_no']}: {kw}" + (f" (용량:{known_volume})" if known_volume else ""))
        r = _correct_name_isolated(kw, known_volume)

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
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
