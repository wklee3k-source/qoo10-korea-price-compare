"""learn_from_decisions.py — 검수페이지에서 사람이 확정한 결과를 사전으로 되먹인다.

[배경] 검수페이지에서 사진을 고르면 그게 '이 큐텐 상품 = 이 한국 상품'이라는
확정이고, 결과가 comparison/decisions/*.json 으로 저장된다. 그런데 지금까지
그 파일을 아무도 읽지 않았다 — 매일의 판단이 쌓이기만 하고 파이프라인에
반영되지 않았다.

확정 1건에서 두 가지를 뽑는다.

1) 브랜드 대응 (data/brand_translations_learned.json)
   큐텐 브랜드(일본어) ↔ 확정된 한국 상품의 브랜드.
   실측 2026-07-28 기준 이 사전의 커버리지는 상품 기준 38.6%뿐이다.
   미등록 1,379종을 검수하면서 자동으로 채운다.

2) 표기 변형 (data/name_alias_learned.json)
   같은 상품인데 소스마다 다르게 쓰는 말.
       화해  : 화이트샷 세럼 유브이
       네이버: POLA 폴라 화이트 샷 세럼 UV
       → 유브이 = UV
   이름 유사도로 오매칭을 걸러내려 할 때, 이 변형을 모르면 멀쩡한 매칭을
   잘못 버린다(실측: 단어겹침만 쓰면 오탐 21%). 규칙을 추측하는 대신
   사람이 확정한 짝에서 뽑아낸다.

[안전장치]
- 확정(match_confirmed)이고 제외되지 않은 건만 쓴다.
- 이미 사전에 있는 항목은 덮어쓰지 않는다(사람이 손으로 고친 값 보호).
- 표기 변형은 '나머지가 거의 다 일치하는데 딱 한 토큰씩만 다를 때'만
  받는다. 느슨하게 받으면 서로 무관한 단어끼리 짝지어져 사전이 오염되고,
  그 오염이 이후 모든 판정에 퍼진다.

사용법:
    python learn_from_decisions.py \\
        --decisions ../comparison/decisions --decisions ../output/review \\
        --discovery ../output/discovery_state.json \\
        --verified ../output/hwahae_verified_39.json \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
from pathlib import Path

HANGUL_RE = re.compile(r"[가-힣]")
KANA_RE = re.compile(r"[ぁ-んァ-ヴ]")
TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")

# 제품명에 흔히 붙는 잡음 — 변형 추출에서 제외한다.
NOISE_TOKENS = {
    "정품", "본품", "세트", "대용량", "공식", "무료배송", "리필", "증정", "단독",
    "신상", "인기", "한국", "매", "장", "개", "종", "ml", "g", "기획", "특가",
    "할인", "쿠폰", "사은품", "택1", "선택",
}


def load_decisions(dirs: list[str]) -> list[dict]:
    rows: list[dict] = []
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            if path.endswith("_used.json"):
                continue
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"  [건너뜀] {path}: {e}")
                continue
            if isinstance(data, list):
                rows.extend(data)
                print(f"  [읽음] {os.path.basename(path)} {len(data)}건")
    return rows


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text or "") if t.lower() not in NOISE_TOKENS]


def learn_brands(confirmed: list[dict], products: dict, verified: dict,
                 brand_dict: dict) -> dict:
    """큐텐 브랜드(일본어) -> 한글 브랜드."""
    added: dict[str, str] = {}
    for row in confirmed:
        gno = str(row.get("goods_no"))
        # 큐텐 브랜드에는 &amp; 같은 HTML 엔티티가 그대로 들어있다.
        jp_brand = html.unescape(((products.get(gno) or {}).get("brand") or "")).strip()
        kr_brand = ((verified.get(gno) or {}).get("brand") or "").strip()
        # 한국 브랜드는 "히스토랩 (HISTOLAB)"처럼 괄호에 영문을 달고 오는
        # 경우가 많다. 사전에는 한글 표기만 남긴다.
        kr_brand = re.sub(r"\s*[\(（][^)）]*[\)）]\s*", " ", kr_brand).strip()
        if not jp_brand or not kr_brand:
            continue
        if not HANGUL_RE.search(kr_brand):
            continue          # 한글이 아니면 대응값으로 쓸 수 없다
        if KANA_RE.search(kr_brand):
            continue          # 번역이 덜 된 값
        if jp_brand in brand_dict or jp_brand in added:
            continue          # 이미 있으면 손대지 않는다
        added[jp_brand] = kr_brand
    return added


def learn_aliases(confirmed: list[dict], products: dict, alias_dict: dict) -> dict:
    """같은 상품의 두 이름에서 '딱 한 토큰씩만 다른' 쌍을 뽑는다."""
    added: dict[str, str] = {}
    for row in confirmed:
        gno = str(row.get("goods_no"))
        left = (row.get("qoo10_name_final") or row.get("qoo10_name_kr")
                or (products.get(gno) or {}).get("translated_kr") or "")
        right = row.get("kr_name") or ""
        if not left or not right:
            continue

        lt, rt = tokens(left), tokens(right)
        lset, rset = {t.lower() for t in lt}, {t.lower() for t in rt}
        common = lset & rset
        # 나머지가 충분히 겹쳐야 '같은 상품의 다른 표기'라고 볼 수 있다.
        if not common or len(common) / max(1, min(len(lset), len(rset))) < 0.6:
            continue
        l_only = [t for t in lt if t.lower() not in common]
        r_only = [t for t in rt if t.lower() not in common]
        # 딱 하나씩만 남았을 때만 짝으로 인정한다. 둘 이상이면 어느 것과
        # 어느 것이 짝인지 알 수 없고, 잘못 짝지으면 사전이 오염된다.
        if len(l_only) != 1 or len(r_only) != 1:
            continue
        a, b = l_only[0], r_only[0]
        if a.lower() == b.lower() or a.isdigit() or b.isdigit():
            continue
        key = f"{a}|{b}"
        if key in alias_dict or key in added:
            continue
        added[key] = {"a": a, "b": b, "goods_no": gno}
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", action="append", required=True)
    ap.add_argument("--discovery", required=True)
    ap.add_argument("--verified", required=True)
    ap.add_argument("--brand-dict", default="../data/brand_translations_learned.json")
    ap.add_argument("--alias-dict", default="../data/name_alias_learned.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("[검수 결정 읽기]")
    rows = load_decisions(args.decisions)
    confirmed = [r for r in rows if r.get("match_confirmed") and not r.get("excluded")]
    print(f"  전체 {len(rows)}건 중 확정 {len(confirmed)}건")
    if not confirmed:
        print("[종료] 확정된 결정이 없다")
        return 0

    products = {}
    p = Path(args.discovery)
    if p.exists():
        for item in json.loads(p.read_text(encoding="utf-8")).get("all_products", []):
            products[str(item.get("goods_no"))] = item
    verified = {}
    v = Path(args.verified)
    if v.exists():
        for item in json.loads(v.read_text(encoding="utf-8")):
            verified[str(item.get("goods_no"))] = item
    print(f"  대조자료: 발굴 {len(products):,}건 / 검증 {len(verified):,}건")

    bpath, apath = Path(args.brand_dict), Path(args.alias_dict)
    brand_dict = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() else {}
    alias_dict = json.loads(apath.read_text(encoding="utf-8")) if apath.exists() else {}

    new_brands = learn_brands(confirmed, products, verified, brand_dict)
    new_alias = learn_aliases(confirmed, products, alias_dict)

    print(f"\n[브랜드 대응] 신규 {len(new_brands)}건")
    for k, v2 in list(new_brands.items())[:8]:
        print(f"  {k} → {v2}")
    print(f"[표기 변형] 신규 {len(new_alias)}건")
    for k, v2 in list(new_alias.items())[:8]:
        print(f"  {v2['a']} = {v2['b']}")

    if args.dry_run:
        print("\n[모의실행] 파일을 쓰지 않았다")
        return 0

    if new_brands:
        brand_dict.update(new_brands)
        bpath.write_text(json.dumps(brand_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[저장] {bpath.name} — 총 {len(brand_dict)}개")
    if new_alias:
        alias_dict.update(new_alias)
        apath.write_text(json.dumps(alias_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[저장] {apath.name} — 총 {len(alias_dict)}개")
    if not new_brands and not new_alias:
        print("\n[변경 없음] 새로 배울 것이 없다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
