"""
exa_search.py — Exa(exa.ai) 의미기반(semantic) 검색 API 래퍼.

[핵심 발견] 화해/네이버쇼핑은 순수 텍스트 매칭이라 번역이 조금만 틀려도
못 찾는데, Exa는 의미(semantic) 기반이라 오역이어도 원래 뜻을 이해해서
정답을 찾아준다. 실측: "디스인탱글"(제 오역) 검색 → 실제 정답인
"디스플린"(정식 제품 라인업명) 상품을 정확히 1등으로 찾아냄.
"""
import json
import os
import sys
import urllib.request

API_KEY = os.environ.get("EXA_API_KEY", "")


def search(query: str, num_results: int = 5) -> list[dict]:
    url = "https://api.exa.ai/search"
    payload = json.dumps({"query": query, "numResults": num_results}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("x-api-key", API_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # [v3.1.3] 예전엔 "HTTP Error 402: Payment Required"만 남아서 원인을
        # 알 수 없었다(키가 틀린 건지, 무료 크레딧이 떨어진 건지, 요금제
        # 문제인지). Exa는 응답 본문에 이유를 담아 보내므로 그것까지 붙인다.
        # 실측 2026-07-28: 402가 떠서 검증이 통째로 멈췄는데, 원인 파악에
        # 로그가 전혀 도움이 안 됐다.
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            body = "(본문 읽기 실패)"
        raise urllib.error.HTTPError(
            e.url, e.code, f"{e.reason} | 응답본문: {body}", e.headers, None
        ) from None
    return [
        {"title": r.get("title"), "url": r.get("url")}
        for r in data.get("results", [])
    ]


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["케라스타즈 디스인탱글 샴푸"]
    results = {}
    for q in queries:
        results[q] = search(q)
    print(json.dumps(results, ensure_ascii=False, indent=2))
