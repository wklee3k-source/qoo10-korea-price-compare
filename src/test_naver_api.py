"""
test_naver_api.py — 네이버 쇼핑검색 API 테스트(GitHub Actions에서 실행,
로컬 샌드박스는 openapi.naver.com이 네트워크 정책으로 차단되어 있어서
여기서는 테스트 불가능함).
"""
import json
import os
import sys
import urllib.request
import urllib.parse

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")


def search(query: str, display: int = 5) -> dict:
    url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(query)}&display={display}"
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode("utf-8"))


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "아누아 어성초 토너"
    result = search(query)
    print(json.dumps(result, ensure_ascii=False, indent=2))
