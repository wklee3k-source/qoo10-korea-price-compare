"""naver_rematch_probe.py — '승자 이름으로 네이버 재검색'의 회수율을 표본으로 측정.

[왜 재는가] 구매링크는 사실상 네이버쇼핑에서만 나온다(실측: 링크 확보
885건 중 867건 = 98%). 그래서 네이버가 못 찾으면 다른 소스가 다 찾아도
버려진다 — 링크 실패 651건 중 367건(56%)이 '화해는 찾았는데 네이버만
못 찾은' 경우다.

화해가 정확한 한국 상품명을 이미 알려줬으므로, 그 이름으로 네이버를
한 번 더 검색하면 상당수를 되살릴 수 있다는 가설이다. 다만 가설일 뿐이라
구현 전에 표본으로 실제 회수율을 잰다 — 회수율이 낮으면 검증 시간만
늘리고 얻는 게 없다.

이 스크립트는 아무것도 바꾸지 않는다(읽기 전용 측정).

사용법:
    python naver_rematch_probe.py <검증본.json> [표본수]
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from naver_shop_search import search as naver_search  # noqa: E402

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1"))
# 링크 출처가 되는 소스. 이 소스들이 못 찾은 게 문제의 원인이다.
LINK_SOURCES = {"naver", "musinsa"}


def pick_targets(rows: list[dict], limit: int) -> list[dict]:
    """네이버는 못 찾았지만 다른 소스가 이름을 확보한 건."""
    targets = []
    for r in rows:
        if r.get("product_url"):
            continue
        summary = r.get("candidates_summary") or {}
        if not summary:
            continue
        if summary.get("naver"):
            continue                      # 네이버가 이미 뭔가 찾은 건은 대상 아님
        # 이름을 알려준 소스 중 상품DB 쪽을 우선(제목만 주는 소스보다 정확)
        for src in ("hwahae", "musinsa", "daum", "naver_web", "exa"):
            name = (summary.get(src) or "").strip()
            if name:
                targets.append({"goods_no": r.get("goods_no"), "name": name,
                                "src": src, "original": r.get("translated_kr")})
                break
        if len(targets) >= limit:
            break
    return targets


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    if not path.exists():
        print(f"[중단] {path} 없음")
        return 1

    rows = json.loads(path.read_text(encoding="utf-8"))
    targets = pick_targets(rows, limit)
    print(f"[표본] 링크 실패 중 '네이버만 못 찾은' 건 {len(targets)}개로 측정")
    if not targets:
        print("[중단] 표본이 없다")
        return 0

    recovered, empty, failed, trust_only = 0, 0, 0, 0
    by_src = Counter()
    samples = []
    for i, t in enumerate(targets, 1):
        try:
            hits = naver_search(t["name"], display=5, strict_trust_only=True)
            loose = hits or naver_search(t["name"], display=5, strict_trust_only=False)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [{i}] 호출실패: {type(e).__name__}: {e}")
            time.sleep(REQUEST_DELAY)
            continue
        # [주의] naver_shop_search.search()는 'product_url'이 아니라 'link'를
        # 돌려준다. 첫 측정에서 이걸 잘못 봐서 회수율이 0%로 나왔다 —
        # 가설이 틀린 게 아니라 자가 측정이 틀렸던 것.
        got = hits[0] if hits else None
        if got and got.get("link"):
            recovered += 1
            by_src[t["src"]] += 1
            if len(samples) < 8:
                samples.append((t, got))
        elif loose and loose[0].get("link"):
            # 검색은 됐는데 '신뢰 판매처' 필터에서 전부 빠진 경우.
            # 회수 실패의 원인이 검색 실패인지 필터인지 구분해야, 필터를
            # 손볼지 검색을 손볼지 판단할 수 있다.
            trust_only += 1
        else:
            empty += 1
        if i % 20 == 0:
            print(f"  ...{i}/{len(targets)} 진행 (회수 {recovered})")
        time.sleep(REQUEST_DELAY)

    n = len(targets)
    print("\n" + "=" * 56)
    print(f"표본 {n}건")
    print(f"  회수 성공(구매링크 확보): {recovered}건 ({recovered / n * 100:.1f}%)")
    print(f"  검색은 됐으나 신뢰필터에 걸림: {trust_only}건")
    print(f"  여전히 못 찾음          : {empty}건")
    print(f"  호출 실패               : {failed}건")
    print(f"  이름을 준 소스별 회수   : {dict(by_src)}")
    print("=" * 56)
    print("\n[회수 사례]")
    for t, got in samples:
        print(f"  큐텐  : {str(t['original'])[:40]}")
        print(f"  {t['src']:9s}: {t['name'][:40]}")
        print(f"  → 네이버: {str(got.get('title'))[:40]} / {got.get('mallName')} "
              f"[{got.get('seller_trust')}]\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
