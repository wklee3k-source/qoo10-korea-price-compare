"""naver_web_search.py — 네이버 웹문서 검색 API 래퍼.

[왜 넣었나] 네이버쇼핑 검색은 쇼핑 DB만 본다. 그래서 쇼핑에 안 올라와
있거나 상품명이 조금 다른 경우를 통째로 놓친다. 웹문서 검색은 그런
경우를 잡아준다.

[v7.38.0 이관 대응]
네이버가 검색 API를 NAVER API HUB(네이버 클라우드 플랫폼)로 이관했다.
웹문서 검색은 **이관 대상**이라 계속 쓸 수 있다(쇼핑 검색은 이관에서
제외돼 2026-07-31 영구 종료됐다 — naver_shop_search.py 참고).

    구분        기존(개발자센터)                  신규(API HUB)
    엔드포인트  openapi.naver.com/v1/search/webkr.json
                -> naverapihub.apigw.ntruss.com/search/v1/webkr (경로 순서가 다름)
    인증헤더    X-Naver-Client-Id / -Secret       X-NCP-APIGW-API-KEY-ID / -KEY
    계정        네이버 계정                       NCP 계정
    호출한도    앱당 하루 25,000회                검색 카테고리 통합 월 775,000회
                                                  (API Key당 50 RPS)

기존 키는 2027-06-30 까지만 동작한다. 그 전에 이관을 마쳐야 한다.

**두 방식을 모두 지원한다.** NCP 키(NAVER_APIHUB_*)가 있으면 그걸 쓰고,
없으면 기존 키(NAVER_CLIENT_*)로 떨어진다. 그래서 사장님이 NCP 콘솔에서
키를 발급해 GitHub Secrets 에 넣기만 하면 코드 수정 없이 전환된다.
전환 후 기존 키는 지워도 된다.

키(둘 중 하나):
  신규 — NAVER_APIHUB_CLIENT_ID / NAVER_APIHUB_CLIENT_SECRET
  기존 — NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
"""
import json
import os
import sys
import urllib.parse
import urllib.request

# 신규(NAVER API HUB) 우선, 없으면 기존 개발자센터 키로 떨어진다.
APIHUB_ID = os.environ.get("NAVER_APIHUB_CLIENT_ID", "")
APIHUB_SECRET = os.environ.get("NAVER_APIHUB_CLIENT_SECRET", "")
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

APIHUB_BASE = "https://naverapihub.apigw.ntruss.com"
LEGACY_BASE = "https://openapi.naver.com"


def _endpoint() -> tuple[str, dict] | None:
    """쓸 수 있는 (URL, 헤더)를 고른다. 자격증명이 없으면 None."""
    if APIHUB_ID and APIHUB_SECRET:
        # 경로 형태가 기존과 다르다. 기존은 '/v1/search/webkr.json' 인데
        #  API HUB 는 '/search/v1/webkr' 로 순서가 뒤집히고 확장자가 없다.
        #  (실측: '/v1/search/webkr.json' 은 404 "URL not found")
        return (f"{APIHUB_BASE}/search/v1/webkr",
                {"X-NCP-APIGW-API-KEY-ID": APIHUB_ID,
                 "X-NCP-APIGW-API-KEY": APIHUB_SECRET})
    if CLIENT_ID and CLIENT_SECRET:
        return (f"{LEGACY_BASE}/v1/search/webkr.json",
                {"X-Naver-Client-Id": CLIENT_ID,
                 "X-Naver-Client-Secret": CLIENT_SECRET})
    return None


def search(query: str, num_results: int = 5) -> list[dict]:
    """웹문서 검색 결과를 [{title, url}] 형태로 돌려준다.

    자격증명이 없으면 빈 리스트(진짜 무결과와 동일 취급) — 예외를
    던지면 상품이 '보류'로 쌓여 검증이 멈춘다.
    """
    picked = _endpoint()
    if not picked:
        return []
    base_url, headers = picked

    params = urllib.parse.urlencode({"query": query, "display": max(1, min(num_results, 100))})
    url = f"{base_url}?{params}"
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)

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
