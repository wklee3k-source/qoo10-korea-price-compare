"""
qoo10_low_review_shop_finder.py

자동화 영역: 상품명(핵심 문구)으로 Qoo10.jp를 검색하고, 검색결과 안의 판매자들을
리뷰 수 기준으로 정렬해서 가장 낮은 상점을 찾는다.

사용법:
    python qoo10_low_review_shop_finder.py "<검색 키워드>"

출력:
    output/search_<키워드>.json
    리뷰수 오름차순으로 정렬된 [{shop_id, shop_name, review_count, price_jpy, goods_no, title}, ...]

주의:
    Qoo10.jp는 curl 등 단순 HTTP 요청을 봇으로 차단(523 에러)하므로
    반드시 Playwright 브라우저 렌더링을 거쳐야 한다.
"""

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

ROW_RE = re.compile(r'(<tr id="g_\d+".*?</tr>)', re.S)
GID_RE = re.compile(r'id="g_(\d+)"')
TITLE_RE = re.compile(r'title="([^"]+)" target="_blank" data-type="goods_url"')
SHOP_RE = re.compile(r'shop/([a-zA-Z0-9_.\-]+)\?cit=\d+" target="_blank" title="([^"]*)"')
REVIEW_RE = re.compile(r'review_total_count">\(([\d,]+)\)')
PRICE_RE = re.compile(r'<strong>([\d,]+)円</strong>')


def search_qoo10(keyword: str, wait_seconds: int = 4) -> str:
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.qoo10.jp/s/{encoded}?keyword={encoded}"

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
            print(f"[WARN] goto issue: {e}", file=sys.stderr)
        time.sleep(wait_seconds)
        content = page.content()
        browser.close()
    return content


def parse_results(html: str) -> list[dict]:
    start = html.find('id="search_result_item_list"')
    if start == -1:
        return []
    end = html.find("</tbody>", start)
    block = html[start:end]

    results = []
    for row_html in ROW_RE.findall(block):
        gid_m = GID_RE.search(row_html)
        title_m = TITLE_RE.search(row_html)
        shop_m = SHOP_RE.search(row_html)
        review_m = REVIEW_RE.search(row_html)
        price_m = PRICE_RE.search(row_html)

        if not (gid_m and shop_m):
            continue

        results.append(
            {
                "goods_no": gid_m.group(1),
                "title": title_m.group(1).strip() if title_m else "",
                "shop_id": shop_m.group(1),
                "shop_name": shop_m.group(2).strip(),
                "review_count": int(review_m.group(1).replace(",", "")) if review_m else 0,
                "price_jpy": int(price_m.group(1).replace(",", "")) if price_m else None,
            }
        )

    # dedupe by goods_no, sort by review_count ascending (lowest review/exposure first)
    seen = {}
    for r in results:
        seen[r["goods_no"]] = r
    return sorted(seen.values(), key=lambda r: r["review_count"])


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    keyword = sys.argv[1]
    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(exist_ok=True)

    print(f"[INFO] searching Qoo10.jp for: {keyword}")
    html = search_qoo10(keyword)
    results = parse_results(html)

    safe_name = re.sub(r"[^\w]+", "_", keyword)[:50]
    out_path = out_dir / f"search_{safe_name}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[INFO] {len(results)} unique sellers found -> {out_path}")
    if results:
        lowest = results[0]
        print(
            f"[INFO] lowest-review seller: {lowest['shop_name']} "
            f"({lowest['shop_id']}) review={lowest['review_count']}"
        )


if __name__ == "__main__":
    main()
