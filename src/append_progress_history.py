"""
append_progress_history.py

GitHub Actions가 매 배치(상점 2개 단위, 또는 화해검증 5건 단위)마다 호출해서
output/progress_history.json에 "이 시점의 진행상황" 한 줄을 계속 추가한다.
브라우저를 안 열고 있어도 서버(GitHub Actions) 쪽에서 계속 기록되므로,
대시보드는 이 파일을 읽기만 하면 된다(클라이언트 쪽에서 직접 쌓을 필요 없음).

사용법:
    python append_progress_history.py <output_dir>
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def append_snapshot(output_dir: str):
    out_dir = Path(output_dir)
    history_path = out_dir / "progress_history.json"

    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []

    state_path = out_dir / "discovery_state.json"
    shops = products = None
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        shops = len(state.get("visited_shops", []))
        products = len(state.get("all_products", []))

    verified_path = out_dir / "hwahae_verified_39.json"
    hwahae_done = None
    if verified_path.exists():
        hwahae_done = len(json.loads(verified_path.read_text(encoding="utf-8")))

    entry = {
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shops": shops,
        "products": products,
        "hwahae_done": hwahae_done,
    }
    history.append(entry)
    if len(history) > 500:
        history = history[-500:]  # 너무 커지지 않게 최근 500개만 유지

    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[LOG] {entry}")


if __name__ == "__main__":
    append_snapshot(sys.argv[1] if len(sys.argv) > 1 else "../output")
