"""검증이 끝난 것 중 구매링크가 없는 것을 골라 수집기용 파일로 만든다.

[파이프라인에서 어디인가]
  ⑤ 검증(GitHub Actions) → **⑥ 보완(이 파일이 만드는 입력)** → ⑦ 검수

검증은 이름은 찾았는데 구매링크를 못 찾는 경우가 있다. 네이버가
데이터센터 IP를 막아서 GitHub Actions에서는 스마트스토어가 안 열리기
때문이다. 그 부분만 사장님 PC의 로컬 수집기로 뺐다.

[출력 형식]
수집기 v2.4.1부터 통합 파일을 받는다:
    {"검색대상": [{"goods_no": ..., "query": ..., "brand": ...}]}

[이미 찾아본 것은 다시 넣지 않는다]
수집기로 한 번 돌렸는데 못 찾은 것은 `link_search_exhausted` 표시가
붙는다. 다시 넣어도 결과가 같으므로 뺀다(실측 2026-08-17: 480건 중
118건이 여기 해당). 지우지는 않는다 — 지우면 다음 검증에서 다시
대상이 되어 같은 일을 반복한다.

[거르는 것 — 실측 2026-08-17]
489건을 뽑아 보니 9건이 검색어로 쓸 수 없었다:
  · 이모지가 붙은 블로그 체험단 글
  · "효모", "티암" 같은 한 낱말
  · 중고 판매글("2개+증정용 2개 일괄 새상품 택포")
이런 걸 넣으면 수집기가 20초씩 헛돈다.

[검색어를 다듬는 이유]
검증 결과의 브랜드에는 `아누아 (Anua)`처럼 영문이 괄호로 붙고,
이름 끝에는 `, , 1개` 같은 꼬리가 남는다. 그대로 검색하면 결과가
안 나온다. 실측: 480건 중 49건에 이런 꼬리가 있었다.
"""

from __future__ import annotations

import glob
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 검색어 끝에 붙는 무의미한 꼬리
_TAIL = [
    r",\s*,\s*\d+개$", r",\s*\d+개$", r"\s+\d+개$",
    r",\s*,\s*$", r",\s*$",
]


def clean_query(brand: str, name: str, volume: str = "") -> str:
    """브랜드·이름·용량을 합쳐 검색어를 만든다."""
    b = re.sub(r"\s*\([^)]*\)\s*$", "", brand or "").strip()
    if b and (name or "").startswith(b):
        parts = [name, volume]          # 이름에 이미 브랜드가 있다
    else:
        parts = [b, name, volume]
    q = " ".join(p for p in parts if p)
    for pat in _TAIL:
        q = re.sub(pat, "", q)
    return re.sub(r"\s+", " ", q).strip(" ,")


def build(state_path: Path, verified_dir: Path, out_dir: Path) -> tuple[Path, int, int]:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hwahae_verify_batch import is_junk_name

    state = json.loads(state_path.read_text(encoding="utf-8"))
    base = state_path.parent.parent / "data"
    foreign = set(json.loads((base / "foreign_brands.json").read_text(encoding="utf-8")))
    try:
        blocked = {str(b.get("goods_no"))
                   for b in json.loads((base / "discovery_blocklist.json")
                                       .read_text(encoding="utf-8")).get("blocked", [])
                   if b.get("goods_no")}
    except (OSError, ValueError):
        blocked = set()

    kept = {str(p["goods_no"]) for p in state["all_products"]
            if p.get("translated_kr")
            and (p.get("brand") or "").strip() not in foreign
            and str(p.get("goods_no")) not in blocked}

    rows = []
    for f in sorted(glob.glob(str(verified_dir / "hwahae_verified_[0-9].json"))):
        try:
            rows += json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

    targets, junk = [], 0
    for x in rows:
        g = str(x.get("goods_no"))
        if g not in kept or not x.get("name") or x.get("product_url"):
            continue
        if x.get("sale") is False or x.get("obsolete") is True:
            continue                     # 판매중지 — 찾아도 살 수 없다
        if x.get("link_search_exhausted"):
            continue                     # 이미 수집기로 찾아봤는데 없었다
        if is_junk_name(x["name"]):
            junk += 1
            continue
        targets.append({
            "goods_no": g,
            "query": clean_query(x.get("brand") or "", x["name"], x.get("volume") or ""),
            "brand": x.get("brand") or "",
        })

    # 파일명에 반드시 "통합"이 들어가야 한다.
    #
    # [실측 2026-08-17] 파일명을 "작업대상_검수페이지_...json"으로 붙여
    # 드렸더니 수집기가 "파일명으로 모드를 못 알아봤습니다"를 띄웠다.
    # 수집기는 파일명에서 검색대상 / 수집대상 / 통합 중 하나를 찾아
    # 모드를 정한다(v2.4.2). 내용이 맞아도 이름이 다르면 안 읽는다.
    kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y%m%d_%H%M")
    out = out_dir / f"작업대상_통합_{kst}_KST.json"
    out.write_text(json.dumps({"검색대상": targets}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    return out, len(targets), junk


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--verified-dir", required=True)
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()

    path, n, junk = build(Path(a.state), Path(a.verified_dir), Path(a.out_dir))
    print(f"{n:,}건 → {path.name}")
    if junk:
        print(f"  검색어로 쓸 수 없어 뺀 것: {junk}건")
