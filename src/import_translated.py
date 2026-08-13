"""
import_translated.py — 사용자가 번역해서 돌려준 엑셀을 통합본에 반영한다.

export_untranslated.py가 뽑은 엑셀의 '한글 상품명(번역)' 열을 채워서
주면, 큐텐상품번호(goods_no)로 맞춰 translated_kr에 넣는다.

[안전장치]
- 이미 번역된 항목은 건드리지 않는다(덮어쓰기 방지).
- 번역칸이 비었거나 일본어(가나)가 남아있으면 건너뛴다 — 잘못된 값이
  들어가면 그 상품은 "번역완료"로 취급돼 영영 재시도되지 않기 때문
  (과거 실패 #13과 같은 부류).

사용법:
    python import_translated.py <state.json> <번역완료.xlsx> [추가.xlsx ...]
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

KANA_RE = re.compile(r"[ぁ-んァ-ヶ]")
COL_GOODS = "큐텐상품번호"
COL_TRANS = "한글 상품명(번역)"


def load_translations(xlsx_paths: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    skipped_empty = skipped_kana = 0
    for xp in xlsx_paths:
        df = pd.read_excel(xp)
        if COL_GOODS not in df.columns or COL_TRANS not in df.columns:
            print(f"[SKIP] {xp}: 필요한 열이 없음({COL_GOODS}, {COL_TRANS})", file=sys.stderr)
            continue
        for _, row in df.iterrows():
            goods = str(row[COL_GOODS]).strip()
            trans = str(row[COL_TRANS]).strip()
            if not goods or goods.lower() == "nan":
                continue
            if not trans or trans.lower() == "nan":
                skipped_empty += 1
                continue
            if KANA_RE.search(trans):
                # 일본어가 남아있으면 번역이 안 된 것 — 넣으면 영영
                # "완료"로 굳어 재시도 대상에서 빠진다.
                print(f"    [건너뜀-일본어잔존] {goods}: {trans[:40]}", file=sys.stderr)
                skipped_kana += 1
                continue
            mapping[goods] = trans
    print(f"[INFO] 번역 {len(mapping)}건 로드 (빈칸 {skipped_empty}건, 일본어잔존 {skipped_kana}건 제외)")
    return mapping


def apply_to_state(state_path: str, mapping: dict[str, str]) -> int:
    path = Path(state_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    products = state.get("all_products", [])

    applied = 0
    for p in products:
        if p.get("translated_kr"):
            continue  # 이미 번역됨 — 덮어쓰지 않는다
        goods = str(p.get("goods_no"))
        if goods in mapping:
            p["translated_kr"] = mapping[goods]
            applied += 1

    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(products)
    done = sum(1 for p in products if p.get("translated_kr"))
    print(f"[DONE] {applied}건 반영 -> 번역 {done}/{total} (남은 {total - done})")
    return applied


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    apply_to_state(sys.argv[1], load_translations(sys.argv[2:]))
