"""
product_gallery.py — 상품 구매링크(상세페이지)에 직접 접속해서 그 상품의
실제 갤러리 사진(여러 장)을 가져온다.

[배경] 지금까지 "이미지 후보 여러 장"이라고 부르던 건 네이버쇼핑 검색결과에
나온 "여러 판매자 각각의 사진 1장씩"이었다. 실제로 한 상품 상세페이지 안에는
훨씬 많은 갤러리 사진(정면/측면/성분표/사용법 등)이 있는데, 이건 네이버쇼핑
API로는 못 가져오고 상세페이지를 직접 열어야 한다.

[지원 사이트] 스마트스토어(smartstore.naver.com)를 우선 지원한다. 다른
쇼핑몰(쿠팡, 자사몰 등)은 사이트마다 구조가 달라서 순차적으로 추가한다.

사용법:
    python product_gallery.py <product_url>
"""

import json
import re
import sys

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fetch_gallery(product_url: str, max_images: int = 8, timeout_ms: int = 20000) -> list[str]:
    """상품 상세페이지에서 갤러리 이미지 URL 목록을 가져온다."""
    if not product_url:
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
            page = context.new_page()
            try:
                page.goto(product_url, timeout=timeout_ms, wait_until="load")
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # noqa: BLE001
                pass

            # 스마트스토어는 페이지 안에 __NEXT_DATA__ 형태로 상품 이미지 목록을
            # JSON으로 갖고 있는 경우가 많다 — DOM 파싱보다 안정적이다.
            images: list[str] = []
            try:
                next_data_raw = page.evaluate(
                    "() => { const el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent : null; }"
                )
                if next_data_raw:
                    data = json.loads(next_data_raw)
                    found = _find_image_urls_in_json(data)
                    images.extend(found)
            except Exception:  # noqa: BLE001
                pass

            # __NEXT_DATA__로 못 찾았으면 DOM의 img 태그를 직접 훑는다(폴백)
            if not images:
                try:
                    imgs = page.query_selector_all("img")
                    for img in imgs:
                        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                        if re.search(r"pstatic\.net.*(product|main_)", src):
                            images.append(src.split("?")[0])
                except Exception:  # noqa: BLE001
                    pass

            browser.close()

        # 중복 제거, 순서 유지
        seen = set()
        unique = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique.append(img)
        return unique[:max_images]
    except Exception as e:  # noqa: BLE001
        print(f"[갤러리조회 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return []


def _find_image_urls_in_json(obj, depth: int = 0) -> list[str]:
    """__NEXT_DATA__ JSON 안에서 상품 이미지로 보이는 URL들을 재귀적으로 찾는다."""
    if depth > 12:
        return []
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and "pstatic.net" in v and re.search(r"\.(jpg|jpeg|png|webp)", v, re.I):
                if k.lower() in ("url", "imageurl", "src", "originalurl"):
                    found.append(v)
            else:
                found.extend(_find_image_urls_in_json(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj[:50]:
            found.extend(_find_image_urls_in_json(item, depth + 1))
    return found


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    result = fetch_gallery(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
