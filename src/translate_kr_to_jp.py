"""
translate_kr_to_jp.py — 검증완료된 한글 상품명(구매처 원본)을 일본어로
번역해서, 검수페이지에서 "한글 상품명 아래에 일본어 번역"을 보여줄 수
있게 한다. auto_translate.py(일→한)와 대칭되는 한→일 버전.

사용법:
    python translate_kr_to_jp.py <hwahae_verified.json> <output.json>
        output.json: {"goods_no": "일본어번역", ...}
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

SYSTEM_PROMPT = """너는 한국 화장품 상품명을 정확한 일본어로 번역하는
전문가다. 브랜드명은 가타카나 표기를 살리고, 성분/제품유형 용어는 일본
화장품 시장에서 실제로 쓰이는 표현을 사용해라. 부가설명도 생략하지 말고
전부 번역해라. 번역 결과만 출력한다 — 설명, 주석 없이.

여러 상품이 번호로 주어지면, 각 번호에 대응하는 번역을 같은 번호로
줄바꿈해서 출력한다. 형식: "1. 번역결과\\n2. 번역결과\\n..." """


def _call_api(user_content: str, max_tokens: int = 4000) -> str:
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


def translate_batch(names: list[str], batch_size: int = 10) -> list[str]:
    results = []
    for i in range(0, len(names), batch_size):
        chunk = names[i:i + batch_size]
        numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(chunk))
        prompt = f"다음 {len(chunk)}개 한글 상품명을 일본어로 번역하라:\n\n{numbered}"
        try:
            response = _call_api(prompt)
            parsed = {}
            for line in response.strip().split("\n"):
                m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
                if m:
                    parsed[int(m.group(1))] = m.group(2).strip()
            for j in range(len(chunk)):
                results.append(parsed.get(j + 1, ""))
        except Exception as e:  # noqa: BLE001
            print(f"    [배치번역 실패] {type(e).__name__}: {e}", file=sys.stderr)
            results.extend([""] * len(chunk))
        time.sleep(0.3)
    return results


if __name__ == "__main__":
    verified = json.loads(open(sys.argv[1], encoding="utf-8").read())
    out_path = sys.argv[2]

    try:
        results = json.load(open(out_path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        results = {}

    # 성공(구매링크확보)한 항목만 대상 — 실패건은 화면에 안 나오니 번역 불필요
    targets = [x for x in verified if x.get("product_url") and x["goods_no"] not in results]
    print(f"[INFO] 전체 {len(verified)}건 중 신규 번역대상 {len(targets)}건", file=sys.stderr)

    batch_size = 10
    for i in range(0, len(targets), batch_size):
        chunk = targets[i:i + batch_size]
        names = [x.get("name") or x.get("translated_kr") or "" for x in chunk]
        translated = translate_batch(names, batch_size=batch_size)
        for x, t in zip(chunk, translated):
            results[x["goods_no"]] = t
        json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  [{i+len(chunk)}/{len(targets)}] 저장완료", file=sys.stderr)

    print(f"[완료] 총 {len(results)}건 번역 완료", file=sys.stderr)
