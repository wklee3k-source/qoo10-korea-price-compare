"""daum_search.py — 카카오 다음(Daum) 웹문서 검색 API 래퍼.

[왜 넣었나] Exa는 무료 월 크레딧이 $10(약 1,428건)뿐이라 며칠 만에
소진되고 402로 검증이 통째로 멈췄다(실측 2026-07-28). 다음 웹문서
검색은 일 30,000건이 무료라 이 파이프라인 물량(잔여 2,687건)에는
사실상 제한이 없는 수준이다.

[Exa와의 차이] Exa는 의미기반이라 오역된 이름으로도 정답을 찾아주지만,
다음은 키워드 매칭이다. 서로 대체재가 아니라 보완재로 쓴다.

키: 환경변수 KAKAO_REST_API_KEY (카카오디벨로퍼스 > 앱 > REST API 키)
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")


def search(query: str, num_results: int = 5) -> list[dict]:
    """웹문서 검색 결과를 [{title, url}] 형태로 돌려준다.

    키가 없으면 빈 리스트를 돌려준다 — 예외를 던지면 호출부가 이걸
    '기술적 실패'로 보고 상품을 보류시켜, 키를 안 넣은 것만으로
    검증이 멈춰버린다(Exa 402 사고와 같은 부류).
    """
    if not API_KEY:
        return []

    params = urllib.parse.urlencode({"query": query, "size": max(1, min(num_results, 50))})
    url = f"https://dapi.kakao.com/v2/search/web?{params}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"KakaoAK {API_KEY}")

    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # [v3.1.3과 동일 원칙] 원인을 로그에서 바로 알 수 있게 본문을 붙인다.
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            body = "(본문 읽기 실패)"
        raise urllib.error.HTTPError(
            e.url, e.code, f"{e.reason} | 응답본문: {body}", e.headers, None
        ) from None

    out = []
    for doc in data.get("documents", []):
        # 다음은 검색어 하이라이트를 <b> 태그로 넣어준다 — 제거한다.
        title = (doc.get("title") or "").replace("<b>", "").replace("</b>", "")
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        if title:
            out.append({"title": title, "url": doc.get("url")})
    return out


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["아누아 어성초 토너"]
    print(json.dumps({q: search(q) for q in queries}, ensure_ascii=False, indent=2))
