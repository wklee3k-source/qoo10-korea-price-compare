"""fix_translation_terms.py — 번역본의 일본어 직역·표기 오류를 한국 표기로 고친다.

[왜 필요한가] 번역본(translated_kr)은 화면 표시용이 아니라 **검증 검색어**로
그대로 쓰인다. 일본어를 직역한 용어가 들어가면 한국 쇼핑몰에서 검색이
빗나가고, 그 상품은 구매링크 없음으로 버려진다.

실측(4,586건):
    미용액(美容液) 247건 · 화장수(化粧水) 151건 · 유액(乳液) 55건
    세안료(洗顔料) 26건  · 수징 68건       · 엑소솜 31건
한국에서 아무도 '미용액'이라 검색하지 않는다. '에센스'다.

띄어쓰기도 같은 문제다. 한국 상품명은 대부분 붙여 쓴다.
    '선 크림' 41건 · '토너 패드' 46건 · '헤어 오일' 43건

[고치지 않는 것] 한국에서도 정상으로 쓰는 말은 건드리지 않는다.
    두피(111) · 미백(65) · 모공 · 히알루론산(159) · 자외선 차단제(56)
'두피'를 '스칼프'로 바꾸면 오히려 검색이 나빠진다. 일본어처럼 보인다고
전부 바꾸면 안 된다 — 판단 기준은 '한국에서 그렇게 쓰는가'다.

사용법:
    python fix_translation_terms.py ../output/discovery_state.json [--dry-run]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# ① 일본어 직역·오표기 -> 한국 표기
TERM_FIXES: list[tuple[str, str]] = [
    ("미용액", "에센스"),
    ("화장수", "토너"),
    ("유액", "로션"),
    ("세안료", "클렌저"),
    ("수징", "수딩"),
    ("엑소솜", "엑소좀"),
    ("블레미시", "블레미쉬"),
    ("시트 마스크", "마스크팩"),
    ("시트마스크", "마스크팩"),
]

# ①-B 한국 표기 기준 교정. 매칭된 한국 상품명과 큐텐 번역본을 1,277쌍
#  대조해 뽑았다(같은 제품이 확실한 쌍만, 3회 이상 반복된 것만).
#  번역이 만든 표기가 한국 쇼핑몰 표기와 어긋나면 검색이 빗나간다.
KOREAN_SPELLING_FIXES: list[tuple[str, str]] = [
    ("프레시", "프레쉬"),
    ("배리어", "베리어"),
    ("글리콜릭", "글리코릭"),
    ("애씨드", "애시드"),
    ("스플래시", "스플래쉬"),
    ("에멀전", "에멀젼"),
    ("모이스처라이징", "모이스춰라이징"),
    ("데오도란트", "데오드란트"),
]

# ② 띄어쓰기 — 한국 상품명은 붙여 쓴다
SPACING_FIXES: list[tuple[str, str]] = [
    ("선 크림", "선크림"), ("선 스틱", "선스틱"), ("선 세럼", "선세럼"),
    ("선 쿠션", "선쿠션"), ("아이 크림", "아이크림"), ("젤 크림", "젤크림"),
    ("토너 패드", "토너패드"), ("마스크 팩", "마스크팩"),
    ("클렌징 폼", "클렌징폼"), ("클렌징 오일", "클렌징오일"),
    ("바디 로션", "바디로션"), ("바디 워시", "바디워시"),
    ("헤어 오일", "헤어오일"), ("헤어 에센스", "헤어에센스"),
]

ALL_FIXES = TERM_FIXES + KOREAN_SPELLING_FIXES + SPACING_FIXES


def fix_text(text: str) -> tuple[str, list[str]]:
    applied = []
    for before, after in ALL_FIXES:
        if before in text:
            text = text.replace(before, after)
            applied.append(f"{before}->{after}")
    return text, applied


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    if not path.exists():
        print(f"[중단] {path} 없음")
        return 1

    state = json.loads(path.read_text(encoding="utf-8"))
    products = state.get("all_products", [])
    counter: Counter = Counter()
    changed = 0
    samples = []
    for p in products:
        original = p.get("translated_kr") or ""
        if not original:
            continue
        fixed, applied = fix_text(original)
        if fixed == original:
            continue
        changed += 1
        counter.update(applied)
        if len(samples) < 8:
            samples.append((original, fixed))
        if not dry:
            p["translated_kr"] = fixed
            # [v7.17.0] 무엇을 바꿨는지 남긴다. 검수 화면에 표시돼야
            #  잘못 고친 것을 사람이 알아볼 수 있다.
            p["term_fixed"] = " · ".join(applied)

    print(f"[대상] 전체 {len(products):,}건 중 {changed:,}건 수정")
    for rule, n in counter.most_common():
        print(f"  {rule}: {n}건")
    print("\n[예시]")
    for before, after in samples:
        print(f"  전: {before[:56]}")
        print(f"  후: {after[:56]}")

    if dry:
        print("\n[모의실행] 파일을 쓰지 않았다")
        return 0
    if changed:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[저장] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
