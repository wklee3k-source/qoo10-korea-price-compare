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
3. 부가설명(효능, 프로모션 문구 등)도 전부 번역해서 포함한다 — 생략하지 않는다.
4. 용량/수량/괄호안 정보는 원문 그대로 유지한다(숫자, ml, g, 개 등).
5. 번역 결과만 출력한다 — 설명, 주석, 따옴표 없이 번역문 한 줄만.

여러 상품이 번호로 주어지면, 각 번호에 대응하는 번역을 같은 번호로
줄바꿈해서 출력한다. 형식: "1. 번역결과\\n2. 번역결과\\n..." """


def _call_api(user_content: str, max_tokens: int = 2000) -> str:
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    with urllib.request.urlopen(req, timeout=60) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data["content"][0]["text"]


def translate_batch(titles: list[str], batch_size: int = 10) -> list[str]:
    """titles를 batch_size씩 묶어서 번역한다."""
    results = []
    for i in range(0, len(titles), batch_size):
        chunk = titles[i:i + batch_size]
        numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(chunk))
        prompt = f"다음 {len(chunk)}개 상품명을 번역하라:\n\n{numbered}"
        try:
            response = _call_api(prompt)
            # "1. 번역\n2. 번역..." 형식 파싱
            lines = {}
            for line in response.strip().split("\n"):
                m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
                if m:
                    lines[int(m.group(1))] = m.group(2).strip()
            for j in range(len(chunk)):
                results.append(lines.get(j + 1, chunk[j]))  # 파싱 실패시 원문 그대로
        except Exception as e:  # noqa: BLE001
            print(f"    [배치번역 실패] {type(e).__name__}: {e}", file=sys.stderr)
            results.extend(chunk)  # 실패시 원문 그대로 폴백
        time.sleep(0.3)  # rate limit 여유
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    products = json.loads(open(sys.argv[1], encoding="utf-8").read())
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    titles = [p["title"] for p in products]
    print(f"[INFO] {len(titles)}건 번역 시작 (배치크기 {batch_size})", file=sys.stderr)
    translated = translate_batch(titles, batch_size)

    results = []
    for p, t in zip(products, translated):
        results.append({
            "goods_no": p["goods_no"],
            "translated_kr": t,
            "known_brand": p.get("known_brand", ""),
        })

    json.dump(results, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[DONE] {len(results)}건 번역 완료 -> {sys.argv[2]}", file=sys.stderr)
