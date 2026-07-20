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
- `src/match_review_builder.py` — 큐텐 원본 vs 한국 매칭 후보를 나란히 보여주는 검수 HTML + 결정 템플릿 생성
- `src/margin_calculator.py` — 사용자의 기존 Q10_계산기.xlsx "마진율 먼저 설정" 산식을
  실측 분석해 그대로 재현. 국내구매가+무게+목표마진율로 큐텐판매가(price_yen)를 역산
- `src/stock_checker.py` — 한국 소싱처 상품페이지의 실제 품절 여부 자동 확인
  (숨김 배지 오탐 방지 로직 포함, 아래 "품절 자동체크" 참고)
- `src/edit_item_list_builder.py` — 검수에서 승인된 상품만, margin_calculator로 계산한
  가격까지 포함해서 공식 Qoo10_EditItemList.xlsx 양식에 데이터 행으로 반영
- `src/image_fetcher.py` — 상품 이미지 다운로드 및 JPEG 정규화
- `src/excel_builder.py` — 비교 데이터를 이미지 포함 엑셀로 출력
- `src/pipeline.py` — 위 단계를 순서대로 실행하는 오케스트레이터

### 참조 데이터 (data/)
- `brand_list.csv` — 큐텐 브랜드명(영/일/한) ↔ brand_number
- `qoo10_category_info.csv` — 큐텐 대/중/소카테고리명 ↔ category_number
- `oliveyoung_categories.json` — 올리브영 dispCatNo ↔ 카테고리명
- `Qoo10_EditItemList_template.xlsx` — 공식 업로드 양식 원본(헤더/가이드 행 보존용)

### 큐텐 상품페이지에서 직접 추출되는 항목 (2025-07 실증 완료)
- **category_number** — 상품페이지 hidden input(`img_search_gdsc_cd` 등)에 원 판매자가
  지정해둔 대/중/소카테고리 코드가 그대로 들어있다. `qoo10_category_info.csv`와 동일한
  코드 체계라 바로 재사용 가능 — 단, "원 판매자 기준" 분류이므로 최종 확인은 권장.
- **고화질 대표이미지** — 목록용 축소 이미지(`...g_400-w_g.jpg`)에서 사이즈 접미사를
  제거하면 원본 해상도 이미지가 나온다(실측: 400×408 9KB → 713×728 20KB). 검수 승인
  (`image_usable=true`) 시 이 고화질 URL을 자동으로 다운로드해
  `output/imgs_hires/<goods_no>_qoo10.jpg`에 리사이즈 없이 저장한다.
- **weight_hint** — 상품명 텍스트에서 ml/g/kg 패턴을 정규식으로 뽑아낸 "참고용" 값.
        큐텐 페이지에는 공식적인 무게 필드가 없어(무게는 셀러 비공개 정보) 신뢰도가
        낮다 — item_weight 칸에 그대로 쓰지 말고 참고만 할 것.

추가로 사용자의 실제 등록이력(322건, `Qoo10_ItemInfo_20260719204313.xlsx`)을 분석해
`data/weight_by_category.json`(카테고리별 실제 무게 중간값/범위)을 만들었다.
`edit_item_list_builder.py`는 상품명 추정치보다 이 실측 기반 참고표를 우선 사용한다.
같은 분석에서 `Shipping_number` 기본값이 템플릿 예시(0)가 아니라 실제로는
`741315`로 322건 전부 동일하게 쓰이고 있음을 확인해 기본값을 교정했다.

### 마진계산기 (margin_calculator.py)
사용자가 기존에 쓰던 `Q10_계산기.xlsx`의 "2. 마진율을 먼저 설정하는 방식" 시트를
openpyxl로 실제 셀 수식까지 읽어 그대로 재현했다(같은 파일의 "1. 판매가를 먼저
설정" 표는 환율 셀 참조가 깨져 있어 사용하지 않음). 실제 캐시값(국내구매가
32,900원, 무게 1.25kg, 목표마진율 12% → 큐텐판매가 6,134.89円)으로 재현 결과가
일치하는 것까지 검증했다.

```
price_yen = (K + P + Q + R − K/11) / (1 − 목표마진율 − 수수료율) / 환율 × 100
  K = 국내구매가(원)      P = 포장대행비(고정 2,080원)
  Q = 배대지배송비(원)    무게를 data/kse_shipping_rate.json 구간표에서 조회(반올림 상위 구간)
  R = 수출신고대행비(고정 165원)   환율 = 원/100엔(예: 900 = 9.00원/엔, 최신값으로 갱신 권장)
```

`edit_item_list_builder.py`에 `korea_side.json`(match_review_builder.py와 동일 형식,
각 항목의 `price_krw`를 국내구매가로 사용)을 넘기면, 카테고리 무게참고값과 결합해
`price_yen`을 자동으로 계산해 채운다. 무게참고값이나 국내구매가 중 하나라도 없으면
계산하지 않고 TODO로 남긴다. `retail_price_yen`(정가 연출용 가격)은 계산기 범위 밖의
비즈니스 판단이라 항상 TODO.

### [폐기됨] 한국 원가 자동검색 시도
2026-07-20에 다나와/무신사 등을 이용한 4단계(한국 원가 매칭) 자동검색을
시도했으나(korea_price_finder.py, musinsa_finder.py, multi_source_finder.py,
fuzzy_match.py 등), 100개 규모 실전 테스트에서 사람이 실제로 검수해보니
48건 중 47건이 오탐(엉뚱한 상품/가격 매칭)으로 확인되어 **전량 폐기**했다.
관련 스크립트, 데이터 파일(brand_db.json 등), GitHub Actions job을 모두
삭제했다. 4단계는 다시 사람이 web_search로 하나씩 확인하는 방식으로
되돌아간다 — 느리지만 정확한 쪽을 택했다.

### 품절 자동체크 (stock_checker.py)
한국 소싱처 상품페이지가 실제로 품절인지 자동으로 확인한다. **핵심 함정**:
cafe24 등 대부분의 쇼핑몰 플랫폼은 "품절"/"SOLD OUT" 배지 요소를 항상
DOM에 숨겨둔 채(`display:none`) 만들어두고, 실제 품절일 때만 보이게 바꾸는
구조라서 단순히 그 텍스트가 페이지에 "있는지"만 검사하면 대부분 오탐(false
positive)이 난다. 2026-07-19 실측 확인: 7개 상품 중 여러 곳에서 "품절"
텍스트 자체는 있었지만 전부 숨김 요소였고, 실제로는 전부 재고 있음이었다.
그래서 이 스크립트는 요소가 실제로 화면에 "보이는지(visible)"까지 확인한다.

```bash
# URL 직접 검사
python src/stock_checker.py "https://example.com/product/123"

# korea_side.json에 있는 소싱링크 전부 검사 (source_url 필드 필요)
python src/stock_checker.py --korea-side output/wline_korea_side.json
```
결과는 `output/stock_status.json`에 저장되며, 품절 발견 시 콘솔에 경고가 뜬다.
페이지 로드 자체가 실패하면 "재고있음"으로 함부로 단정하지 않고 "확인불가"로 남긴다.

### 2. AI가 봐야 하는 영역 (사람의 지시 아래 판단 필요, 자동화 스크립트 밖)
- 일본어 상품명에서 브랜드+고유명+용량만 남기는 핵심문구 추출
- 큐텐 상품과 한국 상품이 "동일 제품"이 맞는지 매칭 판단
- 검색결과 중 진짜 공식몰/브랜드스토어인지 구분(총판/병행수입 구별)
- `category_number`를 큐텐 페이지에서 추출하지 못했을 때(드묾) 대체 카테고리 확정

### 3. 사람이 봐야 하는 영역 (최종 확인/실행 — `match_review_builder.py`가 게이트 역할)
- **동일 제품 확인**: 큐텐 원본과 한국 매칭 후보를 나란히 보여주는 HTML을 눈으로 보고
  `match_confirmed`를 true/false로 결정. false거나 미결정이면 `edit_item_list_builder.py`가
  자동으로 해당 상품을 업로드 양식에서 제외한다.
- **이미지 사용 가능 여부 확인**: 이미지 출처가 공식몰/브랜드스토어가 맞는지, 워터마크·모델
  얼굴·저작권 표시가 없는지 확인 후 `image_usable`을 true/false로 결정. true가 아니면
  `image_main_url`이 자동으로 TODO 처리되어 검수 없는 이미지가 그대로 올라가지 않는다.
- 최종 리스팅 상점/상품 선정
- 가격 책정 — `price_yen`은 margin_calculator.py가 자동 계산하지만, 목표마진율/환율 값
  자체와 `retail_price_yen`(정가 연출) 결정은 여전히 사람의 비즈니스 판단 영역
- 상세설명(`item_description`)·서브이미지(`image_other_url`) 작성 — 셀러마다 상세페이지 구조가 달라 자동 추출 미지원
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

# 검수 페이지 생성: 큐텐 원본 vs 한국 매칭 후보를 눈으로 비교
python src/match_review_builder.py output/items output/<shop_id>_korea_side.json output/review/<shop_id>
# -> output/review/<shop_id>_review.html 를 열어 확인
# -> output/review/<shop_id>_decisions.json 에서 match_confirmed / image_usable 을 true/false로 채움

# 검수 승인된 상품만 공식 업로드 양식(EditItemList)으로 변환
# (data/Qoo10_EditItemList_template.xlsx 는 큐텐 공식 원본을 그대로 보관)
python src/edit_item_list_builder.py \
    data/Qoo10_EditItemList_template.xlsx \
    output/items \
    output/EditItemList_upload.xlsx \
    output/review/<shop_id>_decisions.json

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

## 전체 프로세스 (2026-07-19 10개 상품 실전 검증 완료)

```
1단계. 상품/상점 발굴          완전자동   batch_search_and_scrape.py
2단계. 큐텐 상세정보 수집       완전자동   qoo10_item_detail_scraper.py
3단계. 코드/무게 참고표 매칭    완전자동   category_brand_matcher.py, weight_by_category.json
4단계. 한국 원가 매칭          AI(검색)   공식몰/무신사에서 정가 확인, 가격비교사이트 금지
5단계. 사람 검수              사람       match_review_builder.py (사진 클릭=채택, 옵션상품 자동제외)
6단계. 가격 계산              완전자동   margin_calculator.py (실제 계산기 수식 재현, 원본 서식 유지)
7단계. 이미지 호스팅 업로드    완전자동   freeimage.host(iili.io) 업로드 후 링크 확보
8단계. 업로드 양식 생성        완전자동   edit_item_list_builder.py
9단계. 실제 큐텐 업로드        사람
```

### 실전 업로드에서 확인된 것

10개 중 7개 승인 → 실제 큐텐에 업로드 테스트 → 2건(셀리맥스·이니스프리) 반려:

```
실패사유: 商品名またはブランドにQAブランドが入力されている (QA브랜드)
```

**의미**: 이니스프리·셀리맥스처럼 유명 브랜드는 큐텐이 별도로 보호 지정해서,
brand_number에 그 코드를 넣으면 판매권한(공식 위임장 등)이 없는 계정은
자동 반려됩니다. 데이터 오류가 아니라 계정 권한 문제입니다.

**대응(확정)**: QA브랜드로 반려되면 —
1. `brand_number`는 비워둔다
2. 브랜드명을 `item_name` 맨 앞에 텍스트로 추가한다
   (예: `celimax ハートピンクトーンアップUVクリーム...`)

이렇게 하면 브랜드 코드 검증은 우회되면서도 상품명에는 브랜드가 그대로
노출된다. `edit_item_list_builder.py`는 아직 이 케이스를 자동 감지하지
않으므로, 반려 결과를 보고 수동으로 위 2가지를 고쳐야 한다(9단계 참고).

