"""
stock_checker.py

자동화 영역: 한국 소싱처 상품페이지의 품절 여부를 자동으로 확인한다.

[핵심 주의사항] cafe24 등 대부분의 쇼핑몰 플랫폼은 "품절"/"SOLD OUT" 배지 요소를
항상 DOM에 숨겨둔 채(display:none) 만들어두고, 실제 품절일 때만 JS로 보이게
바꾸는 구조다. 그래서 페이지에 그 텍스트가 "존재하는지"만 보면 항상 오탐(false
positive)이 난다 — 반드시 그 요소가 실제로 화면에 "보이는지(visible)"까지
확인해야 한다. 이 스크립트는 그 방식으로 검증한다(2026-07-19 실측 확인 완료:
7개 상품 중 여러 곳에서 "품절"/"SOLD OUT" 텍스트 자체는 있었지만 전부 숨김
요소였고, 실제로는 전부 재고 있음이었다).

판정 로직:
    1) "품절"/"SOLD OUT"/"일시품절"/"재입고 알림" 등의 텍스트를 가진 요소를 찾는다.
    2) 그 요소가 실제로 화면에 보이는(visible) 상태인지 확인한다.
    3) 보이는 품절 관련 요소가 하나라도 있으면 품절(False), 없으면 재고있음(True)으로 판정.
    4) 페이지 로드 자체가 실패하면 unknown으로 남긴다(재고 있다고 함부로 단정하지 않음).

사용법:
    python stock_checker.py <url> [<url> ...]
    python stock_checker.py --korea-side <korea_side.json>   # 파일 안의 kr_site/소싱링크 전부 검사

출력:
    output/stock_status.json  — {url: {in_stock, evidence, checked_at}}
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SOLDOUT_KEYWORDS = ["품절", "SOLD OUT", "Sold Out", "일시품절", "재입고 알림", "판매종료", "구매불가"]

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def check_stock(url: str, wait_seconds: float = 1.2) -> dict:
    result = {
        "url": url,
        "in_stock": None,  # True/False/None(확인불가)
        "evidence": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
            page = context.new_page()
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(wait_seconds)

            visible_soldout = []
            for kw in SOLDOUT_KEYWORDS:
                try:
                    els = page.query_selector_all(f"text={kw}")
                except Exception:
                    continue
                for el in els[:5]:
                    try:
                        if el.is_visible():
                            tag = el.evaluate("e => e.tagName")
                            visible_soldout.append(f"{kw} ({tag}, visible)")
                    except Exception:
                        continue

            browser.close()

        if visible_soldout:
            result["in_stock"] = False
            result["evidence"] = visible_soldout
        else:
            result["in_stock"] = True
            result["evidence"] = ["품절 관련 요소 중 화면에 보이는 것 없음"]

    except Exception as e:  # noqa: BLE001
        result["in_stock"] = None
        result["evidence"] = [f"페이지 로드 실패: {e}"]

    return result


def check_from_korea_side(korea_side_path: str) -> list[dict]:
    data = json.loads(Path(korea_side_path).read_text(encoding="utf-8"))
    results = []
    for item in data:
        # kr_site 텍스트에 URL이 없으면 스킵(설명 텍스트만 있는 경우)
        url = item.get("source_url") or item.get("link")
        if not url:
            continue
        r = check_stock(url)
        r["goods_no"] = item.get("goods_no")
        r["name_kr"] = item.get("name_kr")
        results.append(r)
        status = "재고있음" if r["in_stock"] is True else ("품절" if r["in_stock"] is False else "확인불가")
        print(f"[{status}] {item.get('goods_no')} {item.get('name_kr')} -> {url}")
    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "stock_status.json"

    if sys.argv[1] == "--korea-side":
        results = check_from_korea_side(sys.argv[2])
    else:
        results = []
        for url in sys.argv[1:]:
            r = check_stock(url)
            results.append(r)
            status = "재고있음" if r["in_stock"] is True else ("품절" if r["in_stock"] is False else "확인불가")
            print(f"[{status}] {url}")
            for e in r["evidence"]:
                print(f"    - {e}")

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[INFO] 결과 저장 -> {out_path}")

    soldout = [r for r in results if r["in_stock"] is False]
    unknown = [r for r in results if r["in_stock"] is None]
    if soldout:
        print(f"[경고] 품절 {len(soldout)}건 발견 — 업로드 전 반드시 확인하세요.")
    if unknown:
        print(f"[주의] 확인 불가 {len(unknown)}건 — 직접 확인 필요.")


if __name__ == "__main__":
    main()
