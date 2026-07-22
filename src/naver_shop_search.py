"""
naver_shop_search.py — 네이버쇼핑 검색 API 래퍼(GitHub Actions 전용,
이 스크립트 자체는 로컬 샌드박스에서 실행 불가 — openapi.naver.com 차단됨)
"""
import json
import os
import re
import sys
import urllib.request
import urllib.parse

CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

# 신뢰할 수 있는(정품/공식 가능성이 높은) 판매채널 화이트리스트.
# 화장품 유통에서 실제로 공식/정식 채널로 통용되는 곳들 — 병행수입/구매대행
# 같은 소규모 스토어와 구분하기 위함.
TRUSTED_MALLS = {
    "올리브영", "시코르", "화해쇼핑", "무신사", "쿠팡", "지그재그",
    "롯데온", "SSG.COM", "신세계몰", "11번가", "G마켓", "옥션",
    "롯데백화점", "신세계백화점", "현대백화점",
}


def _is_official_seller(mall_name: str, brand: str) -> str:
    """판매처가 공식/신뢰 가능한 채널인지 판단한다.
    - mallName에 "공식"이 들어있으면 공식몰로 간주
    - mallName이 브랜드명 자체를 포함하면(예: "아누아" 브랜드의 "아누아" 스토어) 공식 가능성 높음
    - TRUSTED_MALLS(올리브영/쿠팡/무신사 등 정식유통 대형몰)에 있으면 신뢰
    - 그 외(개인샵, 구매대행 등으로 보이는 소규모 스토어명)는 "미확인"으로 표시"""
    if not mall_name:
        return "미확인"
    mall_lower = mall_name.lower()
    brand_lower = (brand or "").lower()
    brand_core = re.sub(r"\(.*?\)", "", brand_lower).strip()  # "아누아 (Anua)" -> "아누아"

    if "공식" in mall_name:
        return "공식몰"
    if brand_core and brand_core in mall_lower:
        return "브랜드직영추정"
    if mall_name in TRUSTED_MALLS:
        return "신뢰채널"
    return "미확인"


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
        mall_name = item.get("mallName")
        brand = item.get("brand", "")
        items.append({
            "title": title,
            "brand": brand,
            "maker": item.get("maker", ""),
            "lprice": item.get("lprice"),
            "link": item.get("link"),
            "image": item.get("image"),
            "mallName": mall_name,
            "productId": item.get("productId"),
            "seller_trust": _is_official_seller(mall_name, brand),
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

    # 신뢰도 높은 판매처를 우선순위로 재정렬한다("미확인"보다 "공식몰/신뢰채널"을 앞으로)
    trust_order = {"공식몰": 0, "브랜드직영추정": 1, "신뢰채널": 2, "미확인": 3}
    items.sort(key=lambda it: trust_order.get(it["seller_trust"], 3))

    return items


if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["아누아 어성초 토너"]
    results = {}
    for q in queries:
        results[q] = search(q)
    print(json.dumps(results, ensure_ascii=False, indent=2))
