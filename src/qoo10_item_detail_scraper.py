"""
qoo10_item_detail_scraper.py

자동화 영역: 큐텐 개별 상품 상세페이지에서 EditItemList 업로드에 필요한 정보를
최대한 자동으로 추출한다. 상세페이지 내 JSON-LD(schema.org Product) 구조화 데이터를
1순위로 사용하고(가장 안정적), 브랜드 링크에서 brandno를 보조로 추출한다.

추가 추출 필드 (실제 페이지 검증 완료):
    category_gdlc_cd/gdmc_cd/gdsc_cd — 이 상품이 큐텐에 등록될 때 셀러가 지정한
        대/중/소카테고리 코드. 페이지 내 hidden input(img_search_gdlc_cd 등)에서
        추출한다. gdsc_cd(소카테고리, 9자리)가 EditItemList의 category_number와
        동일한 코드 체계이므로 그대로 재사용 가능하다 — 단, 이건 "원 판매자가 붙인"
        카테고리이므로 우리 상품과 맥락이 다를 수 있어 최종 확인은 여전히 권장한다.
    image_main_url_hires — 목록/리스트용 축소 이미지(g_400-w_g.jpg 등 사이즈 접미사
        포함)가 아니라, 접미사를 제거한 원본 해상도 이미지 URL. 실측 예시:
        400x408(9KB) -> 713x728(20KB) 로 약 2배 해상도 차이 확인.
    weight_hint — 상품명 텍스트에서 ml/g/kg 패턴을 정규식으로 뽑아낸 "참고용" 값.
        큐텐 페이지에는 공식적인 무게 필드가 없어(무게는 셀러 비공개 정보) 신뢰도가
        낮다 — item_weight 칸에 그대로 쓰지 말고 참고만 할 것.
    has_options — 페이지 hidden input(option_item_yn)에서 옵션(색상/사이즈 등 선택형)
        존재 여부를 읽는다. True인 상품은 match_review_builder.py에서 검수 대상에서
        자동 제외된다(옵션별로 실제 발송 상품이 달라질 수 있어 자동 매칭 리스크가 큼).

주의: 서브 이미지 갤러리(상품설명 탭 내부)와 상세설명 HTML은 셀러마다 구조가
달라 완전 자동 추출이 불안정하다. 이 스크립트는 신뢰할 수 있는 필드만 채우고,
나머지는 TODO로 표시해 사람이 확인하도록 한다 (README "AI/사람이 봐야 하는 영역" 참고).

사용법:
    python qoo10_item_detail_scraper.py <goods_no_or_url> [<goods_no_or_url> ...]

출력:
    output/items/<goods_no>.json
    output/imgs_hires/<goods_no>_qoo10.jpg   (고화질 원본 이미지, 리사이즈 없음)
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BRAND_LINK_RE = re.compile(r'brandno=(\d+)"[^>]*>\s*([^<]+)')
LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
OPTION_FLAG_RE = re.compile(r'id="option_item_yn"[^>]*value="([YN])"')
CATEGORY_RE = {
    "gdlc_cd": re.compile(r'id="img_search_gdlc_cd" value="(\d+)"'),
    "gdmc_cd": re.compile(r'id="img_search_gdmc_cd" value="(\d+)"'),
    "gdsc_cd": re.compile(r'id="img_search_gdsc_cd" value="(\d+)"'),
}
# g_400-w_g / g_400-w-st_g / g_80-w-st_g 등 사이즈 접미사를 제거해 원본 URL로 변환
IMG_SIZE_SUFFIX_RE = re.compile(r"\.g_\d+-w(?:-st)?_g(?=\.\w+$)")
WEIGHT_HINT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:ml|mL|ML|g|kg|G|KG)\b")


def _to_item_url(goods_no_or_url: str) -> str:
    if goods_no_or_url.startswith("http"):
        return goods_no_or_url
    return f"https://www.qoo10.jp/gmkt.inc/Goods/Goods.aspx?goodscode={goods_no_or_url}"


def _to_hires_url(image_url: str) -> str:
    """리스트/썸네일용 사이즈 접미사를 제거해 원본 해상도 URL을 만든다."""
    if not image_url:
        return image_url
    return IMG_SIZE_SUFFIX_RE.sub("", image_url)


def save_original_image(url: str, out_path: Path) -> bool:
    """리사이즈 없이 원본 그대로 저장한다 (고화질 보관용)."""
    if not url:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": DESKTOP_UA})
        with urllib.request.urlopen(req, timeout=20) as r, open(out_path, "wb") as f:
            f.write(r.read())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 고화질 이미지 저장 실패 {url}: {e}", file=sys.stderr)
        return False


def fetch_item_detail(goods_no_or_url: str, wait_seconds: int = 4, save_hires_image: bool = True) -> dict:
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
            page.goto(url, timeout=20000, wait_until="load")
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
        "image_main_url_hires": None,
        "image_hires_local_path": None,
        "image_other_url": [],  # TODO: 신뢰도 낮음, 사람 확인 필요
        "item_description_html": None,  # TODO: 셀러마다 구조 달라 미추출
        "category_gdlc_cd": None,
        "category_gdmc_cd": None,
        "category_gdsc_cd": None,
        "weight_hint": None,  # 참고용 추정치. 정식 item_weight로 그대로 쓰지 말 것.
        "has_options": None,  # 큐텐 옵션(색상/사이즈 등 선택형) 존재 여부. True면 검수단계에서 자동 제외 대상.
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

    for key, pattern in CATEGORY_RE.items():
        m = pattern.search(content)
        if m:
            result[f"category_{key}"] = m.group(1)

    option_m = OPTION_FLAG_RE.search(content)
    if option_m:
        result["has_options"] = option_m.group(1) == "Y"

    if result["item_name"]:
        wm = WEIGHT_HINT_RE.search(result["item_name"])
        if wm:
            result["weight_hint"] = wm.group(0)

    if not result["goods_no"]:
        m = re.search(r"goodscode=(\d+)", url)
        if m:
            result["goods_no"] = m.group(1)

    if result["image_main_url"]:
        hires_url = _to_hires_url(result["image_main_url"])
        result["image_main_url_hires"] = hires_url
        if save_hires_image and result["goods_no"]:
            out_dir = Path(__file__).resolve().parent.parent / "output" / "imgs_hires"
            ext = Path(hires_url).suffix or ".jpg"
            out_path = out_dir / f"{result['goods_no']}_qoo10{ext}"
            if save_original_image(hires_url, out_path):
                result["image_hires_local_path"] = str(out_path)

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
        if detail.get("image_hires_local_path"):
            print(f"[INFO] 고화질 이미지 저장 -> {detail['image_hires_local_path']}")


if __name__ == "__main__":
    main()
