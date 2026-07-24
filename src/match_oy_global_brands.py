"""
match_oy_global_brands.py

화해로 못 찾은 나머지 한글 브랜드들을, 올리브영 글로벌 브랜드리스트
(영문명 2,120개)와 로마자변환+퍼지매칭으로 대조한다.

[정확도 관리] 순수 로마자변환은 부정확할 위험이 크므로(예: "그라운드랩"
academic 표준변환이 실제 브랜드표기 "GROUNDLAB"과 편집거리가 있음),
아래 3단계로 신뢰도를 관리한다:
  1. 로마자변환(academic) + 정규화(공백/특수문자 제거, 소문자화)
  2. 올리브영글로벌 2,120개 영문명과 편집거리 기반 유사도 매칭
  3. 유사도가 매우 높은(예: 0.90 이상) 것만 채택 — 애매한 건 버림
  4. 채택된 영문명을 큐텐 공식 브랜드리스트(English 컬럼)와 재대조해서
     일본어 원문을 확인 — 이 이중검증까지 통과해야 최종 확정
"""

import csv
import json
import re
import sys

from hangul_romanize import Transliter
from hangul_romanize.rule import academic
from rapidfuzz import fuzz, process

_trans = Transliter(academic)


def _normalize(s: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s


def match_brands(kr_brands: list[str], oy_global_brands: dict, threshold: float = 90.0) -> dict:
    """한글브랜드 -> 영문명(올리브영글로벌 기준) 매핑, 임계값 미달은 제외"""
    eng_names = list(oy_global_brands.values())
    normalized_eng = {_normalize(e): e for e in eng_names}
    choices = list(normalized_eng.keys())

    result = {}
    for kr in kr_brands:
        romanized = _normalize(_trans.translit(kr))
        if not romanized:
            continue
        match = process.extractOne(romanized, choices, scorer=fuzz.ratio)
        if match and match[1] >= threshold:
            matched_norm, score, _ = match
            eng_original = normalized_eng[matched_norm]
            result[kr] = {"english": eng_original, "score": score}
            print(f"{kr} -> {eng_original} (유사도 {score:.1f})")
    return result


def cross_reference_qoo10(matches: dict, qoo10_csv_path: str) -> dict:
    eng_to_japanese = {}
    with open(qoo10_csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eng = (row.get("English") or "").strip().lower()
            jp = (row.get("Japanese") or "").strip()
            if eng and jp:
                eng_to_japanese.setdefault(eng, jp)

    final = {}
    for kr, info in matches.items():
        jp = eng_to_japanese.get(info["english"].lower())
        if jp:
            final[jp] = kr
    return final


if __name__ == "__main__":
    kr_list_path = sys.argv[1]
    oy_global_path = sys.argv[2]
    out_path = sys.argv[3]
    threshold = float(sys.argv[4]) if len(sys.argv) > 4 else 90.0

    kr_brands = json.load(open(kr_list_path, encoding="utf-8"))
    oy_global = json.load(open(oy_global_path, encoding="utf-8"))

    matches = match_brands(kr_brands, oy_global, threshold)
    print(f"\n총 {len(matches)}개 로마자매칭 성공(임계값 {threshold} 이상)")

    final = cross_reference_qoo10(matches, "../data/brand_list.csv")
    print(f"큐텐 브랜드리스트 대조 후 최종 {len(final)}개 확정")

    json.dump(final, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
