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
INSTRUCTION = """아래는 큐텐재팬에 올라온 **한국 화장품**의 일본어 상품명 목록입니다.
각 줄을 한국어 상품명으로 옮겨 주세요.

**이 번역이 어디에 쓰이는지 알고 시작해 주세요**
번역 결과는 화면에 보여주려는 게 아니라, **네이버 쇼핑에서 같은 상품을
찾는 검색어**로 그대로 들어갑니다. 그래서 "일본어를 한국어로 옮긴 말"이
아니라 **"한국 쇼핑몰에 실제로 그렇게 적혀 있는 이름"**이어야 합니다.
매끄러운 번역보다 실제 표기가 우선입니다.

**규칙**
1. 출력은 `상품번호|한국어명` 형식 한 줄씩. 설명·인사·머리말 없이 목록만.
2. 맨 앞 상품번호(10자리 숫자)는 **한 글자도 바꾸지 말고** 그대로.
   순서를 바꾸거나 줄을 빼지 마세요.
3. **있는 그대로 전부 옮기세요.** 프로모션 문구, 증정·세트 구성(1+1, 2+1),
   배송 문구, 괄호 안 설명, 기호까지 빼지 말고 원래 순서대로. 요약 금지.
4. 제품명은 **한국에서 실제로 쓰는 이름을 복원**하세요. 직역하지 마세요.
5. 브랜드명은 한국 공식 표기로 (アヌア→아누아, メディキューブ→메디큐브).
6. 용량·수량(50ml, 2매입)은 그대로.
7. **라인명·번호·색상·제형을 절대 바꾸거나 빼지 마세요.** 같은 브랜드
   안에서 이것만 다른 제품이 많아, 하나만 틀려도 다른 상품이 됩니다.
       5번 글루타치온 ≠ 1번 판토텐산
       화이트 블론드 ≠ 퍼플
       에센스 ≠ 크림 ≠ 젤크림 ≠ 밤
8. 확실하지 않으면 지어내지 말고 `번호|` 로 비워 두세요.
   빈 줄은 다음 회차에 다시 시도됩니다. 틀린 값이 들어가면 '번역완료'로
   굳어 영영 고쳐지지 않으니, 비우는 편이 낫습니다.

**카테고리 용어 — 일본식 한자어를 쓰지 마세요**
- 美容液 → 에센스 (○) / 미용액 (×)
- 化粧水 → 토너 (○) / 화장수 (×)
- 乳液 → 로션 (○) / 유액 (×)
- 洗顔料 → 클렌저 · 클렌징폼 (○) / 세안료 (×)
- 日焼け止め → 선크림 (○)
- シートマスク → 마스크팩 (○) / 시트 마스크 (×)
- スージング → 수딩 (○) / 수징 (×)
- エクソソーム → 엑소좀 (○) / 엑소솜 (×)
- ブレミッシュ → 블레미쉬 (○) / 블레미시 (×)
- 두피 · 미백 · 모공 · 히알루론산 · 자외선 차단제는 그대로
  (한국에서도 그렇게 씁니다. 억지로 바꾸지 마세요)

**붙여 쓰는 말 — 한국 상품명은 대부분 붙여 씁니다**
선크림 · 선스틱 · 선세럼 · 선쿠션 · 아이크림 · 젤크림 · 수분크림
토너패드 · 마스크팩 · 클렌징폼 · 클렌징오일 · 클렌징워터
바디로션 · 바디워시 · 바디크림 · 헤어오일 · 헤어에센스 · 헤어팩

**자주 나오는 말**
- ドクダミ → 어성초 (○) / 삼백초 (×)
- ツボクサ → 병풀,  シカ / CICA → 시카 (○) / 사슴 (×)
- ヨモギ → 쑥,  コメ / 米 → 쌀,  ハトムギ → 율무
- 桃 / ピーチ → 복숭아,  緑茶 → 녹차,  緑豆 → 녹두
- ヒアルロン酸 → 히알루론산,  セラミド → 세라마이드
- ナイアシンアミド → 나이아신아마이드,  グルタチオン → 글루타치온
- コラーゲン → 콜라겐,  レチノール → 레티놀,  ペプチド → 펩타이드
- ニキビ → 트러블 (○) / 여드름도 가능,  トーンアップ → 톤업
- レフィル → 리필,  アンプル → 앰플,  セラム → 세럼
- エイジングケア → 안티에이징,  ダメージケア → 데미지케어
"""



def export(state_path: str, out_path: str, limit: int | None = None,
           chunk: int = 200) -> int:
    """미번역 목록을 chunk건씩 잘라 여러 장으로 뽑는다.

    [왜 자르나] 500줄을 한 장으로 주면 입력은 문제없지만(약 32k 토큰)
    **응답이 27k 토큰**이 된다. 이 길이는 한 번의 답변에서 잘리거나
    중간부터 번호가 어긋나기 쉽다. 200줄이면 응답이 약 11k 토큰이라
    안전하고, 중간에 실패해도 그 장만 다시 하면 된다.
    """
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

    out = Path(out_path)
    stem, suffix = out.stem, out.suffix or ".md"
    # 이전 회차 파일을 먼저 지운다 — 안 지우면 이미 끝난 목록이 남아
    # 다시 번역하게 되고, 장수가 줄었을 때 옛 뒷장이 유령처럼 남는다.
    for old_file in out.parent.glob(f"{stem}*{suffix}"):
        old_file.unlink()

    if not pending:
        print("[INFO] 미번역 상품 없음 — 번역요청 파일 생성 생략")
        return 0

    chunks = [pending[i:i + chunk] for i in range(0, len(pending), chunk)]
    n_files = len(chunks)
    base_no = 0
    for idx, part in enumerate(chunks, 1):
        lines = [
            f"# 번역 요청 {idx}/{n_files}",
            "",
            f"미번역 {total_pending}건 중 이 장은 {len(part)}건. "
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
        for i, p in enumerate(part, base_no + 1):
            title = (p.get("title") or "").replace("\n", " ").replace("|", "/").strip()
            # [v3.5.1] 키를 순번이 아니라 상품번호로 쓴다. 순번을 쓰면,
            # 사용자가 번역하는 동안 통합이 한 번 더 돌아 요청서가
            # 새로 만들어졌을 때 번호가 밀려 엉뚱한 상품에 이름이 박힌다
            # (안전망 통합이 4시간마다 도는 운영에서는 실제로 일어난다).
            lines.append(f"{p.get('goods_no')}|{title}")
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
        name = out.parent / (f"{stem}_{idx:02d}{suffix}" if n_files > 1 else f"{stem}{suffix}")
        name.write_text("\n".join(lines), encoding="utf-8")
        print(f"[OK] {name.name} — {len(part)}건")
        base_no += len(part)

    ja_only = sum(1 for p in pending if not HANGUL_RE.search(p.get("title") or ""))
    print(f"[완료] {n_files}장 / 총 {len(pending)}건 (일본어만 {ja_only}건)")
    return len(pending)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    lim = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    ch = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].strip() else 200
    export(sys.argv[1], sys.argv[2], lim, ch)
