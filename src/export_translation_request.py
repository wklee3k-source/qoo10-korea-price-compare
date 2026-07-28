"""export_translation_request.py — 미번역 상품을 '그대로 붙여넣으면 되는'
마크다운 한 장으로 뽑는다.

[왜 만들었나] 기존 엑셀 왕복은 (1) 엑셀 다운로드 (2) 열 맞춰 붙여넣기
(3) 번역열 채우기 (4) 로컬 파이썬 실행 순서라, 번역 자체보다 앞뒤가
더 번거로웠다. 번역은 어차피 다른 Claude 창에서 하므로, 지시문까지
파일 안에 넣어두면 사용자는 **파일 전체를 복사해서 붙여넣기만** 하면 된다.

출력 형식은 `번호|일본어명` 한 줄짜리로 고정한다. 표(마크다운 테이블)로
주면 돌려받을 때 파이프와 정렬이 깨져서 파싱이 자주 실패한다.

사용법:
    python export_translation_request.py ../output/discovery_state.json \\
        ../output/번역요청.md [최대건수]
"""
import json
import re
import sys
from pathlib import Path

HANGUL_RE = re.compile(r"[가-힣]")

# 번역 지시문. 화장품 도메인에서 반복적으로 틀리는 것들을 명시한다 —
# 예전 API 번역에서 실제로 나왔던 오역들이다.
INSTRUCTION = """아래 표는 큐텐재팬에 올라온 한국 화장품의 일본어 상품명 목록입니다.
각 줄을 한국어로 번역해 주세요.

**규칙**
1. 출력은 `번호|한국어명` 형식 한 줄씩. 설명·인사·머리말 없이 목록만 주세요.
2. 번호는 입력과 똑같이 유지하세요. 순서를 바꾸거나 줄을 빼지 마세요.
3. **상품명에 있는 내용을 있는 그대로 전부 번역하세요.**
   프로모션 문구, 증정·세트 구성(1+1, 2+1), 배송 문구, 괄호 안 설명,
   기호까지 하나도 빼지 말고 원래 순서대로 옮기세요. 요약하거나
   정리하지 마세요.
4. 한국 제품이므로 제품명 부분은 **원래 한국어 이름을 복원**하세요.
   일본어를 직역하지 말고, 그 브랜드가 한국에서 실제로 쓰는 이름으로 쓰세요.
5. 브랜드명은 한국 표기를 쓰세요 (アヌア→아누아, メディキューブ→메디큐브).
6. 용량·수량(50ml, 2매입 등)은 그대로 두세요.
7. 확실하지 않으면 억지로 만들지 말고 그 줄은 `번호|` 로 비워 두세요.
   (빈 줄은 다음 회차에 다시 시도됩니다. 틀린 값이 들어가면 '번역완료'로
   굳어서 영영 고쳐지지 않으니, 지어내는 것보다 비우는 편이 낫습니다.)

**자주 틀리는 성분어**
- ドクダミ → 어성초 (○) / 삼백초 (×)
- ツボクサ → 병풀 (○)
- シカ / CICA → 시카 (○) / 사슴 (×)
- ヨモギ → 쑥
- コメ / 米 → 쌀
- ハトムギ → 율무
- 桃 / ピーチ → 복숭아
- 緑茶 → 녹차
"""


def export(state_path: str, out_path: str, limit: int | None = None) -> int:
    path = Path(state_path)
    if not path.exists():
        print(f"[SKIP] {path} 없음")
        return 0

    state = json.loads(path.read_text(encoding="utf-8"))
    products = state.get("all_products", [])
    pending = [p for p in products if not p.get("translated_kr")]
    total_pending = len(pending)
    if limit:
        pending = pending[:limit]

    print(f"[INFO] 전체 {len(products)}건 중 미번역 {total_pending}건")
    if not pending:
        print("[INFO] 미번역 상품 없음 — 번역요청 파일 생성 생략")
        # 남은 게 없으면 예전 파일을 지운다. 안 지우면 이미 끝난 목록을
        # 다시 번역하게 된다.
        out = Path(out_path)
        if out.exists():
            out.unlink()
            print(f"[INFO] 이전 {out.name} 삭제")
        return 0

    lines = [
        "# 번역 요청",
        "",
        f"미번역 {total_pending}건 중 {len(pending)}건. "
        "**이 파일 전체를 복사해서 다른 Claude 창에 붙여넣으세요.**",
        "",
        "---",
        "",
        INSTRUCTION,
        "",
        "**목록**",
        "",
        "```",
    ]
    index_map = {}
    for i, p in enumerate(pending, 1):
        title = (p.get("title") or "").replace("\n", " ").replace("|", "/").strip()
        lines.append(f"{i}|{title}")
        index_map[i] = p.get("goods_no")
    lines += [
        "```",
        "",
        "---",
        "",
        "<!-- 번호↔상품번호 대응표. 반영할 때 쓰므로 지우지 마세요. -->",
        "<!-- INDEX_MAP " + json.dumps(index_map, ensure_ascii=False) + " -->",
        "",
    ]

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    ja_only = sum(1 for p in pending if not HANGUL_RE.search(p.get("title") or ""))
    print(f"[OK] {out_path} 생성 — {len(pending)}건 (일본어만 {ja_only}건)")
    return len(pending)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    lim = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    export(sys.argv[1], sys.argv[2], lim)
