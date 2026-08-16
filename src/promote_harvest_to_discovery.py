"""수확본을 발굴 통합본으로 편입한다.

[왜 필요한가 — 실측 2026-08-16]
발굴이 고갈됐다. 검색어 100개를 써서 새 상점 2개를 찾고, 그 2개에서
상품이 0~1건 나온다. 큐텐의 화장품 상점 11,172개를 이미 다 훑었기
때문이다. 검색어를 아무리 바꿔도 가본 곳으로만 이어진다.

그런데 **수확본에 이미 498,722건이 놀고 있었다.**

수확은 발굴이 찾은 상점의 전 상품을 훑어 저장하는데, 저장할 때
이미 우리 조건을 다 통과시킨다:
  · 화장품 카테고리만 (색조·네일·향수 제외)
  · 리뷰 20 이하만
즉 통합본에 들어갈 자격을 이미 갖춘 상품이다. 그런데 지금까지는
검색어 재료로만 쓰고 통합본에는 넣지 않았다.

[왜 한 번에 다 안 넣나]
번역이 사람 손을 거친다. 49만 건을 한꺼번에 올리면 번역 요청서가
2,500장이 된다. 그래서 회차마다 정해진 만큼만 옮긴다.

[어떤 것부터 옮기나]
1. 브랜드를 아는 것 — 검색어에 브랜드가 붙어 검증 통과율이 2.5배 높다
   (실측: 브랜드 붙은 건 52.2% vs 없는 건 20.5%)
2. 상품명이 짧은 것 — 판매자 홍보 문구가 적어 번역·검증이 잘 된다
3. 비화장품은 제외 — 헤어핀·잡화가 섞여 있다
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from nonbeauty_filter import is_non_beauty
except ImportError:  # 필터를 못 읽으면 아무것도 안 거른다(안전한 쪽)
    def is_non_beauty(_text: str) -> bool:
        return False


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", (s or "")).lower()


def load_harvest(items_dir: Path) -> list[dict]:
    """수확본 jsonl을 전부 읽는다."""
    out = []
    for path in sorted(items_dir.glob("fullcatalog_items_*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


# 상품명 최소 길이.
#
# [왜 필요한가 — 실측 2026-08-16] "이름이 짧은 것부터"로 정렬했더니
# 맨 위에 `0`, `[I`, `洗顔` 같은 것들이 올라왔다. 수확 과정에서 이름이
# 잘렸거나 원래 부실한 상품이다. 이런 건 번역해도 무슨 제품인지 알 수
# 없고 검증에서 100% 버려진다 — 사람 번역 시간만 쓴다.
#
# 짧은 것을 먼저 쓰는 원칙 자체는 맞다(판매자 홍보 문구가 적어 검증이
# 잘 된다). 다만 "짧은 것"과 "잘린 것"은 다르다.
# 상품명 길이 구간.
#
# [실측 2026-08-16] 검증 3,986건을 원본 이름 길이별로 갈라 통과율을 쟀다:
#     ~15자   57.1%   정보가 부족하다
#   16~25자   67.5%   <- 가장 좋다
#   26~40자   58.8%
#   41~60자   44.3%
#   61~90자   34.3%   홍보 문구가 검색을 방해한다
#     91자+   34.5%
#
# 처음엔 "짧은 것부터"로만 뽑았다가 사장님이 "번역이 너무 짧다"고
# 지적하셨다. 확인해보니 수확본 전체 평균은 47자인데 하위 7%(11~20자)
# 에서만 뽑고 있었다. 그 구간에는 이런 것들이 있다:
#     子音生2種セット      (브랜드 없이는 무슨 제품인지 모른다)
#     音の数125ml         (潤燥가 깨져서 들어온 것)
# 짧은 게 좋은 이유는 "홍보 문구가 적어서"이지 "정보가 없어서"가 아니다.
MIN_TITLE_LEN = 16
MAX_TITLE_LEN = 40

# 상품이 아직 준비 중이거나 판매를 안 하는 상태를 나타내는 말.
# 번역해봐야 살 수 없으므로 옮기지 않는다.
_NOT_FOR_SALE = re.compile(r"準備中|準備 中|販売終了|品切|在庫なし|SOLD\s*OUT", re.IGNORECASE)


def pick(candidates: list[dict], known_brands: set, limit: int,
         scores: dict | None = None) -> list[dict]:
    """옮길 것을 고른다. 브랜드를 아는 것과 이름이 짧은 것이 먼저."""
    scored = []
    seen_title = set()
    for it in candidates:
        title = (it.get("title") or "").strip()
        if not (MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN):
            continue
        if _NOT_FOR_SALE.search(title):
            continue
        if is_non_beauty(title):
            continue
        brand = (it.get("brand") or "").strip()
        # 같은 브랜드+같은 이름이 여러 번 나온다(상점마다 같은 상품을 판다).
        # 하나만 남긴다 — 번역·검증을 중복으로 돌릴 이유가 없다.
        key = (_norm(brand), _norm(title))
        if key in seen_title:
            continue
        seen_title.add(key)
        has_brand = bool(brand) and (brand in known_brands
                                     or _norm(brand) in known_brands)
        # 순위 기준(앞에서부터):
        #  1) 검증 실적이 나쁜 브랜드는 뒤로 (통과율 20% 미만)
        #  2) 브랜드를 아는 것 먼저 (통과율 52.2% vs 20.5%)
        #  3) 통과율이 가장 높은 길이(16~25자)에 가까운 것
        rate = (scores or {}).get(brand)
        weak = 1 if (rate is not None and rate < 0.2) else 0
        scored.append((weak, 0 if has_brand else 1, abs(len(title) - 22), it))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [it for *_, it in scored[:limit]]





def brand_scores(verified_dir: Path, state: dict) -> dict:
    """브랜드별 검증 통과율을 낸다. 실적이 쌓인 브랜드만 대상.

    [왜 — 09-03 번역 피드백] "소형·신생 브랜드가 배치마다 20~30건씩
    꾸준히 나옵니다. 국내 판매 흔적이 희박해 검증 통과율도 낮을 것으로
    예상되니, 발굴 단계에서 브랜드 인지도로 1차 필터링하는 것도
    고려해볼 만합니다."

    맞는 지적이다. 다만 "인지도"는 재기 어렵고, 우리에게는 더 나은 것이
    있다 — **실제 검증 통과율**이다. 실측 2026-08-16 (검증 4,516건):
      검증 5건 이상 쌓인 브랜드 196개 중
        통과율 20% 미만: 36개 (상품 359건)
        통과율 60% 이상: 92개 (상품 1,361건)
    통과율 낮은 쪽에는 밀본·큐렐·케라스타즈·바세린처럼 한국에서 굳이
    살 이유가 없는 브랜드가 몰려 있다.

    이 실적을 편입 순서에 반영하면, 잘 되는 브랜드가 먼저 올라오고
    안 되는 브랜드는 뒤로 밀린다. 버리지는 않는다 — 표본이 적어
    잘못 판단했을 수 있고, 나중에 사정이 바뀔 수도 있다.
    """
    import glob as _glob
    by = {str(p.get("goods_no")): p for p in state["all_products"]}
    tally = {}
    for path in sorted(_glob.glob(str(verified_dir / "hwahae_verified_[0-9].json"))):
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for x in rows:
            src = by.get(str(x.get("goods_no")))
            if not src:
                continue
            b = (src.get("brand") or "").strip()
            if not b:
                continue
            cur = tally.setdefault(b, [0, 0])
            cur[0] += 1
            if x.get("name"):
                cur[1] += 1
    # 표본 5건 이상인 것만 신뢰한다
    return {b: ok / tot for b, (tot, ok) in tally.items() if tot >= 5}


def promote(state_path: Path, items_dir: Path, dict_path: Path,
            limit: int, apply: bool, verified_dir: Path | None = None) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    existing = {str(p.get("goods_no")) for p in state["all_products"]}

    raw = json.loads(dict_path.read_text(encoding="utf-8"))
    known_brands = {k for k in raw if not k.startswith("_")}
    known_brands |= {_norm(k) for k in known_brands}

    harvest = load_harvest(items_dir)
    fresh = [it for it in harvest
             if str(it.get("goods_no")) not in existing]

    scores = brand_scores(verified_dir, state) if verified_dir else {}
    if scores:
        weak = sum(1 for v in scores.values() if v < 0.2)
        print(f"  브랜드 실적 {len(scores)}개 반영 (통과율 20% 미만 {weak}개는 뒤로)")
    chosen = pick(fresh, known_brands, limit, scores)
    for it in chosen:
        state["all_products"].append({
            "goods_no": it.get("goods_no"),
            "title": it.get("title"),
            "brand": it.get("brand"),
            "passes_filter": True,
            "from_harvest": True,   # 어디서 왔는지 남긴다
        })

    if apply:
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "수확본": len(harvest),
        "통합본에 없는 것": len(fresh),
        "이번에 옮김": len(chosen),
        "통합본": len(state["all_products"]),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--items-dir", required=True)
    ap.add_argument("--dict", required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--verified-dir", help="검증 결과 폴더 (브랜드 실적 반영용)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    s = promote(Path(a.state), Path(a.items_dir), Path(a.dict), a.limit, a.apply,
                Path(a.verified_dir) if a.verified_dir else None)
    for k, v in s.items():
        print(f"  {k}: {v:,}")
    if not a.apply:
        print("(시험 실행 — --apply 를 붙이면 반영)")
