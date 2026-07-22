"""
pipeline.py

자동화 영역 전체를 잇는 오케스트레이터.

    1) 상품명(핵심 문구)으로 Qoo10 검색 -> 저리뷰 상점 탐색   (qoo10_low_review_shop_finder)
    2) 그 상점의 실 판매랭킹 TOP5 추출                        (qoo10_ranking_scraper)
    3) 이미지 다운로드/정규화                                  (image_fetcher)
    4) 엑셀로 큐텐/한국 비교표 생성                             (excel_builder)

한국 쪽 공식몰 검색·가격 매칭은 AI(사람의 확인이 필요한 판단 영역)이므로
이 파이프라인은 큐텐 쪽 데이터 수집까지 자동화하고, korea_side.json은
사람이 채워 넣거나 별도 검색 도구로 채운 뒤 04 단계를 실행한다.

사용법:
    python pipeline.py "<검색 키워드>"
"""

import json
import sys
from pathlib import Path

from excel_builder import build_excel
from image_fetcher import download_and_normalize
from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_ranking_scraper import fetch_shop_ranking

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def run(keyword: str):
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"[STEP 1] Qoo10 검색: {keyword}")
    html = search_qoo10(keyword)
    sellers = parse_results(html)
    if not sellers:
        print("[ERROR] 검색 결과 없음. 종료.")
        return
    lowest = sellers[0]
    print(f"[STEP 1] 저리뷰 상점 선정: {lowest['shop_name']} ({lowest['shop_id']}), review={lowest['review_count']}")

    print(f"[STEP 2] '{lowest['shop_id']}' 상점 랭킹 TOP5 추출")
    ranking = fetch_shop_ranking(lowest["shop_id"])
    ranking_path = OUTPUT_DIR / f"{lowest['shop_id']}_ranking.json"
    ranking_path.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[STEP 2] {len(ranking)}건 저장 -> {ranking_path}")

    print("[STEP 3] 이미지 다운로드")
    img_dir = OUTPUT_DIR / "imgs"
    for i, item in enumerate(ranking):
        local_path = img_dir / f"{lowest['shop_id']}_{i}_qoo10.jpg"
        ok = download_and_normalize(item["image_url"], str(local_path))
        item["local_image"] = str(local_path) if ok else None

    print("[STEP 4] 사람 확인 대기: 한국 쪽(공식몰/브랜드스토어) 상품명·가격·이미지를")
    print(f"         output/{lowest['shop_id']}_korea_side.json 형식으로 채워주세요. 예시 생성 중...")

    template = [
        {
            "brand_ja": item["brand"],
            "name_ja": item["title"],
            "price_jpy": item["price_jpy"],
            "img_qoo10": item.get("local_image"),
            "name_kr": "",
            "price_krw": None,
            "img_kr": "",
            "kr_site": "",
        }
        for item in ranking
    ]
    template_path = OUTPUT_DIR / f"{lowest['shop_id']}_korea_side.json"
    template_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[STEP 4] 템플릿 저장 -> {template_path}")
    print("         name_kr / price_krw / img_kr / kr_site 를 채운 뒤 아래 명령으로 엑셀 생성:")
    print(f"         python excel_builder.py {template_path} ../output/{lowest['shop_id']}_비교.xlsx")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
