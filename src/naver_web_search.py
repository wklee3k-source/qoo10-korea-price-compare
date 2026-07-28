"""naver_web_search.py — 네이버 웹문서 검색 API 래퍼.

[왜 넣었나] 네이버쇼핑 검색(naver_shop_search.py)은 쇼핑 DB만 본다.
그래서 쇼핑에 안 올라와 있거나 상품명이 조금 다른 경우를 통째로
놓친다. 웹문서 검색은 같은 자격증명(NAVER_CLIENT_ID/SECRET)으로
바로 쓸 수 있어서 추가 가입 없이 소스를 하나 늘릴 수 있다.

⚠️ 쿼터는 앱 단위로 하루 25,000회이고 쇼핑 검색과 공유한다.
검증 물량(하루 수백 건)에 비하면 충분하지만, 쇼핑 검색이 먼저
쿼터를 다 쓰면 이쪽도 같이 막힌다.

키: 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
"""
import json
import os
import sys
import urllib.parse
import urllib.request

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")


def search(query: str, num_results: int = 5) -> list[dict]:
    """웹문서 검색 결과를 [{title, url}] 형태로 돌려준다.

    자격증명이 없으면 빈 리스트(진짜 무결과와 동일 취급) — 예외를
    던지면 상품이 '보류'로 쌓여 검증이 멈춘다.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        return []

    params = urllib.parse.urlencode({"query": query, "display": max(1, min(num_results, 100))})
    url = f"https://openapi.naver.com/v1/search/webkr.json?{params}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            body = "(본문 읽기 실패)"
        raise urllib.error.HTTPError(
            e.url, e.code, f"{e.reason} | 응답본문: {body}", e.headers, None
        ) from None

    out = []
    for it in data.get("items", []):
        title = (it.get("title") or "").replace("<b>", "").replace("</b>", "")
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        if title:
            out.append({"title": title, "url": it.get("link")})
    return out


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["아누아 어성초 토너"]
    print(json.dumps({q: search(q) for q in queries}, ensure_ascii=False, indent=2))
