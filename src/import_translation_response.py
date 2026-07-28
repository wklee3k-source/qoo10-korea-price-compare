"""import_translation_response.py — 다른 Claude 창에서 받은 `번호|한국어명`
블록을 통합본에 반영한다.

[안전장치 3가지 — import_translated.py와 동일한 원칙]
1. 이미 번역된 항목은 덮어쓰지 않는다.
2. 빈칸은 건너뛴다(다음 회차에 다시 시도되게).
3. 가나(ひらがな/カタカナ)가 남아있으면 건너뛴다 — 번역이 덜 된 값이
   들어가면 그 상품이 '번역완료'로 굳어 영영 재시도되지 않는다.

[번호↔상품번호 대응] 번역요청.md 끝의 `<!-- INDEX_MAP {...} -->` 주석을
읽어서 번호를 상품번호로 되돌린다. 응답에 있는 번호를 그대로 믿고
통합본의 N번째 항목에 넣으면, 그 사이 통합이 한 번 더 돌아 순서가
바뀌었을 때 엉뚱한 상품에 이름이 박힌다.

사용법:
    python import_translation_response.py ../output/discovery_state.json \\
        ../output/번역요청.md 응답.txt
"""
import json
import re
import sys
from pathlib import Path

KANA_RE = re.compile(r"[ぁ-んァ-ヴ]")
LINE_RE = re.compile(r"^\s*(\d{4,})\s*\|\s*(.*?)\s*$")
INDEX_MAP_RE = re.compile(r"<!--\s*INDEX_MAP\s*(\{.*?\})\s*-->", re.S)


def load_index_map(request_path: str) -> dict[int, str]:
    text = Path(request_path).read_text(encoding="utf-8")
    m = INDEX_MAP_RE.search(text)
    if not m:
        raise SystemExit(f"[중단] {request_path} 에서 INDEX_MAP 주석을 못 찾음")
    return {int(k): v for k, v in json.loads(m.group(1)).items()}


def parse_response(response_path: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for raw in Path(response_path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("```") or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def apply(state_path: str, request_path: str | None, response_path: str) -> int:
    # [v3.5.1] 응답의 키는 상품번호 그 자체다. 요청서를 안 넘겨도 반영된다
    # — 요청서가 새로 생성돼 사라져도 손에 든 응답만으로 처리할 수 있다.
    index_map = load_index_map(request_path) if request_path else {}
    answers = parse_response(response_path)
    print(f"[INFO] 요청 {len(index_map)}건 / 응답 파싱 {len(answers)}건")

    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    by_goods = {str(p.get("goods_no")): p for p in state.get("all_products", [])}

    applied = skipped_empty = skipped_kana = skipped_done = missing = 0
    for num, korean in answers.items():
        # 상품번호로 바로 찾고, 못 찾으면 옛 순번 방식으로 한 번 더 시도한다.
        goods_no = str(num) if str(num) in by_goods else index_map.get(num)
        if goods_no is None:
            missing += 1
            continue
        product = by_goods.get(str(goods_no))
        if product is None:
            missing += 1
            continue
        if product.get("translated_kr"):
            skipped_done += 1
            continue
        if not korean:
            skipped_empty += 1
            continue
        if KANA_RE.search(korean):
            print(f"  [건너뜀-가나잔존] {num}: {korean}")
            skipped_kana += 1
            continue
        product["translated_kr"] = korean
        applied += 1

    Path(state_path).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[완료] 반영 {applied}건 | 빈칸 {skipped_empty} | 가나잔존 {skipped_kana} "
          f"| 이미번역 {skipped_done} | 대응없음 {missing}")
    remaining = sum(1 for p in state.get("all_products", []) if not p.get("translated_kr"))
    print(f"[남은 미번역] {remaining}건")
    return applied


if __name__ == "__main__":
    if len(sys.argv) == 3:          # state, 응답  (요청서 없이)
        apply(sys.argv[1], None, sys.argv[2])
    elif len(sys.argv) >= 4:        # state, 요청서, 응답
        apply(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        raise SystemExit(1)
