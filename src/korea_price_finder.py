"""
korea_price_finder.py

자동화 영역: 4단계(한국 원가 매칭)를 완전 자동화하기 위한 스크립트.

[배경] 지금까지 4단계는 매번 web_search로 브랜드+상품명을 검색하고 사람이
직접 판단해서 채워왔다 — 정확하지만 상품 1개당 검색 1~3회가 필요해 200개
규모로는 감당이 안 됐다. 이 스크립트는 danawa.com(다나와) 검색을 자동으로
긁어서 후보 가격을 즉시 여러 개 가져온다.

[왜 다나와인가] 이 실행환경에서 실제로 접근 가능한지 직접 확인했다:
    - search.shopping.naver.com : 접속 차단됨 (egress policy)
    - www.oliveyoung.co.kr      : 403 (봇 차단)
    - search.danawa.com         : 200 정상 접근 + 구조화된 가격 데이터 확인됨
다나와는 여러 판매처의 최저가를 모아 보여주는 가격비교 사이트라 판매처가
공식몰인지 아닌지는 자동으로 완벽히 구분되지 않는다. 그래서 이 스크립트는
"자동 후보 발굴" 용도로만 쓰고, 결과에 항상 "가격비교사이트 후보"라는
꼬리표를 남겨 사람이 최종 확인하도록 설계했다 — 완전 자동 확정이 아니라
사람 검수 부담을 크게 줄여주는 역할이다.

사용법:
    python korea_price_finder.py "<검색어>"
    python korea_price_finder.py --batch <items_dir> <output.json>
        items_dir 안의 qoo10_item_detail_scraper.py 출력들을 모두 읽어
        brand_name + item_name에서 핵심어를 뽑아 자동 검색한다.
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

PROD_ITEM_RE = re.compile(r'<li[^>]*class="prod_item[^"]*"', re.S)
NAME_RE = re.compile(r'class="prod_name">\s*<a[^>]*>(.*?)</a>', re.S)
PRICE_RE = re.compile(r'class="price_sect"[^>]*>.*?<strong>([\d,]+)</strong>', re.S)
LINK_RE = re.compile(r'<a href="(https://prod\.danawa\.com/bridge/go_link_goods\.php[^"]+)"')
IMG_RE = re.compile(r'thumb_image">.*?<img src="([^"]+)"', re.S)
TAG_RE = re.compile(r"</?b>")


def search_danawa(keyword: str, wait_seconds: float = 3.0) -> str:
    url = f"https://search.danawa.com/dsearch.php?query={keyword}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="load")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] goto issue: {e}", file=sys.stderr)
        time.sleep(wait_seconds)
        content = page.content()
        browser.close()
    return content


def parse_candidates(html: str, max_results: int = 5) -> list[dict]:
    # 각 prod_item 블록 단위로 잘라서 이름/가격/링크를 뽑는다
    blocks = re.split(r'(?=<li[^>]*class="prod_item)', html)
    results = []
    for block in blocks:
        if 'class="prod_item' not in block:
            continue
        name_m = NAME_RE.search(block)
        price_m = PRICE_RE.search(block)
        link_m = LINK_RE.search(block)
        img_m = IMG_RE.search(block)
        if not (name_m and price_m):
            continue
        name = TAG_RE.sub("", name_m.group(1)).strip()
        price = int(price_m.group(1).replace(",", ""))
        img_url = img_m.group(1) if img_m else None
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url
        results.append(
            {
                "name": name,
                "price_krw": price,
                "link": link_m.group(1) if link_m else None,
                "img_kr": img_url,
            }
        )
        if len(results) >= max_results:
            break
    return results


def find_price(keyword: str, max_results: int = 5) -> list[dict]:
    import urllib.parse

    html = search_danawa(urllib.parse.quote(keyword))
    return parse_candidates(html, max_results)


def batch_find(items_dir: str, out_path: str):
    out_file = Path(out_path)
    results = []
    done_goods_no = set()
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
        done_goods_no = {r["goods_no"] for r in results}
        print(f"[RESUME] 이미 처리된 {len(done_goods_no)}건부터 이어서 진행")

    for p in sorted(Path(items_dir).glob("*.json")):
        item = json.loads(p.read_text(encoding="utf-8"))
        goods_no = item.get("goods_no")
        if goods_no in done_goods_no:
            continue

        brand = item.get("brand_name") or ""
        name = item.get("item_name") or ""
        keyword = f"{brand} {name}"[:60]
        print(f"[SEARCH] {goods_no}: {keyword}")
        try:
            candidates = find_price(keyword)
        except Exception as e:  # noqa: BLE001
            print(f"    [WARN] 검색 실패: {e}")
            candidates = []
        for c in candidates:
            c["kr_site"] = "가격비교사이트 후보(danawa) — 실제 판매처/정가 여부 확인 필요"

        results.append(
            {
                "goods_no": goods_no,
                "qoo10_name": name,
                "brand_name": brand,
                "candidates": candidates,
            }
        )
        # 매 건마다 즉시 저장 (타임아웃/중단에도 진행상황 보존)
        out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        if candidates:
            print(f"    -> {len(candidates)}건 후보, 최저 {min(c['price_krw'] for c in candidates):,}원")
        else:
            print("    -> 후보 없음")

    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--batch":
        batch_find(sys.argv[2], sys.argv[3])
        return

    keyword = sys.argv[1]
    candidates = find_price(keyword)
    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
