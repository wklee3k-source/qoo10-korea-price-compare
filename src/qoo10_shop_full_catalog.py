"""
qoo10_shop_full_catalog.py

자동화 영역: 이미 발굴된 상점의 "전체상품(全ての商品)" 목록을 랭크5(베스트5)가
아니라 전부 훑는다. 랭크5는 상점 하나당 최대 5개만 알려주지만, 이미 "괜찮은
상점"으로 확인된 곳이라면 그 상점이 파는 나머지 상품(리뷰수 20 이하, 색조 제외)도
전부 발굴 대상으로 삼을 가치가 있다는 판단에서 나온 확장 크롤러다.

[페이지 구조] 검색결과 페이지(qoo10_low_review_shop_finder.py)와 달리, 상점 자체
페이지는 <table><tr id="g_..."> 가 아니라 <ul><li id="g_..."> 갤러리 구조를 쓴다.
초기 로드는 60개뿐이고, "もっと見る"(더보기) 버튼을 계속 눌러야 나머지가 로드된다
(스크롤만으로는 안 됨 — 실측: 스크롤 8회 시도 시 120개에서 멈췄지만, 버튼을
JS로 직접 클릭하면 722개 전부 로드됨).

사용법:
    python qoo10_shop_full_catalog.py <shop_id>
    -> stdout에 JSON {"items": [...], "failed": bool} 출력 (crawl_single_shop.py와
       동일한 규약 — stdout에는 이 한 줄만 나가야 한다, 디버그 출력은 전부 stderr로)
"""

import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

MOBILE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

GA_CLICK_RE = re.compile(r"GA_Front\.Click\('([^']+)'\)")
TITLE_RE = re.compile(r'class="tt" href="[^"]*" title="([^"]+)"')
BRAND_RE = re.compile(r'class="txt_brand" href="[^"]*" title="ブランド:([^"]*)"')
REVIEW_RE = re.compile(r'review_total_count">\(([\d,]+)\)')


class ShopCatalogFailed(Exception):
    """페이지 자체를 못 불러온 경우에만 발생시킨다(9번 수정과 동일한 원칙 —
    '진짜 빈 상점'과 '크롤 실패'를 구분해야 재시도가 제대로 된다)."""


def fetch_shop_full_catalog(shop_id: str, max_clicks: int = 40, wait_seconds: int = 3) -> list[dict]:
    url = f"https://www.qoo10.jp/shop/{shop_id}?search_mode=basic"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=20000, wait_until="load")
        except Exception as e:  # noqa: BLE001
            browser.close()
            raise ShopCatalogFailed(f"{shop_id} 페이지 로드 실패: {e}") from e

        time.sleep(wait_seconds)

        # "더보기" 버튼을 JS로 직접 클릭(요소가 로딩 오버레이에 가려 일반
        # click()은 실패할 수 있어 evaluate로 우회 — 실측 확인된 방식).
        prev_count = -1
        for _ in range(max_clicks):
            try:
                cur_count = page.eval_on_selector_all('li[id^="g_"]', "els => els.length")
            except Exception:  # noqa: BLE001
                break
            if cur_count == prev_count:
                break  # 더 안 늘어나면(끝까지 로드됨) 종료
            prev_count = cur_count
            try:
                page.evaluate(
                    'document.querySelector("#btn_more_item") && '
                    'document.querySelector("#btn_more_item").click()'
                )
            except Exception:  # noqa: BLE001
                break
            time.sleep(1.5)
            # 로딩 스피너가 끝날 때까지 잠깐 더 기다린다(최대 5초).
            for _ in range(10):
                try:
                    hidden = page.eval_on_selector(
                        "#append_loading_span", "el => el.style.display"
                    )
                except Exception:  # noqa: BLE001
                    hidden = "none"
                if hidden == "none":
                    break
                time.sleep(0.5)

        content = page.content()
        browser.close()

    li_blocks = re.findall(r'<li id="g_\d+".*?</li>\s*(?=<li id="g_|</ul>)', content, re.S)

    items = []
    for block in li_blocks:
        ga_m = GA_CLICK_RE.search(block)
        if not ga_m:
            continue
        fields = ga_m.group(1).split("#")
        if len(fields) < 8:
            continue
        goods_no = fields[1]
        try:
            price_jpy = int(fields[2])
        except ValueError:
            price_jpy = None
        category = fields[7]

        title_m = TITLE_RE.search(block)
        brand_m = BRAND_RE.search(block)
        review_m = REVIEW_RE.search(block)

        items.append(
            {
                "goods_no": goods_no,
                "title": title_m.group(1).strip() if title_m else "",
                "brand": brand_m.group(1).strip() if brand_m else "",
                "price_jpy": price_jpy,
                "category_gdlc_cd": category,
                "review_count": int(review_m.group(1).replace(",", "")) if review_m else 0,
                "shop_id": shop_id,
            }
        )

    # goods_no 기준 중복제거(같은 상품이 여러 옵션으로 중복 렌더링되는 경우 대비)
    seen = {}
    for it in items:
        seen[it["goods_no"]] = it
    return list(seen.values())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    shop_id = sys.argv[1]
    try:
        result_items = fetch_shop_full_catalog(shop_id)
        failed = False
    except ShopCatalogFailed as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        result_items, failed = [], True
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] {shop_id}: {type(e).__name__}: {e}", file=sys.stderr)
        result_items, failed = [], True

    print(json.dumps({"items": result_items, "failed": failed}, ensure_ascii=False))
