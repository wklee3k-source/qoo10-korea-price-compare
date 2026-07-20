"""
iterative_low_review_discovery.py

사용자가 정의한 알고리즘(v2, 명확화됨):

    1. (초기) 검색어로 큐텐 검색 → 리뷰 없음/3개 미만 상점 찾기
    2. 그 상점의 베스트5를 크롤링한다. 크롤링 시점에 카테고리가 색조
       (베이스메이크업/포인트메이크업/메이크업소품 — 반드시 옵션이 생기는
       계열)면 스킵, 옵션이 있으면 스킵. 통과한 상품은 원본 상품명 그대로 저장.
    3. 통과한 상품명에서 핵심단어를 추출한다(괄호/슬래시이후/수량단위/
       잡음단어 제거).
    4. 핵심단어로 재검색해서 리뷰 없음/3개 미만 상점을 또 찾는다.
    5. 그 상점들의 베스트5를 크롤링(2번부터 반복) — 상점은 전체 라운드에
       걸쳐 중복 방문 안 함.

사용법:
    python iterative_low_review_discovery.py "<초기검색어(일본어)>" <목표상품수> <output.xlsx> [최대상점수]
"""

import json
import re
import sys
from pathlib import Path

from qoo10_low_review_shop_finder import search_qoo10, parse_results
from qoo10_ranking_scraper import fetch_shop_ranking
from qoo10_item_detail_scraper import fetch_item_detail
from google_translate import GoogleTranslateSession
from hwahae_name_corrector import correct_name

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
STATE_PATH = OUTPUT_DIR / "discovery_state.json"

COLOR_COSMETIC_CATEGORIES = {"120000013", "120000014", "120000016"}
REVIEW_THRESHOLD = 3

STOPWORDS = ["選べる", "NEW", "セット", "公式", "限定", "特価", "お得", r"全\d+種", r"\bor\b", "×"]


def extract_core_keyword(title: str) -> str:
    t = title
    t = re.sub(r"[【\[（(][^】\])）]*[】\])）]", " ", t)
    t = re.split(r"\s*/", t)[0]
    t = re.sub(r"\d+\s*[枚mMｍＭlLｌＬgGｇＧ個点セ回本日%]+", " ", t)
    for sw in STOPWORDS:
        t = re.sub(sw, " ", t)
    t = re.sub(r"[,、]+\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


VOLUME_RE = re.compile(r"[\d.]+\s*(?:ml|g|枚|個|本)(?:[×xX+][\d.]+\s*(?:ml|g|個|箱|セット))*")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")

# 1단계: 브랜드 보호 — 번역기가 브랜드명을 엉뚱하게 오역하는 걸 막기 위해
# 번역 전에 플레이스홀더로 바꿔치기하고, 번역 후 원래 브랜드로 복원한다.
KNOWN_BRANDS = [
    "AOU", "VT", "d'Alba", "TIRTIR", "SK-II", "rom&nd", "fwee", "hince",
    "dasique", "KAHI", "ATRUE", "AGAIN ME",
]

# 2단계: 화장품 특수 용어(의성어/의태어 등, 일반 번역기가 못 알아듣는 것들)
# — 실측으로 확인된 것만 우선 등록. 번역 전에 플레이스홀더로 바꿔치기하고
# 번역 후 화장품 업계 정식 표기로 복원한다(예: "ぽよん" → 일반번역은 "포옹"/
# "포용"이 되지만 화장품 정식표기는 "뽀용").
COSMETIC_TERM_MAP = {
    "ぽよん": "뽀용",
}


def _protect_and_translate(text: str, translator) -> str:
    """브랜드/특수용어를 플레이스홀더로 보호한 뒤 번역하고, 번역 후 복원한다."""
    protected = text
    restore_map = {}

    for i, brand in enumerate(KNOWN_BRANDS):
        if brand in protected:
            placeholder = f"XBRAND{i}X"
            protected = protected.replace(brand, placeholder)
            restore_map[placeholder] = brand

    for i, (jp_term, kr_term) in enumerate(COSMETIC_TERM_MAP.items()):
        if jp_term in protected:
            placeholder = f"XTERM{i}X"
            protected = protected.replace(jp_term, placeholder)
            restore_map[placeholder] = kr_term

    translated = translator.translate(protected) or protected

    for placeholder, original in restore_map.items():
        # 번역기가 플레이스홀더 대소문자/띄어쓰기를 살짝 바꿀 수 있어서 느슨하게 매칭
        translated = re.sub(re.escape(placeholder), original, translated, flags=re.IGNORECASE)
        translated = re.sub(placeholder.replace("X", r"X\s*"), original, translated, flags=re.IGNORECASE)

    return translated


def crawl_shop_best5(shop_id: str) -> list[dict]:
    """상점 베스트5를 크롤링하고, 카테고리(색조)/옵션 필터를 즉시 적용한다.
    통과한 상품만 반환(원본 title 그대로 유지).

    [주의] 필터링 단계(fetch_item_detail)와 번역 단계(GoogleTranslateSession)를
    반드시 분리된 두 단계로 처리해야 한다 — 둘 다 각자 sync_playwright()를
    쓰는데, 한쪽 세션이 열려있는 동안 다른 쪽을 또 열면 asyncio 충돌이 난다
    (앞서 multi_source_finder.py에서도 같은 문제를 겪었다)."""
    try:
        ranking = fetch_shop_ranking(shop_id)
    except Exception:  # noqa: BLE001
        return []
    if not ranking:
        return []

    # 1단계: 필터링(카테고리/옵션/리뷰수) — fetch_item_detail만 사용
    passed = []
    for item in ranking:
        try:
            detail = fetch_item_detail(item["goods_no"], save_hires_image=False)
        except Exception:  # noqa: BLE001
            continue
        category = detail.get("category_gdlc_cd")
        has_options = detail.get("has_options")
        # review_count가 None인 건 에러가 아니라 "리뷰가 아예 없어서 JSON-LD의
        # aggregateRating 필드 자체가 안 나오는" 정상 상태다 → 0으로 취급한다
        review_count = detail.get("review_count")
        if review_count is None:
            review_count = 0
        if category in COLOR_COSMETIC_CATEGORIES:
            print(f"    [스킵-색조] {item['goods_no']} {item['title'][:30]}")
            continue
        if has_options:
            print(f"    [스킵-옵션] {item['goods_no']} {item['title'][:30]}")
            continue
        if review_count >= REVIEW_THRESHOLD:
            print(f"    [스킵-상품리뷰{review_count}] {item['goods_no']} {item['title'][:30]}")
            continue
        item["shop_id"] = shop_id
        item["category_gdlc_cd"] = category
        item["has_options"] = has_options
        item["review_count"] = review_count
        passed.append(item)

    if not passed:
        return []

    # 2단계: 번역 — GoogleTranslateSession만 사용(1단계가 끝난 뒤에 열림)
    # 브랜드/특수용어는 플레이스홀더로 보호한 뒤 번역(외부 AI 리뷰 반영)
    translated = {}
    with GoogleTranslateSession() as translator:
        for item in passed:
            title_no_bracket = BRACKET_RE.sub(" ", item["title"])
            title_no_bracket = re.split(r"\s*/", title_no_bracket)[0]
            vol_match = VOLUME_RE.search(title_no_bracket)
            volume = vol_match.group() if vol_match else ""
            title_for_translate = title_no_bracket
            if vol_match:
                title_for_translate = title_no_bracket[: vol_match.start()] + " " + title_no_bracket[vol_match.end():]

            brand_ja = item.get("brand", "")
            brand_kr = _protect_and_translate(brand_ja, translator) if brand_ja else ""
            core_kr = _protect_and_translate(title_for_translate.strip(), translator)
            translated[item["goods_no"]] = {"brand_kr": brand_kr.strip(), "core_kr": core_kr.strip(), "volume": volume}

    # 3단계: 화해로 정확한 명칭 검증 — hwahae_name_corrector가 자체적으로
    # sync_playwright를 여는 함수라서, 2단계(번역세션)가 완전히 닫힌 뒤에 실행한다.
    # [검색 전략] 브랜드 없이 "상품명만"으로 검색한다(브랜드를 넣으면 오역된
    # 브랜드명 때문에 검색이 0건이 되는 경우가 실측으로 확인됐다). 화해가
    # 브랜드까지 알려주므로 그걸 우선 채택하고, 화해에 브랜드가 없으면
    # 우리가 번역한 brand_kr로 보완한다.
    for item in passed:
        t = translated[item["goods_no"]]
        hwahae = correct_name(t["core_kr"])
        corrected = hwahae.get("corrected")
        hwahae_brand = hwahae.get("brand")

        if corrected:
            final_brand = hwahae_brand or t["brand_kr"] or item.get("brand", "")
            volume = hwahae.get("volume") or t["volume"]
            final_name = f"{final_brand} {corrected}".strip()
            if volume:
                final_name = f"{final_name} {volume}"
        else:
            # 화해에서 못 찾으면 원래 방식(브랜드+추측번역)으로 대체
            final_name = f"{t['brand_kr']} {t['core_kr']} {t['volume']}".strip()

        item["name_kr_verified"] = final_name
        item["hwahae_matched"] = bool(corrected)
        print(f"    [저장] {item['goods_no']} review={item['review_count']} {item['title'][:30]} -> {final_name}")

    return passed


def find_low_review_shops(keyword: str, visited_shops: set) -> list[dict]:
    html = search_qoo10(keyword)
    results = parse_results(html)
    low = [r for r in results if r["review_count"] < REVIEW_THRESHOLD]
    seen = {}
    for r in low:
        if r["shop_id"] not in visited_shops:
            seen[r["shop_id"]] = r
    return list(seen.values())


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"visited_shops": [], "all_products": [], "shop_urls": [], "pending_keywords": None, "seen_keywords": []}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(exist_ok=True, parents=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run(keyword_ja: str, target_products: int, max_shops: int | None = None):
    state = _load_state()
    visited_shops = set(state["visited_shops"])
    all_products = {p["goods_no"]: p for p in state["all_products"]}
    shop_urls = state["shop_urls"]
    pending_keywords = state["pending_keywords"] if state["pending_keywords"] is not None else [keyword_ja]
    seen_keywords = set(state["seen_keywords"])

    if state["visited_shops"]:
        print(f"[RESUME] 상점 {len(visited_shops)}개, 상품 {len(all_products)}건부터 이어서 진행")

    def save():
        _save_state(
            {
                "visited_shops": list(visited_shops),
                "all_products": list(all_products.values()),
                "shop_urls": shop_urls,
                "pending_keywords": pending_keywords,
                "seen_keywords": list(seen_keywords),
            }
        )

    while pending_keywords and len(all_products) < target_products:
        if max_shops and len(visited_shops) >= max_shops:
            print(f"\n[STOP] 최대 상점수({max_shops}) 도달")
            break

        kw = pending_keywords[0]  # 상점 처리 끝나야 pop (중간에 끊겨도 재개 가능)
        if kw in seen_keywords:
            pending_keywords.pop(0)
            save()
            continue

        print(f"\n[검색] {kw}")
        shops = find_low_review_shops(kw, visited_shops)
        print(f"  -> 신규 저리뷰 상점 {len(shops)}개")

        for shop in shops:
            if max_shops and len(visited_shops) >= max_shops:
                break
            if len(all_products) >= target_products:
                break
            shop_id = shop["shop_id"]
            visited_shops.add(shop_id)
            shop_urls.append(f"https://m.qoo10.jp/shop/{shop_id}")
            print(f"\n  [상점진입] {shop_id} (review={shop['review_count']})")

            passed_items = crawl_shop_best5(shop_id)
            for item in passed_items:
                if len(all_products) >= target_products:
                    break
                all_products[item["goods_no"]] = item
                core = extract_core_keyword(item["title"])
                if core:
                    pending_keywords.append(core)
            save()  # 매 상점마다 저장 (타임아웃 걸려도 이어서 진행 가능)

        seen_keywords.add(kw)
        pending_keywords.pop(0)
        save()

    print(f"\n[DONE] 상점 {len(visited_shops)}개 방문, 상품 {len(all_products)}건 확보")
    return list(all_products.values()), shop_urls


def export_excel(products: list[dict], out_path: str):
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment

    rows = [
        {
            "큐텐상품번호": p.get("goods_no"),
            "상점ID": p.get("shop_id"),
            "상품명(원본)": p.get("title"),
            "한글검증명칭": p.get("name_kr_verified"),
            "브랜드": p.get("brand"),
            "가격(엔)": p.get("price_jpy"),
            "리뷰수": p.get("review_count"),
            "옵션있음": p.get("has_options"),
            "카테고리코드": p.get("category_gdlc_cd"),
            "상품URL": p.get("item_url"),
        }
        for p in products
    ]
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="저리뷰상품", index=False)

    from openpyxl import load_workbook

    wb = load_workbook(out_path)
    ws = wb.active
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    widths = {"A": 14, "B": 16, "C": 45, "D": 40, "E": 16, "F": 10, "G": 8, "H": 10, "I": 14, "J": 45}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(out_path)
    print(f"[EXCEL] {out_path} 저장 완료 ({len(rows)}행)")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    keyword_ja = sys.argv[1]
    target = int(sys.argv[2])
    out_path = sys.argv[3]
    max_shops = int(sys.argv[4]) if len(sys.argv) > 4 else None

    products, shop_urls = run(keyword_ja, target, max_shops)
    export_excel(products, out_path)
    print("\n방문한 상점 URL:")
    for u in shop_urls:
        print(" ", u)


if __name__ == "__main__":
    main()