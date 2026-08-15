"""번역된 상품명 앞에 한국어 브랜드명을 붙인다.

[왜 필요한가 — 실측 2026-08-15]
재검증 절반 시점에 이름 확정 통과율이 39.6%로, 기존 가정 70.1%에
크게 못 미쳤다. 합의부족 건을 들여다보니 원인이 검색어에 있었다:

    검색어: 아젤라산 CICA 스킨 클리어 토너 250ml   ← 브랜드 없음
    네이버: 아누아 아젤라산 3 아젤라익애씨드 CICA 스킨 클리어 토너  ← 정답
    다음  : AC클리어 CICA 90% 퓨어엔 시카토너&스킨          ← 다른 제품
    판정  : 합의부족(0곳) → 폐기

정답을 찾아놓고도 다른 소스가 엉뚱한 걸 물어와 버려진다. 브랜드
한 단어만 있었으면 두 소스가 같은 제품을 찾았을 것이다.
검증 대상 2,490건 중 브랜드가 이름에 들어간 건 29건(1.2%)뿐이었다.

[브랜드 출처 세 가지 — 신뢰도 순]
1. known_brand 필드 — 발굴이 이미 확정해둔 한국어 브랜드
2. 브랜드 번역 사전 — 일본어/영문 브랜드 → 한국어
3. 검증 결과에서 새로 배운 쌍 — 단, 다수결을 통과한 것만

3번은 검증이 오매칭한 건에서 엉뚱한 브랜드가 딸려 온다(실측:
`aXENDA → 내추럴아린메디`, `temporary → 아브카`). 그래서 같은 일본어
브랜드에 대해 **2건 이상에서 80% 이상 같은 답이 나온 경우만** 채택한다.
431개 후보 중 101개만 통과했다.

[안 붙이는 경우]
- 이름에 이미 그 브랜드가 들어 있음
- 한국어 브랜드를 모름 (일본어/영문 브랜드를 그대로 붙이면 한국
  쇼핑몰 검색에서 오히려 방해가 된다)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

MIN_VOTES = 2
MIN_RATIO = 0.8


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", (s or "")).lower()


def learn_from_verified(verified_paths, products_by_no) -> dict:
    """검증 결과에서 '일본어 브랜드 → 한국어 브랜드'를 배운다(다수결)."""
    votes = defaultdict(Counter)
    for path in verified_paths:
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows:
            raw = (row.get("brand") or "").strip()
            if not raw:
                continue
            kr = re.sub(r"\s*\(.*?\)\s*$", "", raw).strip()
            product = products_by_no.get(str(row.get("goods_no")))
            if not product or not kr:
                continue
            jb = (product.get("brand") or "").strip()
            if jb:
                votes[jb][kr] += 1
    learned = {}
    for jb, counter in votes.items():
        kr, n = counter.most_common(1)[0]
        if n >= MIN_VOTES and n / sum(counter.values()) >= MIN_RATIO:
            learned[jb] = kr
    return learned


def resolve_korean_brand(product, dictionary, dict_norm) -> str:
    """이 상품의 한국어 브랜드명. 모르면 빈 문자열."""
    known = (product.get("known_brand") or "").strip()
    if known:
        return known
    raw = (product.get("brand") or "").strip()
    if not raw:
        return ""
    return dictionary.get(raw) or dict_norm.get(_norm(raw)) or ""


def attach(state_path: str, dict_path: str, verified_paths, apply: bool) -> dict:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    products = state["all_products"]
    by_no = {str(p.get("goods_no")): p for p in products}

    dictionary = {
        k: v
        for k, v in json.loads(Path(dict_path).read_text(encoding="utf-8")).items()
        if not k.startswith("_")
    }
    learned = learn_from_verified(verified_paths, by_no)
    added = {k: v for k, v in learned.items() if k not in dictionary}
    dictionary.update(added)
    dict_norm = {_norm(k): v for k, v in dictionary.items()}

    stat = Counter()
    for product in products:
        name = product.get("translated_kr") or ""
        if not name:
            stat["미번역"] += 1
            continue
        brand = resolve_korean_brand(product, dictionary, dict_norm)
        if not brand:
            stat["브랜드모름"] += 1
            continue
        if brand in name or _norm(brand) in _norm(name):
            stat["이미포함"] += 1
            continue
        if apply:
            product["translated_kr"] = f"{brand} {name}"
        stat["부착"] += 1

    if apply:
        Path(state_path).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        full = json.loads(Path(dict_path).read_text(encoding="utf-8"))
        full.update(added)
        Path(dict_path).write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    stat["사전신규"] = len(added)
    return stat


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--dict", required=True)
    ap.add_argument("--verified", nargs="*", default=[])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    s = attach(a.state, a.dict, a.verified, a.apply)
    print(
        f"부착 {s['부착']:,} | 이미포함 {s['이미포함']:,} | "
        f"브랜드모름 {s['브랜드모름']:,} | 미번역 {s['미번역']:,} | "
        f"사전신규 {s['사전신규']:,}"
    )
    if not a.apply:
        print("(시험 실행 — 파일을 바꾸지 않았습니다. --apply 를 붙이면 반영)")
    sys.exit(0)
