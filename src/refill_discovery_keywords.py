"""발굴 검색어 자동 보충 — 수확본(fullcatalog) 상품명을 발굴 검색어로 재활용.

[왜 필요한가 — 실측 사고]
발굴 워커는 자기가 방문한 상점에서 나온 상품명으로 검색어를 재생산하는데,
재생산율이 1보다 낮으면 큐가 서서히 말라붙는다. 그런데 워크플로의
"Prepare this branch's seed keywords" 단계는 **브랜치 전용 상태파일이
없을 때 딱 한 번만** 시드를 나눠줬다. 그래서 파일이 이미 있는 워커의
pending_keywords가 0이 되면, 그 워커는 영원히 아무것도 안 하는
빈 실행만 반복한다.

실측(2026-07-28):
    워커0  pending 2,237개  → 정상 가동
    워커1  pending     0개  → 완전 정지 (발굴 처리량 50% 손실)
    통합본 pending     0개  → 재분배할 재료조차 없음

수확본에는 상품명 60,289개(고유)가 이미 쌓여 있고, 운영 방침상
"수확 상품은 검수 대상이 아니라 발굴 검색어 재료로만 쓴다"이므로
이 스크립트가 그 연결고리를 자동화한다.

[배정 규칙 — 인덱스가 아니라 결정적 해시]
기존 시드 분배는 `i % N`(리스트 인덱스 기준)이었다. 보충은 워커마다
서로 다른 시점에 서로 다른 제외집합을 들고 돌기 때문에, 인덱스 기준으로
나누면 두 워커가 같은 검색어를 집어갈 수 있다. 검색어 문자열의 md5를
워커수로 나눈 나머지로 배정하면 언제 돌든 파티션이 항상 서로소다.

⚠️ 아래 WORKER_COUNT 기본값(2)은 워크플로 matrix.branch 개수와 반드시
같아야 한다. 다르면 남는 나머지값 검색어가 어느 워커에도 안 간다.
simulation.py 항목 40/43이 이걸 자동 검사한다.

사용법:
    python refill_discovery_keywords.py \
        --state ../output/discovery_state_1.json \
        --worker 1 --workers 2 \
        --pool /tmp/fcpool \
        --peer-dir ../output \
        --limit 4000
"""

from __future__ import annotations

import argparse
import glob
import html
import hashlib
import json
import os
import re
import sys

# 발굴 스크립트와 동일한 core 추출 로직을 그대로 재사용한다(중복 구현 금지 —
# 규칙이 갈라지면 "이미 쓴 검색어"를 제대로 못 걸러 같은 상점을 재방문한다).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iterative_low_review_discovery import extract_core_keyword  # noqa: E402

# 검색어 한 개의 최대 길이. 큐텐 상품명은 30~80자로 매우 길어서 통째로
# 검색하면 결과가 0건이다(실측). 토큰 경계에서 잘라 앞부분만 쓴다.
MAX_KEYWORD_LEN = 24
MIN_KEYWORD_LEN = 4

_LEAD_JUNK_RE = re.compile(r"^[^\wぁ-んァ-ヴ一-龥A-Za-z0-9]+")
_HAS_WORD_RE = re.compile(r"[ぁ-んァ-ヴ一-龥A-Za-z]")


def shorten_keyword(core: str) -> str:
    """core 검색어를 실제로 검색 가능한 길이로 줄인다. 못 쓰면 빈 문자열."""
    core = html.unescape(core)  # 큐텐 상품명에 &amp; 같은 엔티티가 그대로 들어있다
    core = _LEAD_JUNK_RE.sub("", core).strip()
    picked: list[str] = []
    for token in core.split():
        if picked and len(" ".join(picked + [token])) > MAX_KEYWORD_LEN:
            break
        picked.append(token)
    result = " ".join(picked).strip()
    if len(result) < MIN_KEYWORD_LEN or not _HAS_WORD_RE.search(result):
        return ""
    return result


def assign_worker(keyword: str, workers: int) -> int:
    """검색어 → 담당 워커 번호(결정적). 언제 돌려도 같은 답이 나온다."""
    return int(hashlib.md5(keyword.encode("utf-8")).hexdigest(), 16) % workers


def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        print(f"  [건너뜀] {path}: {exc}")
        return None


def collect_used_keywords(state_path: str, peer_dir: str | None) -> set[str]:
    """이미 쓴/대기 중인 검색어 전부 — 자기 자신 + 통합본 + 다른 워커 샤드.

    다른 워커 것까지 보는 이유: 해시 배정이 바뀌거나(워커수 변경) 과거
    인덱스 배정으로 이미 소비된 검색어를 다시 큐에 넣지 않기 위해서다.
    """
    used: set[str] = set()
    paths = [state_path]
    if peer_dir:
        paths += sorted(glob.glob(os.path.join(peer_dir, "discovery_state*.json")))
    for path in dict.fromkeys(paths):
        state = _load_json(path)
        if not isinstance(state, dict):
            continue
        used |= set(state.get("seen_keywords") or [])
        used |= set(state.get("pending_keywords") or [])
    return used


def collect_pool_titles(pool_dir: str) -> set[str]:
    """수확본 샤드에서 상품명만 모은다(읽기 전용 — 절대 수정하지 않는다)."""
    titles: set[str] = set()
    files = sorted(glob.glob(os.path.join(pool_dir, "fullcatalog_state*.json")))
    if not files:
        print(f"  [경고] 수확본을 못 찾음: {pool_dir}/fullcatalog_state*.json")
    for path in files:
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        products = data.get("all_products") or []
        items = products.values() if isinstance(products, dict) else products
        for item in items:
            title = (item or {}).get("title")
            if title:
                titles.add(title)
        print(f"  [수확본] {os.path.basename(path)} 상품 {len(products):,}건")
    return titles


def build_fresh_keywords(titles: set[str], used: set[str], worker: int, workers: int) -> list[str]:
    fresh: set[str] = set()
    for title in titles:
        keyword = shorten_keyword(extract_core_keyword(title))
        if not keyword or keyword in used:
            continue
        if assign_worker(keyword, workers) != worker:
            continue
        fresh.add(keyword)
    return sorted(fresh)


def refill(state_path: str, worker: int, workers: int, pool_dir: str,
           peer_dir: str | None, limit: int, threshold: int, dry_run: bool) -> int:
    state = _load_json(state_path)
    if not isinstance(state, dict):
        print(f"[중단] 상태파일을 못 읽음: {state_path}")
        return 1

    pending = state.get("pending_keywords") or []
    if len(pending) > threshold:
        print(f"[보충 불필요] pending {len(pending)}개 > 임계 {threshold}개")
        return 0

    print(f"[보충 시작] 워커 {worker}/{workers}, 현재 pending {len(pending)}개")
    used = collect_used_keywords(state_path, peer_dir)
    print(f"  [제외집합] 이미 쓴/대기 검색어 {len(used):,}개")
    titles = collect_pool_titles(pool_dir)
    print(f"  [재료] 수확 상품명 {len(titles):,}건(고유)")

    fresh = build_fresh_keywords(titles, used, worker, workers)
    print(f"  [신규] 이 워커 몫 {len(fresh):,}개")
    if not fresh:
        print("[보충 실패] 새 검색어가 0개 — 수확을 더 돌려야 한다")
        return 2

    added = fresh[:limit]
    if dry_run:
        print(f"[모의실행] {len(added):,}개를 넣었을 것 (샘플: {added[:3]})")
        return 0

    # pending 끝에 붙인다(앞에 넣으면 재개 중이던 검색어가 밀린다).
    state["pending_keywords"] = list(pending) + added
    tmp_path = state_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, state_path)  # 원자적 교체 — 중간에 죽어도 원본 안 깨짐
    print(f"[보충 완료] {len(added):,}개 추가 → pending {len(state['pending_keywords']):,}개")
    print(f"  샘플: {added[:3]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, help="이 워커의 discovery_state_<N>.json")
    parser.add_argument("--worker", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2, help="발굴 워커 총수(matrix 개수와 일치)")
    parser.add_argument("--pool", required=True, help="fullcatalog_state*.json이 있는 폴더")
    parser.add_argument("--peer-dir", default=None, help="다른 워커 샤드가 있는 폴더(중복방지)")
    parser.add_argument("--limit", type=int, default=4000, help="한 번에 넣을 최대 개수")
    parser.add_argument("--threshold", type=int, default=0,
                        help="pending이 이 값 이하일 때만 보충(기본 0 = 완전 고갈 시에만)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.workers < 1 or not (0 <= args.worker < args.workers):
        print(f"[중단] 워커번호({args.worker})가 워커수({args.workers}) 범위를 벗어남")
        return 1
    return refill(args.state, args.worker, args.workers, args.pool,
                  args.peer_dir, args.limit, args.threshold, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
