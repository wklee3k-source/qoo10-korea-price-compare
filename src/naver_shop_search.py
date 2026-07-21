"""
naver_shop_search.py — 네이버쇼핑 검색 API 래퍼(GitHub Actions 전용,
이 스크립트 자체는 로컬 샌드박스에서 실행 불가 — openapi.naver.com 차단됨)
"""
import json
import os
import sys
import urllib.request
import urllib.parse

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")


def search(query: str, display: int = 5) -> list[dict]:
    url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(query)}&display={display}"
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
    items = []
    for item in data.get("items", []):
        title = item["title"].replace("<b>", "").replace("</b>", "")
        items.append({
            "title": title,
            "brand": item.get("brand", ""),
            "maker": item.get("maker", ""),
            "lprice": item.get("lprice"),
            "mallName": item.get("mallName"),
            "productId": item.get("productId"),
        })
    return items


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["아누아 어성초 토너"]
    results = {}
    for q in queries:
        results[q] = search(q)
    print(json.dumps(results, ensure_ascii=False, indent=2))
