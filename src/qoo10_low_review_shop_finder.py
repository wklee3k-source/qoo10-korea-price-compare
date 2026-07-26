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


def search_qoo10(keyword: str, wait_seconds: int = 4, max_scrolls: int = 8) -> str:
    """검색어로 큐텐재팬을 검색해서 결과 페이지 HTML을 반환한다.

    [1순위 개선] 예전엔 페이지를 열고 wait_seconds만 기다린 뒤 그 상태
    그대로 읽었다. 그런데 검색결과 테이블은 무한스크롤 방식이라, 첫
    화면엔 딱 40개만 로드되고 나머지(표시된 전체상품 수 - 40개)는
    스크롤을 실제로 내려야 추가로 로드된다. 실측 확인(PDRN 검색어:
    72개 표시 중 40개만 파싱, 28개 상점만 회수 vs 스크롤 강제시 72개
    전부/48개 상점; 스파그로우 검색어: 178개 표시 중 스크롤 없이는
    35개 상점, 스크롤 강제시 127~139개 상점 — 최대 3.7배 차이).
    이제 마우스 휠 스크롤을 max_scrolls번 반복해서 더 로드할 게 없을
    때까지(또는 상한 횟수까지) 계속 끌어온다."""
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
        # 속도 개선: 텍스트 데이터만 필요하므로 이미지/폰트/CSS/미디어는 아예 안 받는다
        try:
            page.goto(url, timeout=20000, wait_until="load")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] goto issue: {e}", file=sys.stderr)
        time.sleep(wait_seconds)

        # 무한스크롤 유도: 더 이상 행(row)이 안 늘어나면 일찍 멈춘다.
        prev_count = -1
        for _ in range(max_scrolls):
            try:
                page.mouse.wheel(0, 3000)
            except Exception:  # noqa: BLE001
                break
            time.sleep(1.5)
            try:
                cur_count = page.eval_on_selector_all('tr[id^="g_"]', "els => els.length")
            except Exception:  # noqa: BLE001
                cur_count = prev_count
            if cur_count == prev_count:
                break  # 더 늘어나지 않으면(끝까지 로드됨) 스크롤 그만
            prev_count = cur_count

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
