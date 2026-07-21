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

# 화장품/뷰티 허용 대분류 코드(화이트리스트) — 이게 없으면 속옷/식품/잡화 같은
# 완전히 무관한 카테고리(예: "흰비둘기 거들", "롯데 가나 초콜릿 쿠키")가
# 그대로 통과하는 문제가 실측으로 확인됐다. 색조(위 3개)는 이미 별도로
# 제외하니 여기엔 안 넣는다.
COSMETIC_ALLOWED_CATEGORIES = {
    "120000012",  # 스킨케어
    "120000017",  # UV케어
    "120000018",  # 바디・핸드・풋케어
    "120000019",  # 제모
    "120000020",  # 헤어
    "120000021",  # 네일
    "120000022",  # 향수
    "120000023",  # 맨즈뷰티
}
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


SKIP_LOG_PATH = OUTPUT_DIR / "discovery_skip_log.json"
SEED_LOG_PATH = OUTPUT_DIR / "discovery_seed_log.json"


def _append_skip_log(entries: list[dict]):
    """스킵 사유를 파일에 계속 누적 저장한다(나중에 '왜 27건만 남았나' 같은
    질문에 바로 답할 수 있도록)."""
    existing = []
    if SKIP_LOG_PATH.exists():
        existing = json.loads(SKIP_LOG_PATH.read_text(encoding="utf-8"))
    existing.extend(entries)
    SKIP_LOG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_seed_log(entries: list[dict]):
    """어떤 상품(베스트5 중 하나)에서 어떤 검색어(시드)가 나왔는지 전부
    기록한다 — 필터 통과여부와 무관하게 시드는 항상 생성되므로, 이 로그를
    보면 "왜 상점 발굴이 이렇게 뻗어나갔는지/막혔는지"를 바로 추적할 수 있다."""
    existing = []
    if SEED_LOG_PATH.exists():
        existing = json.loads(SEED_LOG_PATH.read_text(encoding="utf-8"))
    existing.extend(entries)
    SEED_LOG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl_shop_best5(shop_id: str) -> list[dict]:
    """상점 베스트5를 전부 크롤링해서 반환한다(필터 통과여부와 무관하게
    5개 다 반환 — 사용자 지적사항 반영: 필터는 "최종 결과물에 넣을지"만
    결정해야지 "다음 검색 시드로 쓸지"까지 막으면 안 된다. 색조/옵션이라도
    다음 라운드 검색어로는 계속 써야 상점 발굴이 5개씩 계속 뻗어나간다).

    각 item에 passes_filter(bool)와 skip_reason을 달아서 반환하고, 최종
    상품목록에 넣을지는 호출하는 쪽(run())이 passes_filter를 보고 결정한다.

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

    all_items = []
    skip_entries = []
    for item in ranking:
        try:
            detail = fetch_item_detail(item["goods_no"], save_hires_image=False)
        except Exception as e:  # noqa: BLE001
            skip_entries.append({"shop_id": shop_id, "goods_no": item["goods_no"], "title": item["title"], "reason": f"상세조회실패: {e}"})
            continue

        category = detail.get("category_gdlc_cd")
        has_options = detail.get("has_options")
        # review_count가 None인 건 에러가 아니라 "리뷰가 아예 없어서 JSON-LD의
        # aggregateRating 필드 자체가 안 나오는" 정상 상태다 → 0으로 취급한다
        review_count = detail.get("review_count")
        if review_count is None:
            review_count = 0

        item["shop_id"] = shop_id
        item["category_gdlc_cd"] = category
        item["has_options"] = has_options
        item["review_count"] = review_count

        skip_reason = None
        if category in COLOR_COSMETIC_CATEGORIES:
            skip_reason = "색조카테고리"
        elif category not in COSMETIC_ALLOWED_CATEGORIES:
            skip_reason = "화장품카테고리아님"
        elif has_options:
            skip_reason = "옵션있음"
        elif review_count >= REVIEW_THRESHOLD:
            skip_reason = f"리뷰수{review_count}(3개이상)"

        item["passes_filter"] = skip_reason is None
        item["skip_reason"] = skip_reason

        if skip_reason:
            print(f"    [필터탈락-{skip_reason}] {item['goods_no']} {item['title'][:30]} (그래도 다음 시드로는 사용)")
            skip_entries.append({"shop_id": shop_id, "goods_no": item["goods_no"], "title": item["title"], "reason": skip_reason, "category": category})
        else:
            print(f"    [저장] {item['goods_no']} review={review_count} {item['title'][:30]}")

        all_items.append(item)  # 필터 통과여부와 무관하게 항상 추가(시드 생성용)

    if skip_entries:
        _append_skip_log(skip_entries)

    return all_items


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


def run(keyword_ja: str, target_products: int, max_shops: int | None = None, shops_per_keyword: int | None = None, seed_keywords: list[str] | None = None):
    state = _load_state()
    visited_shops = set(state["visited_shops"])
    all_products = {p["goods_no"]: p for p in state["all_products"]}
    shop_urls = state["shop_urls"]
    if state["pending_keywords"] is not None:
        pending_keywords = state["pending_keywords"]
    elif seed_keywords:
        pending_keywords = list(seed_keywords)
    else:
        pending_keywords = [keyword_ja]
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
        if shops_per_keyword:
            shops = shops[:shops_per_keyword]
        print(f"  -> 신규 저리뷰 상점 {len(shops)}개 (이 검색어에서 처리할 상점)")

        for shop in shops:
            if max_shops and len(visited_shops) >= max_shops:
                break
            if len(all_products) >= target_products:
                break
            shop_id = shop["shop_id"]
            visited_shops.add(shop_id)
            shop_urls.append(f"https://m.qoo10.jp/shop/{shop_id}")
            print(f"\n  [상점진입] {shop_id} (review={shop['review_count']})")

            crawled_items = crawl_shop_best5(shop_id)
            seed_entries = []
            for item in crawled_items:
                # 시드는 필터 통과여부와 무관하게 전부 생성(사용자 지적사항 반영)
                core = extract_core_keyword(item["title"])
                if core:
                    pending_keywords.append(core)
                    seed_entries.append(
                        {
                            "from_shop": shop_id,
                            "from_goods_no": item["goods_no"],
                            "from_title": item["title"],
                            "passes_filter": item.get("passes_filter"),
                            "seed_keyword": core,
                        }
                    )
                # 최종 상품목록에는 필터 통과한 것만 넣는다
                if item.get("passes_filter") and len(all_products) < target_products:
                    all_products[item["goods_no"]] = item
            if seed_entries:
                _append_seed_log(seed_entries)
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
    shops_per_keyword = int(sys.argv[5]) if len(sys.argv) > 5 else None

    products, shop_urls = run(keyword_ja, target, max_shops, shops_per_keyword)
    export_excel(products, out_path)
    print("\n방문한 상점 URL:")
    for u in shop_urls:
        print(" ", u)


if __name__ == "__main__":
    main()