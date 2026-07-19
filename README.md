# qoo10-korea-price-compare

Qoo10.jp 저리뷰 상점 판매랭킹을 추출하고, 한국 공식몰/브랜드스토어 가격과
비교하는 엑셀을 자동 생성하기 위한 프로젝트입니다.

## 작업 영역 구분

이 프로젝트는 아래 세 영역을 명확히 나눠서 진행합니다.

### 1. 자동화 영역 (이 저장소의 스크립트가 처리)
- `src/qoo10_low_review_shop_finder.py` — 상품명 검색 → 판매자별 리뷰수 정렬 → 최저리뷰 상점 탐색
- `src/qoo10_ranking_scraper.py` — 특정 상점의 実 판매랭킹(AJAX 위젯) TOP5 추출
- `src/qoo10_item_detail_scraper.py` — 개별 상품 상세페이지(JSON-LD)에서 상품명/브랜드/가격/대표이미지 추출
- `src/category_brand_matcher.py` — data/의 브랜드·카테고리 참조표로 brand_number/category_number 조회
- `src/edit_item_list_builder.py` — 위 정보를 공식 Qoo10_EditItemList.xlsx 양식에 맞춰 데이터 행 생성
- `src/image_fetcher.py` — 상품 이미지 다운로드 및 JPEG 정규화
- `src/excel_builder.py` — 비교 데이터를 이미지 포함 엑셀로 출력
- `src/pipeline.py` — 위 단계를 순서대로 실행하는 오케스트레이터

### 참조 데이터 (data/)
- `brand_list.csv` — 큐텐 브랜드명(영/일/한) ↔ brand_number
- `qoo10_category_info.csv` — 큐텐 대/중/소카테고리명 ↔ category_number
- `oliveyoung_categories.json` — 올리브영 dispCatNo ↔ 카테고리명
- `Qoo10_EditItemList_template.xlsx` — 공식 업로드 양식 원본(헤더/가이드 행 보존용)

### 2. AI가 봐야 하는 영역 (사람의 지시 아래 판단 필요, 자동화 스크립트 밖)
- 일본어 상품명에서 브랜드+고유명+용량만 남기는 핵심문구 추출
- 큐텐 상품과 한국 상품이 "동일 제품"이 맞는지 매칭 판단
- 검색결과 중 진짜 공식몰/브랜드스토어인지 구분(총판/병행수입 구별)
- `category_number` 매칭 후보가 여러 개이거나 없을 때 최종 카테고리 확정
  (상품명만으로는 신뢰도가 낮아 `edit_item_list_builder.py`는 이 필드를 항상 TODO로 남김)

### 3. 사람이 봐야 하는 영역 (최종 확인/실행)
- 최종 리스팅 상점/상품 선정
- 가격 책정(관부가세, 마진, 환율) — `price_yen`/`retail_price_yen`은 마진계산기 결과를 받아야 확정됨
- 상세설명(`item_description`)·서브이미지(`image_other_url`) 작성 — 셀러마다 상세페이지 구조가 달라 자동 추출 미지원
- 이미지 저작권 확인
- 브랜드 정품 여부 최종 확인
- 실제 리스팅 등록 실행

`pipeline.py`는 1번 영역까지 자동 처리한 뒤, 한국 쪽 정보를 채울 수 있는
템플릿 JSON(`output/<shop_id>_korea_side.json`)을 생성하고 멈춥니다.
이 템플릿을 채우는 것이 2번(AI 검색/매칭) + 3번(사람 확인) 영역입니다.

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

## 사용법

```bash
# 1) 상품명으로 검색 -> 저리뷰 상점 -> 랭킹 -> 이미지까지 자동 수집
python src/pipeline.py "celimax ハートピンクトーンアップUVクリーム"

# 2) output/<shop_id>_korea_side.json 을 열어 한국 쪽 정보(name_kr, price_krw,
#    img_kr, kr_site)를 채운다

# 3) 엑셀 생성
python src/excel_builder.py output/<shop_id>_korea_side.json output/<shop_id>_비교.xlsx
```

## 개별 스크립트 단독 실행

```bash
# 상점 랭킹만 추출
python src/qoo10_ranking_scraper.py wline hanbikosupa

# 검색 + 저리뷰 상점 찾기만
python src/qoo10_low_review_shop_finder.py "라운드랩 백진주 수분크림"

# 개별 상품 상세정보 수집 (goods_no 또는 URL, 여러 개 가능)
python src/qoo10_item_detail_scraper.py 1187464238 1200512631

# 수집한 상품들을 공식 업로드 양식(EditItemList)으로 변환
# (data/Qoo10_EditItemList_template.xlsx 는 큐텐 공식 원본을 그대로 보관)
python src/edit_item_list_builder.py \
    data/Qoo10_EditItemList_template.xlsx \
    output/items \
    output/EditItemList_upload.xlsx

# 브랜드/카테고리 코드만 조회
python src/category_brand_matcher.py brand "ROUND LAB"
python src/category_brand_matcher.py category "스킨케어" "크림"
```

`edit_item_list_builder.py`가 만든 파일에서 `TODO`가 적힌 셀
(`category_number`, `price_yen`, `retail_price_yen`, `image_other_url`,
`item_description`, `item_weight` 등)은 반드시 사람이 채운 뒤 큐텐에
업로드해야 합니다.

## 주의사항

- Qoo10.jp는 단순 HTTP 요청(curl 등)을 봇으로 차단(523 에러)하므로
  모든 수집은 Playwright 브라우저 렌더링을 거칩니다.
- 랭킹 위젯은 AJAX 로드이므로 정적 HTML 파싱으로는 데이터가 잡히지 않습니다.
- 한국 공식몰 검색/가격 매칭은 사이트마다 구조가 달라 완전 자동화하지
  않았습니다. 검색 API(예: 네이버 검색 API) 연동은 추후 확장 지점입니다.
