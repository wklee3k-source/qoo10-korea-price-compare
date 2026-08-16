"""
harvest_full_catalog.py

이미 발굴된 상점(discovery-live의 visited_shops)의 "전체상품"을 훑어서,
랭크5(베스트5)에서는 못 봤던 상품까지 추가로 건진다. 필터: 색조 제외,
화장품 카테고리 화이트리스트, 리뷰수 20 이하만 저장.

[설계원칙 유지] discovery-live와 완전히 분리된 별도 브랜치
(fullcatalog-live)에 저장한다 — discovery-live를 건드리면 발굴 워커와
push 경합이 생기고(과거실패 #2·#4), 병합 시점에 서로 다른 목적의
데이터가 뒤섞인다. 이 스크립트는 "읽기는 discovery-live에서, 쓰기는
fullcatalog-live에서"만 한다.

사용법:
    python harvest_full_catalog.py <state_suffix> <shop_id_1> [<shop_id_2> ...]
    -> output/fullcatalog_state_<suffix>.json 에 결과 누적저장(이어서 진행 가능)
"""

import json
import sys
import time
from pathlib import Path

from qoo10_shop_full_catalog import fetch_shop_full_catalog, ShopCatalogFailed

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

COLOR_COSMETIC_CATEGORIES = {"120000013", "120000014", "120000016"}
COSMETIC_ALLOWED_CATEGORIES = {
    "120000012",  # 스킨케어
    "120000017",  # UV케어
    "120000018",  # 바디・핸드・풋케어
    "120000019",  # 제모
    "120000020",  # 헤어
    "120000023",  # 맨즈뷰티
    # [v7.1.0] 네일(120000021)·향수(120000022) 제외 — 색조와 같은 이유.
    #  색상·호수·향으로 갈리는 상품군이라 이름만으로 같은 제품인지 알 수 없다.
}
REVIEW_MAX = 20  # 20 이하(0~20)만 저장 — 상품저장 필터(<20)와 다르게 이번엔 <=20
MAX_RETRIES = 3


def _state_path(suffix: str) -> Path:
    return OUTPUT_DIR / f"fullcatalog_state_{suffix}.json"


def _load_state(suffix: str) -> dict:
    p = _state_path(suffix)
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
        state.setdefault("failed_shops", {})
        return state
    return {"harvested_shops": [], "failed_shops": {}}


# [v7.66.0] 상품은 상태파일과 분리해서 "덧붙이기"로만 쌓는다.
#
# [실측 사고 2026-08-16] 수확이 계속 진전 없이 도는 진짜 원인.
# 상태파일이 99MB(상품 31만 건)까지 커졌는데, **상점 하나 끝날 때마다
# 그 99MB를 통째로 다시 썼다.** 읽고 쓰는 데만 3초, 배치 20개면
# 그것만 60초다. 워크플로도 매 반복 이 파일을 두 번 더 읽는다(2초씩).
#
# 게다가 파일은 계속 커진다. 지금 고쳐도 상품이 쌓이면 또 느려진다.
#
# 그래서 나눈다:
#   fullcatalog_state_N.json   진행 상태만 (수확한 상점 목록·실패 기록)
#                              -> 몇 MB 수준으로 유지, 매 상점마다 저장해도 싸다
#   fullcatalog_items_N.jsonl  상품 (한 줄에 한 건, 덧붙이기만)
#                              -> 아무리 커져도 쓰는 비용이 일정하다
#
# 검색어 재보충은 상품명과 브랜드명만 쓰므로(refill_discovery_keywords.py)
# 그 두 개만 남긴다. 전체 필드를 들고 있을 이유가 없다.
def _items_path(suffix: str) -> Path:
    return _state_path(suffix).with_name(f"fullcatalog_items_{suffix}.jsonl")


def _append_items(items: list[dict], suffix: str) -> None:
    """상품을 한 줄에 하나씩 덧붙인다. 파일이 커져도 비용이 안 늘어난다."""
    if not items:
        return
    with open(_items_path(suffix), "a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(
                {"goods_no": it.get("goods_no"),
                 "title": it.get("title"),
                 "brand": it.get("brand")},
                ensure_ascii=False) + "\n")


def _save_state(state: dict, suffix: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    _state_path(suffix).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def harvest(shop_ids: list[str], suffix: str) -> None:
    state = _load_state(suffix)
    harvested = set(state["harvested_shops"])
    failed_shops = state["failed_shops"]
    # 이미 담은 상품번호. jsonl을 한 번만 훑어 중복만 거른다.
    seen_goods = set()
    ip = _items_path(suffix)
    if ip.exists():
        with open(ip, encoding="utf-8") as f:
            for line in f:
                try:
                    seen_goods.add(json.loads(line).get("goods_no"))
                except ValueError:
                    continue
    total_kept = 0

    for shop_id in shop_ids:
        if shop_id in harvested:
            continue

        print(f"\n[상점진입] {shop_id} (실패이력={failed_shops.get(shop_id, 0)}회)")
        try:
            items = fetch_shop_full_catalog(shop_id)
            failed = False
        except ShopCatalogFailed as e:
            print(f"  [크롤실패-재시도대상] {e}", file=sys.stderr)
            items, failed = [], True
        except Exception as e:  # noqa: BLE001
            print(f"  [크롤실패-예상외오류] {type(e).__name__}: {e}", file=sys.stderr)
            items, failed = [], True

        if failed:
            failed_shops[shop_id] = failed_shops.get(shop_id, 0) + 1
            if failed_shops[shop_id] >= MAX_RETRIES:
                print(f"  [포기] {shop_id} {MAX_RETRIES}회 연속 실패 — 완료 처리")
                harvested.add(shop_id)
            _save_state(
                {"harvested_shops": list(harvested), "failed_shops": failed_shops},
                suffix,
            )
            continue

        keep_items = []
        for it in items:
            cat = it.get("category_gdlc_cd")
            if cat in COLOR_COSMETIC_CATEGORIES:
                continue
            if cat not in COSMETIC_ALLOWED_CATEGORIES:
                continue
            if it.get("review_count", 0) > REVIEW_MAX:
                continue
            if it.get("goods_no") in seen_goods:
                continue
            seen_goods.add(it.get("goods_no"))
            keep_items.append(it)

        _append_items(keep_items, suffix)
        total_kept += len(keep_items)
        print(f"  [완료] {shop_id}: 전체{len(items)}건 중 {len(keep_items)}건 저장"
              f"(이번 실행 누적 {total_kept}건)")
        harvested.add(shop_id)
        failed_shops.pop(shop_id, None)
        _save_state(
            {"harvested_shops": list(harvested), "failed_shops": failed_shops},
            suffix,
        )
        time.sleep(0.5)

    print(f"\n[DONE] 이번 실행 대상 {len(shop_ids)}개 중 처리완료 누적 {len(harvested)}개, 이번 실행 상품 {total_kept}건(전체 누적 {len(seen_goods)}건)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    state_suffix = sys.argv[1]
    target_shop_ids = sys.argv[2:]
    harvest(target_shop_ids, state_suffix)
