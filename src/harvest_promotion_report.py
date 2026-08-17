"""수확본에서 옮긴 것들이 실제로 얼마나 팔 만한지 잰다.

[왜 만들었나 — 사장님 방침 2026-08-17]
수확본에 옮길 수 있는 상품이 171,365건 있다. 다 옮기려면 번역
요청서 856장, 하루 10장씩 해도 85일이 걸린다. 그래서 "회차마다
2,000건씩 옮기고 성과를 보며 조절한다"로 정했다.

조절하려면 근거가 있어야 한다. 이 도구가 회차마다 그 근거를 만든다:
  · 편입분이 발굴분보다 잘 되는가 (이름확정률·구매링크율)
  · 어느 브랜드가 잘 되고 어느 브랜드가 안 되는가
  · 남은 물량이 얼마나 되는가

[읽는 법]
편입분 성과가 전체 평균보다 높으면 계속 옮긴다. 낮아지기 시작하면
좋은 것을 다 퍼낸 것이므로 회차당 물량을 줄이거나 멈춘다.
"""

from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", (s or "")).lower()


def measure(state_path: Path, verified_dir: Path, items_dir: Path,
            dict_path: Path, foreign_path: Path) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    products = state["all_products"]
    by_id = {str(p["goods_no"]): p for p in products}

    rows = []
    for f in sorted(glob.glob(str(verified_dir / "hwahae_verified_[0-9].json"))):
        try:
            rows += json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

    def split(items):
        """검증 결과 묶음을 이름확정·구매링크로 가른다."""
        named = [x for x in items if x.get("name")]
        link = [x for x in named if x.get("product_url")]
        return len(items), len(named), len(link)

    harvest_ids = {str(p["goods_no"]) for p in products if p.get("from_harvest")}
    from_harvest = [x for x in rows if str(x.get("goods_no")) in harvest_ids]
    from_discover = [x for x in rows if str(x.get("goods_no")) not in harvest_ids]

    h_tot, h_named, h_link = split(from_harvest)
    d_tot, d_named, d_link = split(from_discover)

    # 브랜드별 성과 — 다음 회차에 무엇을 먼저 옮길지 정하는 근거
    per = defaultdict(lambda: [0, 0])
    for x in rows:
        src = by_id.get(str(x.get("goods_no")))
        if not src:
            continue
        b = (src.get("brand") or "").strip()
        if not b:
            continue
        per[b][0] += 1
        if x.get("name"):
            per[b][1] += 1
    good = {b for b, (t, o) in per.items() if t >= 5 and o / t >= 0.6}
    bad = {b for b, (t, o) in per.items() if t >= 5 and o / t < 0.2}

    # 남은 물량
    raw = json.loads(dict_path.read_text(encoding="utf-8"))
    known = {k for k in raw if not k.startswith("_")}
    known |= {_norm(k) for k in known}
    foreign = set(json.loads(foreign_path.read_text(encoding="utf-8")))
    have = set(by_id)

    seen, pool, pool_good = set(), 0, 0
    for f in glob.glob(str(items_dir / "fullcatalog_items_*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    it = json.loads(line)
                except ValueError:
                    continue
                g = str(it.get("goods_no"))
                if g in seen or g in have:
                    continue
                seen.add(g)
                t = (it.get("title") or "").strip()
                if not (16 <= len(t) <= 40):
                    continue
                b = (it.get("brand") or "").strip()
                if b in foreign:
                    continue
                if b and (b in known or _norm(b) in known):
                    pool += 1
                    if b in good:
                        pool_good += 1

    return {
        "편입분_검증": h_tot, "편입분_이름확정": h_named, "편입분_구매링크": h_link,
        "발굴분_검증": d_tot, "발굴분_이름확정": d_named, "발굴분_구매링크": d_link,
        "실적좋은브랜드": len(good), "실적나쁜브랜드": len(bad),
        "남은물량": pool, "그중_실적좋은브랜드": pool_good,
    }


def report(s: dict) -> str:
    def pct(a, b):
        return f"{a / b * 100:.1f}%" if b else "—"

    h_named = pct(s["편입분_이름확정"], s["편입분_검증"])
    d_named = pct(s["발굴분_이름확정"], s["발굴분_검증"])
    h_link = pct(s["편입분_구매링크"], s["편입분_검증"])
    d_link = pct(s["발굴분_구매링크"], s["발굴분_검증"])

    lines = [
        "수확본 편입 성과",
        "",
        f"  편입분 {s['편입분_검증']:,}건 검증 → 이름확정 {h_named} / 구매링크 {h_link}",
        f"  발굴분 {s['발굴분_검증']:,}건 검증 → 이름확정 {d_named} / 구매링크 {d_link}",
        "",
        f"  남은 물량 {s['남은물량']:,}건 "
        f"(실적 좋은 브랜드만 {s['그중_실적좋은브랜드']:,}건)",
        f"  실적 좋은 브랜드 {s['실적좋은브랜드']}개 / 나쁜 브랜드 {s['실적나쁜브랜드']}개",
    ]
    # 판단까지 적어 준다
    if s["편입분_검증"] >= 100 and s["발굴분_검증"] >= 100:
        hr = s["편입분_이름확정"] / s["편입분_검증"]
        dr = s["발굴분_이름확정"] / s["발굴분_검증"]
        if hr >= dr:
            lines += ["", f"  → 편입분이 발굴분보다 {(hr - dr) * 100:.1f}%p 잘 됩니다. "
                          "계속 옮겨도 됩니다."]
        else:
            lines += ["", f"  → 편입분이 발굴분보다 {(dr - hr) * 100:.1f}%p 못합니다. "
                          "좋은 것을 다 퍼냈을 수 있으니 회차당 물량을 줄이십시오."]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--verified-dir", required=True)
    ap.add_argument("--items-dir", required=True)
    ap.add_argument("--dict", required=True)
    ap.add_argument("--foreign", required=True)
    a = ap.parse_args()

    print(report(measure(Path(a.state), Path(a.verified_dir), Path(a.items_dir),
                         Path(a.dict), Path(a.foreign))))
