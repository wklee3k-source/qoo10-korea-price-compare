"""
hwahae_brand_lookup.py

올리브영 등에서 확보한 한글 브랜드명 리스트를 화해(hwahae.co.kr)에서
하나씩 검색해서, 화해가 갖고 있는 정확한 "브랜드명 (English)" 표기를
가져온다. 그 영문표기를 큐텐 공식 브랜드리스트(data/brand_list.csv,
41,511개, Japanese/English 컬럼)와 대조해서, 큐텐 원본 brand 필드(일본어)를
알아내 data/brand_translations_learned.json에 채운다.

이렇게 하면 "이미 발굴된 상품과 우연히 겹쳐야만 매칭되는" 기존 방식보다
훨씬 넓은 커버리지를 얻을 수 있다 — 화해 검색만으로 영문표기를 확보하고,
그걸 큐텐 브랜드 마스터DB와 직접 대조하기 때문에 발굴 여부와 무관하게
매칭이 가능하다.

사용법:
    python hwahae_brand_lookup.py <한글브랜드목록.json> <출력.json>
"""

import csv
import json
import re
import sys
import time

sys.path.insert(0, ".")
from hwahae_name_corrector import _fetch_search_page, _parse_products  # noqa: E402

BRAND_PAREN_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")


def lookup_brands(kr_brand_list: list[str]) -> dict:
    """각 한글 브랜드명 -> 화해가 반환한 영문표기 매핑"""
    result = {}
    for i, kr in enumerate(kr_brand_list):
        try:
            html = _fetch_search_page(kr, wait_seconds=1.5)
            products = _parse_products(html)
        except Exception as e:  # noqa: BLE001
            print(f"[{i+1}/{len(kr_brand_list)}] {kr}: 오류 {type(e).__name__}")
            continue
        if not products:
            print(f"[{i+1}/{len(kr_brand_list)}] {kr}: 검색결과없음")
            continue
        brand_field = products[0].get("brand") or ""
        m = BRAND_PAREN_RE.match(brand_field)
        if m and kr in m.group(1):
            eng = m.group(2).strip()
            result[kr] = eng
            print(f"[{i+1}/{len(kr_brand_list)}] {kr} -> {eng}")
        else:
            print(f"[{i+1}/{len(kr_brand_list)}] {kr}: 브랜드불일치({brand_field})")
        time.sleep(0.3)
    return result


def cross_reference_qoo10(kr_to_eng: dict, qoo10_csv_path: str) -> dict:
    """영문표기를 큐텐 공식 브랜드리스트와 대조해서 일본어 원문을 알아낸다."""
    eng_to_japanese = {}
    with open(qoo10_csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eng = (row.get("English") or "").strip().lower()
            jp = (row.get("Japanese") or "").strip()
            if eng and jp:
                eng_to_japanese.setdefault(eng, jp)

    new_mappings = {}
    for kr, eng in kr_to_eng.items():
        jp = eng_to_japanese.get(eng.lower())
        if jp:
            new_mappings[jp] = kr
    return new_mappings


if __name__ == "__main__":
    pending_path = sys.argv[1]
    out_path = sys.argv[2]
    chunk_size = int(sys.argv[3]) if len(sys.argv) > 3 else 400

    all_pending = json.load(open(pending_path, encoding="utf-8"))
    kr_list = all_pending[:chunk_size]
    remaining = all_pending[chunk_size:]
    print(f"이번 실행: {len(kr_list)}개 처리, {len(remaining)}개는 다음으로 이월")

    kr_to_eng = lookup_brands(kr_list)
    print(f"\n총 {len(kr_to_eng)}개 화해 매칭 성공")

    new_mappings = cross_reference_qoo10(kr_to_eng, "../data/brand_list.csv")
    print(f"큐텐 브랜드리스트 대조 후 최종 {len(new_mappings)}개 매핑 확보")

    json.dump(new_mappings, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 이번에 시도한 것들은 성공/실패 여부와 무관하게 pending에서 제거(중복시도 방지).
    # 실패한 건(화해에 없거나 매칭 안 된 것)은 애초에 화해에 없는 브랜드일
    # 가능성이 높으므로 다시 시도해도 결과가 같을 것이다.
    json.dump(remaining, open(pending_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
