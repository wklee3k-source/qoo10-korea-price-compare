"""
qoo10_ranking_scraper.py

자동화 영역: 큐텐(Qoo10.jp) 상점의 "실 판매랭킹(ランキング)" 위젯을 렌더링 후 파싱한다.
이 위젯은 AJAX로 렌더링되어 정적 HTML 수집으로는 잡히지 않으므로 Playwright 헤드리스
브라우저로 m.qoo10.jp 모바일 페이지를 직접 렌더링해서 추출한다.

사용법:
    python qoo10_ranking_scraper.py <shop_id> [<shop_id> ...]

    예) python qoo10_ranking_scraper.py wline hanbikosupa

출력:
    output/<shop_id>_ranking.json
    각 항목: goods_no, rank, image_url, title, brand, price_jpy
"""

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

RANKING_ITEM_RE = re.compile(
    r'data_gd_no="(\d+)".*?rank_current">(\d+)<'
    r'.*?src="([^"]+)" alt="([^"]*)"'
    r'.*?common_ui_seller_brand[^>]*>([^<]*)</span>\s*'
    r'<span class="list_v2_title[^"]*">([^<]*)</span>'
    r'.*?price_final_value[^>]*>([\d,]+)<',
    re.S,
)


def fetch_shop_ranking(shop_id: str, wait_seconds: int = 6) -> list[dict]:
    """m.qoo10.jp/shop/<shop_id> 를 렌더링해서 랭킹 TOP5를 반환한다."""
    url = f"https://m.qoo10.jp/shop/{shop_id}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 390, "height": 844},
            ignore_https_errors=True,
            is_mobile=True,
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="load")
        except Exception as e:  # noqa: BLE001 - best effort, content may still be usable
            print(f"[WARN] goto issue for {shop_id}: {e}", file=sys.stderr)

        time.sleep(wait_seconds)
        content = page.content()
        browser.close()

    idx = content.find('id="ul_minishop_ranking"')
    if idx == -1:
        print(f"[WARN] ranking widget not found for shop '{shop_id}'", file=sys.stderr)
        return []

    end_idx = content.find("</ul>", idx)
    block = content[idx:end_idx]

    items = []
    for m in RANKING_ITEM_RE.finditer(block):
        goods_no, rank, image_url, alt, brand, title, price = m.groups()
        items.append(
            {
                "goods_no": goods_no,
                "rank": int(rank),
                "image_url": image_url,
                "title": title.strip(),
                "brand": brand.strip(),
                "price_jpy": int(price.replace(",", "")),
                "item_url": f"https://m.qoo10.jp/gmkt.inc/Mobile/Goods/goods.aspx?goodscode={goods_no}",
            }
        )
    return items


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(exist_ok=True)

    for shop_id in sys.argv[1:]:
        print(f"[INFO] fetching ranking for shop: {shop_id}")
        items = fetch_shop_ranking(shop_id)
        out_path = out_dir / f"{shop_id}_ranking.json"
        out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] wrote {len(items)} items -> {out_path}")


if __name__ == "__main__":
    main()
