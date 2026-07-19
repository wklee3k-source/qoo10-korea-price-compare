"""
edit_item_list_builder.py

자동화 영역: qoo10_item_detail_scraper.py로 수집한 상품 정보 +
category_brand_matcher.py로 조회한 카테고리/브랜드 코드를 합쳐서,
공식 Qoo10_EditItemList.xlsx 템플릿의 헤더/가이드 행(1~4행)은 그대로 두고
5행부터 데이터 행을 채운 새 업로드 파일을 만든다.

자동으로 채우는 필드 (신뢰도 높음):
    seller_unique_item_id, item_name, image_main_url,
    category_number(단일 후보일 때만), brand_number(단일 후보일 때만),
    item_status_Y/N/D, end_date, quantity, Shipping_number,
    available_shipping_date, item_condition_type, origin_type, origin_country_id

TODO로 남기는 필드 (AI/사람 판단 필요, README 참고):
    price_yen / retail_price_yen  -> 마진계산기 결과 필요
    category_number/brand_number  -> 매칭 후보가 여러 개거나 없을 때
    image_other_url, item_description -> 상세페이지 구조가 셀러마다 달라 미추출
    item_weight, model_name 등 상품별 개별 정보

사용법:
    python edit_item_list_builder.py <template.xlsx> <items_dir> <output.xlsx>

    items_dir 안의 각 <goods_no>.json 은 qoo10_item_detail_scraper.py 출력 형식이어야 한다.
"""

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

from category_brand_matcher import BrandCategoryMatcher

DATA_START_ROW = 5  # 템플릿의 예시 행부터 실제 데이터로 채움
TODO = "TODO"

# 신규 등록 시 공통 기본값 (템플릿 예시 행 관례를 따름)
DEFAULTS = {
    "item_status_Y/N/D": "Y",
    "end_date": "2050-12-31 00:00:00",
    "quantity": 200,
    "Shipping_number": 0,
    "available_shipping_date": 3,
    "item_condition_type": 1,  # 1: 새상품
    "origin_type": 2,  # 2: 해외
    "origin_country_id": "KR",  # 한국 소싱 상품 기준
}


def load_items(items_dir: str) -> list[dict]:
    items = []
    for path in sorted(Path(items_dir).glob("*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def build_row(item: dict, matcher: BrandCategoryMatcher) -> dict:
    row = dict(DEFAULTS)

    row["seller_unique_item_id"] = item.get("goods_no", TODO)
    row["item_name"] = item.get("item_name") or TODO
    row["image_main_url"] = item.get("image_main_url") or TODO

    brand_name = item.get("brand_name")
    if brand_name:
        candidates = matcher.find_brand(brand_name)
        if len(candidates) == 1:
            row["brand_number"] = candidates[0]["brand_no"]
        else:
            row["brand_number"] = f"{TODO} (후보 {len(candidates)}건, brand_name={brand_name})"
    else:
        row["brand_number"] = TODO

    # 카테고리는 상품명 토큰만으로는 신뢰도가 낮으므로 항상 사람 확인 필요
    row["category_number"] = f"{TODO} (item_name 참고해서 카테고리 지정 필요)"

    row["price_yen"] = f"{TODO} (마진계산기 결과 반영 필요, 큐텐참고가={item.get('price_jpy')})"
    row["retail_price_yen"] = TODO

    row["image_other_url"] = TODO
    row["item_description"] = TODO
    row["item_weight"] = TODO

    return row


COLUMN_ORDER = [
    "item_number", "seller_unique_item_id", "category_number", "brand_number", "item_name",
    "item_promotion_name", "item_status_Y/N/D", "start_date", "end_date", "price_yen",
    "retail_price_yen", "taxrate", "quantity", "option_info", "additional_option_info",
    "additional_option_text", "image_main_url", "image_other_url", "video_url",
    "image_option_info", "image_additional_option_info", "header_html", "footer_html",
    "item_description", "Shipping_number", "option_number", "available_shipping_date",
    "desired_shipping_date", "search_keyword", "item_condition_type", "origin_type",
    "origin_region_id", "origin_country_id", "origin_others", "medication_type",
    "item_weight", "item_material", "model_name", "external_product_type",
    "external_product_id", "manufacture_date", "expiration_date_type", "expiration_date_MFD",
    "expiration_date_PAO", "expiration_date_EXP", "under18s_display_Y/N", "A/S_info",
    "buy_limit_type", "buy_limit_date", "buy_limit_qty",
]


def build_workbook(template_path: str, items: list[dict], matcher: BrandCategoryMatcher, out_path: str):
    wb = load_workbook(template_path)
    ws = wb.active

    header_row = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert header_row == COLUMN_ORDER, "템플릿 컬럼 순서가 예상과 다릅니다. 템플릿이 바뀌었는지 확인하세요."

    for i, item in enumerate(items):
        row_data = build_row(item, matcher)
        r = DATA_START_ROW + i
        for col_idx, col_name in enumerate(COLUMN_ORDER, start=1):
            if col_name in row_data:
                ws.cell(row=r, column=col_idx, value=row_data[col_name])

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    template_path, items_dir, out_path = sys.argv[1:4]
    data_dir = Path(__file__).resolve().parent.parent / "data"
    matcher = BrandCategoryMatcher(
        str(data_dir / "brand_list.csv"), str(data_dir / "qoo10_category_info.csv")
    )

    items = load_items(items_dir)
    print(f"[INFO] {len(items)}건 로드")

    build_workbook(template_path, items, matcher, out_path)
    print(f"[INFO] 작성 완료 -> {out_path}")
    print("[INFO] TODO 표시된 셀(가격/카테고리/설명/이미지 등)은 반드시 사람이 채운 뒤 업로드하세요.")


if __name__ == "__main__":
    main()
