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


def search(query: str, display: int = 5, known_brand: str = "") -> list[dict]:
    url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(query)}&display={display}"
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    with urllib.request.urlopen(req, timeout=10) as res:
        raw = res.read().decode("utf-8")
    if os.environ.get("NAVER_DEBUG"):
        print(f"    [naver raw] total={json.loads(raw).get('total')} len={len(raw)}", file=sys.stderr)
    data = json.loads(raw)
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

    if known_brand:
        # 브랜드 필드가 우리가 아는 브랜드와 일치하는 것만 남긴다(엉뚱한
        # 브랜드 상품이 실려서 오답이 되는 걸 막기 위함). brand 필드가
        # 비어있는 경우(네이버가 브랜드 인식을 못 한 리스팅)는 상품명에
        # 브랜드명이 포함되어 있으면 통과시킨다.
        filtered = []
        for it in items:
            item_brand = (it.get("brand") or "").lower()
            title_lower = it["title"].lower()
            kb_lower = known_brand.lower()
            if kb_lower in item_brand or kb_lower in title_lower:
                filtered.append(it)
        if os.environ.get("NAVER_DEBUG"):
            print(f"    [naver 브랜드필터] known_brand='{known_brand}' {len(items)}건 -> {len(filtered)}건", file=sys.stderr)
        items = filtered

    return items


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["아누아 어성초 토너"]
    results = {}
    for q in queries:
        results[q] = search(q)
    print(json.dumps(results, ensure_ascii=False, indent=2))
