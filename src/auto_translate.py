"""
auto_translate.py — Claude Haiku 4.5 API를 이용해 큐텐 상품명(일본어)을
한글로 자동 번역한다. 그동안 사람이 직접 하나하나 번역하던 2단계를
자동화한다.

[핵심 설계] 화장품 도메인 특화 오역(예: ドクダミ→어성초 안 됨, シカ→사슴으로
오역)을 방지하기 위해, 시스템 프롬프트에 실측으로 확인된 용어 대응표를
명시한다. 여러 건을 한 번에 배치로 묶어서 API 호출 수를 줄인다(비용 절감 +
속도 향상).

사용법:
    python auto_translate.py <qoo10_products.json> <output.json> [batch_size]
        qoo10_products.json: [{"goods_no":..., "title":..., "brand":...}, ...]
        output.json: [{"goods_no":..., "translated_kr":..., "known_brand":...}, ...]
"""

import json
import os
import re
import sys
import time
import urllib.request

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """너는 큐텐재팬(일본 이커머스)의 한국 화장품 상품명을
정확한 한글로 번역하는 전문가다. 다음 원칙을 반드시 지켜라:

1. 브랜드명은 원문 그대로 유지하거나(영문 브랜드), 정확한 한글 정식표기로
   번역한다(예: ドクターフォーヘア→닥터포헤어).
2. 화장품 성분/타입 용어는 반드시 아래 대응표를 따른다(실측으로 확인된
   오역 방지용):
   ドクダミ=어성초, ツボクサ=병풀, シカ=시카(사슴 아님!), センテラ=센텔라,
   ヒアルロン酸=히알루론산, ナイアシンアミド=나이아신아마이드,
   コラーゲン=콜라겐, セラミド=세라마이드, レチノール=레티놀,
   トナー=토너, セラム=세럼, エッセンス=에센스, アンプル=앰플,
   クレンジング=클렌징, フォーム=폼, パック=팩, マスク=마스크
3. [매우 중요, 절대 준수] 원문에 있는 모든 내용을 하나도 빠짐없이
   번역한다 — 요약·축약·생략 절대 금지. "/"나 "・"로 구분된 여러
   구성품/부가설명(예: "スパチュラ付き"=스파츌라 포함, 성분명 나열,
   "韓国コスメ"=한국화장품 같은 프로모션 문구)도 전부 번역문에
   포함해야 한다. 번역문 길이가 원문보다 눈에 띄게 짧아지면 안 된다.
   실측 확인된 실패사례(절대 이렇게 하면 안 됨):
     원문: "モデリングクリームマスク 71g スパチュラ付き / ドクダミ
           復活草 保湿パック 密着パック 韓国コスメ X 2個"
     틀린 번역(뒷부분 생략됨): "모델링크림마스크 71g"
     올바른 번역: "모델링 크림 마스크 71g 스파츌라 포함 / 어성초
                   부활초 보습팩 밀착팩 한국화장품 X 2개"
4. 용량/수량/괄호안 정보는 원문 그대로 유지한다(숫자, ml, g, 개 등).
5. 번역 결과만 출력한다 — 설명, 주석, 따옴표 없이 번역문 한 줄만.

여러 상품이 번호로 주어지면, 각 번호에 대응하는 번역을 같은 번호로
줄바꿈해서 출력한다. 형식: "1. 번역결과\\n2. 번역결과\\n..." """


def _load_brand_dict() -> dict:
    try:
        d = json.load(open("../data/brand_translations_learned.json", encoding="utf-8"))
        d.pop("_설명", None)
        d.pop("_아도르_참고", None)
        return d
    except Exception:  # noqa: BLE001
        return {}


BRAND_DICT = _load_brand_dict()


def _build_system_prompt() -> str:
    """[비용문제 수정] 실측 확인: 1,630건 번역(약 109회 API 호출)에 $5~10이
    나갔다 — 매 호출마다 시스템 프롬프트를 처음부터 다시 전송했기 때문이다.
    Anthropic 프롬프트 캐싱을 적용하면 두 번째 호출부터 캐싱된 부분은
    최대 90% 할인되는데, 문제는 Haiku 4.5의 캐싱 최소기준이 4,096토큰
    이라는 것이다(Sonnet/Opus는 1,024토큰). 기존 시스템 프롬프트는 약
    500~700토큰뿐이라 cache_control을 붙여도 조용히 무시된다(API가 에러
    없이 그냥 캐싱을 안 함 — 실측 확인이 필요했던 부분).

    그래서 이미 갖고 있던 브랜드사전(972개, data/brand_translations_
    learned.json)을 시스템 프롬프트 안에 통째로 포함시킨다. 이러면:
    (1) 시스템 프롬프트가 4,096토큰을 확실히 넘어 캐싱이 실제로 작동하고,
    (2) 매번 아이템별로 브랜드 힌트를 개별 조립할 필요 없이 모델이
        항상 전체 브랜드 사전을 참고할 수 있어 번역 일관성도 좋아진다.
    패딩을 위한 낭비가 아니라, 실제로 유용한 내용을 채워서 기준을
    넘기는 것이다."""
    lines = [f"{jp}={kr}" for jp, kr in BRAND_DICT.items()]
    brand_table = "\n".join(lines)
    return (
        SYSTEM_PROMPT
        + "\n\n6. 아래는 실측으로 확인된 한국 화장품 브랜드명 대응표다(일본어"
        + "표기=정확한 한글 정식표기). 상품명에 이 목록의 브랜드가 나오면"
        + "반드시 이 표기를 그대로 쓴다:\n"
        + brand_table
    )


FULL_SYSTEM_PROMPT = _build_system_prompt()


def _call_api(user_content: str, max_tokens: int = 4000) -> str:
    """[중대버그 이력] max_tokens가 4000 고정이던 시절, translate_in_place가
    batch_size=len(titles)로 수천 건을 한 통에 보내는 바람에 응답이 약 80건
    분량에서 잘렸다. 잘린 뒤쪽은 아래 폴백 로직이 '일본어 원문 그대로'를
    translated_kr에 채워넣었고, 그 칸이 채워졌다는 이유로 재번역 대상에서도
    영구 제외됐다 — 실측 2,520건 중 2,035건(80.8%)이 일본어인 채로 굳었다.
    이제 (1) 배치를 잘게 쪼개고 (2) 배치 크기에 비례해 토큰을 잡고
    (3) 실패는 원문 폴백이 아니라 None으로 남겨 재시도되게 한다.

    [비용문제 수정] 1,630건 번역에 약 109회 호출이 나갔는데, 매번 이
    시스템 프롬프트(약 500토큰)를 처음부터 다시 통째로 보내고 있었다
    (프롬프트 캐싱 미적용). 실측 청구액이 예상보다 훨씬 커서(사용자
    확인: $5~10) 원인을 추적한 결과다. Anthropic 프롬프트 캐싱은 동일한
    프리픽스를 cache_control로 표시해두면, 두 번째 호출부터 그 부분은
    최대 90% 할인된 가격으로 읽는다. system 블록을 캐싱 대상으로
    표시한다 — 같은 프로세스 안에서 반복 호출될 때(번역 배치 109회처럼)
    비용이 크게 줄어든다."""
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": FULL_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user_content}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("anthropic-beta", "prompt-caching-2024-07-31")
    with urllib.request.urlopen(req, timeout=60) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data["content"][0]["text"]


KANA_RE = re.compile(r"[ぁ-んァ-ヶ]")
HANGUL_RE = re.compile(r"[가-힣]")
CJK_RE = re.compile(r"[一-龯]")
MIN_LENGTH_RATIO = 0.5  # 번역문이 원문의 이 비율보다 짧으면 생략으로 간주
MAX_BATCH_SIZE = 100    # [30->100 추가 확대] 검색으로 확인: Haiku 4.5의
                        # 실제 최대 출력 토큰은 64,000이다(8,000으로 캡을
                        # 걸어둔 건 실제 한도의 1/8에 불과했다). 배치를
                        # 100으로 늘려도 예상 출력(100*250+1000=26,000)이
                        # 여유있게 한도 안에 들어온다. 호출횟수가 30건
                        # 기준 대비 또 3분의1로 줄어 캐시읽기 오버헤드
                        # (매 호출 10%)와 왕복횟수가 그만큼 더 준다.
MAX_ATTEMPTS = 3        # 실패분 재시도 횟수(시도마다 배치를 절반으로 줄임)


def validate_translation(original: str, translated: str | None) -> tuple[bool, str]:
    """번역 결과 3중 검사. (통과여부, 사유)를 돌려준다.

    [1] 개수검사 — 애초에 결과가 없으면(번호 파싱 실패/응답 잘림) 탈락.
    [2] 글자검사 — 가나가 남아있거나 한글이 하나도 없으면 번역이 안 된 것.
    [3] 길이검사 — 원문 대비 절반 미만이면 뒷부분이 생략된 것.

    실패는 '원문 그대로 채우기'가 아니라 반드시 빈칸으로 남겨야 다음
    사이클에 재시도된다(과거 실패 #13 재발방지).
    """
    if not translated or not translated.strip():
        return False, "빈응답"

    t = translated.strip()

    if KANA_RE.search(t):
        return False, "일본어(가나)잔존"

    if not HANGUL_RE.search(t):
        # 원문이 영문/숫자뿐이면 한글이 없는 게 정상이다.
        if KANA_RE.search(original) or CJK_RE.search(original):
            return False, "한글없음"

    if len(t) < len(original.strip()) * MIN_LENGTH_RATIO:
        return False, f"길이부족({len(t)}/{len(original.strip())})"

    return True, "OK"


def translate_batch(items: list[dict], batch_size: int = MAX_BATCH_SIZE) -> list[str]:
    """[버그 발견] 기본값이 10으로 박혀있어서, MAX_BATCH_SIZE를 100으로
    올려도 translate_in_place.py처럼 batch_size를 명시 안 하고 부르면
    여전히 10건씩 처리되고 있었다(호출부 확인: translate_batch(items)
    — 인자 없이 호출). 기본값 자체를 MAX_BATCH_SIZE로 맞춰서, 별도로
    작게 지정하지 않는 한 항상 최대치로 배치를 묶게 한다."""
    """items: [{"title": ..., "brand": ...}, ...] 형태. brand_size씩 묶어서 번역한다.

    [핵심개선] 실측 확인된 문제: 브랜드사전(972개, 화해로 검증된 정확한
    한글명)이 있는데도, 번역 자체는 그걸 전혀 참고 안 하고 Haiku가 그냥
    발음대로 추측 번역해서 틀리는 경우가 있었다(예: "スキンアンドラブ"를
    이미 정확히 "스킨앤랩"으로 확인해뒀는데도, 번역결과는 "스킨앤러브"라는
    엉뚱한 발음번역이 나옴). 이제 원본 brand 필드가 사전에 있으면, 그
    정확한 한글명을 프롬프트에 직접 알려줘서 Haiku가 추측 대신 그대로
    쓰게 한다."""
    batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))
    results: list[str | None] = [None] * len(items)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        todo = [i for i, r in enumerate(results) if r is None]
        if not todo:
            break
        # 재시도는 배치를 더 잘게 쪼갠다(잘림이 원인이면 작게 보내면 살아난다).
        size = max(1, batch_size // (2 ** (attempt - 1)))
        print(f"  [번역 {attempt}차] 대상 {len(todo)}건, 배치 {size}건씩", file=sys.stderr)

        for i in range(0, len(todo), size):
            idxs = todo[i:i + size]
            chunk = [items[k] for k in idxs]
            lines = []
            for j, item in enumerate(chunk):
                brand = item.get("brand") or ""
                known_kr_brand = BRAND_DICT.get(brand)
                hint = f" [정확한 브랜드명: {known_kr_brand} — 반드시 이 표기 그대로 사용]" if known_kr_brand else ""
                lines.append(f"{j+1}. {item['title']}{hint}")
            prompt = f"다음 {len(chunk)}개 상품명을 번역하라:\n\n" + "\n".join(lines)

            try:
                # 응답 잘림 방지: 항목당 넉넉히 잡고 상한만 둔다.
                budget = min(20000, 250 * len(chunk) + 1000)
                response = _call_api(prompt, max_tokens=budget)
                parsed = {}
                for line in response.strip().split("\n"):
                    m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
                    if m:
                        parsed[int(m.group(1))] = m.group(2).strip()
            except Exception as e:  # noqa: BLE001
                print(f"    [배치번역 실패] {type(e).__name__}: {e}", file=sys.stderr)
                parsed = {}

            for j, k in enumerate(idxs):
                cand = parsed.get(j + 1)
                ok, reason = validate_translation(items[k]["title"], cand)
                if ok:
                    results[k] = cand
                elif attempt == MAX_ATTEMPTS:
                    # 끝까지 실패하면 원문으로 덮지 않고 None으로 남긴다.
                    print(f"    [번역포기-{reason}] {items[k]['title'][:40]}", file=sys.stderr)
            time.sleep(0.3)  # rate limit 여유

    fail = sum(1 for r in results if r is None)
    if fail:
        print(f"  [번역결과] 성공 {len(results)-fail}건 / 실패 {fail}건(빈칸으로 남겨 다음에 재시도)", file=sys.stderr)
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    products = json.loads(open(sys.argv[1], encoding="utf-8").read())
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    out_path = sys.argv[2]

    # 이어서 진행: 출력파일에 이미 있는 goods_no는 건너뛴다(타임아웃 대비)
    try:
        results = json.load(open(out_path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        results = []
    done_goods = {r["goods_no"] for r in results}
    remaining = [p for p in products if p["goods_no"] not in done_goods]
    print(f"[INFO] 전체 {len(products)}건 중 이미 처리된 {len(done_goods)}건부터 이어서 진행 ({len(remaining)}건 남음)", file=sys.stderr)

    # 남은 게 0건이어도(예: 신규 번역대상이 없는 경우) 결과파일은 반드시
    # 만들어둔다 — 안 그러면 이 파일을 여는 다음 스텝이 FileNotFoundError로
    # 죽는다(실측으로 확인된 버그).
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    for i in range(0, len(remaining), batch_size):
        chunk = remaining[i:i + batch_size]
        items = [{"title": p["title"], "brand": p.get("brand", "")} for p in chunk]
        translated = translate_batch(items, batch_size=batch_size)
        for p, t in zip(chunk, translated):
            if t is None:
                # 검증 탈락분은 아예 기록하지 않는다 — 기록해두면 done_goods에
                # 잡혀서 영영 재시도되지 않는다(과거 실패 #13의 정확한 재발경로).
                continue
            results.append({
                "goods_no": p["goods_no"],
                "translated_kr": t,
                "known_brand": p.get("known_brand", ""),
            })
        json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[진행] {len(results)}/{len(products)}건 완료 -> {out_path}", file=sys.stderr)

    print(f"[DONE] {len(results)}건 번역 완료 -> {out_path}", file=sys.stderr)
