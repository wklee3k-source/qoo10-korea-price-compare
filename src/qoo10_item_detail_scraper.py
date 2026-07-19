"""
qoo10_item_detail_scraper.py

자동화 영역: 큐텐 개별 상품 상세페이지에서 EditItemList 업로드에 필요한 정보를
최대한 자동으로 추출한다. 상세페이지 내 JSON-LD(schema.org Product) 구조화 데이터를
1순위로 사용하고(가장 안정적), 브랜드 링크에서 brandno를 보조로 추출한다.

주의: 서브 이미지 갤러리(상품설명 탭 내부)와 상세설명 HTML은 셀러마다 구조가
달라 완전 자동 추출이 불안정하다. 이 스크립트는 신뢰할 수 있는 필드만 채우고,
나머지는 TODO로 표시해 사람이 확인하도록 한다 (README "AI/사람이 봐야 하는 영역" 참고).

사용법:
    python qoo10_item_detail_scraper.py <goods_no_or_url> [<goods_no_or_url> ...]

출력:
    output/items/<goods_no>.json
"""

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BRAND_LINK_RE = re.compile(r'brandno=(\d+)"[^>]*>\s*([^<]+)')
LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _to_item_url(goods_no_or_url: str) -> str:
    if goods_no_or_url.startswith("http"):
        return goods_no_or_url
    return f"https://www.qoo10.jp/gmkt.inc/Goods/Goods.aspx?goodscode={goods_no_or_url}"


def fetch_item_detail(goods_no_or_url: str, wait_seconds: int = 4) -> dict:
    url = _to_item_url(goods_no_or_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DESKTOP_UA,
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="load")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] goto issue for {url}: {e}", file=sys.stderr)
        time.sleep(wait_seconds)
        content = page.content()
        browser.close()

    result = {
        "source_url": url,
        "goods_no": None,
        "item_name": None,
        "brand_name": None,
        "brand_no": None,
        "price_jpy": None,
        "review_count": None,
        "rating": None,
        "image_main_url": None,
        "image_other_url": [],  # TODO: 신뢰도 낮음, 사람 확인 필요
        "item_description_html": None,  # TODO: 셀러마다 구조 달라 미추출
    }

    ld_matches = LD_JSON_RE.findall(content)
    for raw in ld_matches:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "Product":
            continue

        result["item_name"] = data.get("name")
        images = data.get("image")
        if isinstance(images, list) and images:
            result["image_main_url"] = images[0]
        elif isinstance(images, str):
            result["image_main_url"] = images

        brand = data.get("brand", {})
        if isinstance(brand, dict):
            result["brand_name"] = brand.get("name")

        offers = data.get("offers", {})
        if isinstance(offers, dict):
            result["price_jpy"] = offers.get("price")

        rating = data.get("aggregateRating", {})
        if isinstance(rating, dict):
            result["review_count"] = rating.get("reviewCount")
            result["rating"] = rating.get("ratingValue")

        result["goods_no"] = data.get("sku")
        break

    brand_link = BRAND_LINK_RE.search(content)
    if brand_link:
        result["brand_no_hint"] = brand_link.group(1)  # 참고용, 정식 매칭은 category_brand_matcher 사용

    if not result["goods_no"]:
        m = re.search(r"goodscode=(\d+)", url)
        if m:
            result["goods_no"] = m.group(1)

    return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    out_dir = Path(__file__).resolve().parent.parent / "output" / "items"
    out_dir.mkdir(parents=True, exist_ok=True)

    for arg in sys.argv[1:]:
        print(f"[INFO] fetching item detail: {arg}")
        detail = fetch_item_detail(arg)
        goods_no = detail.get("goods_no") or arg
        out_path = out_dir / f"{goods_no}.json"
        out_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] wrote -> {out_path}")


if __name__ == "__main__":
    main()
