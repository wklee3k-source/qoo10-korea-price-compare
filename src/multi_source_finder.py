"""
multi_source_finder.py

4단계(한국 원가 매칭) — 다단계 소싱 오케스트레이터.

이전에는 danawa.com(가격비교사이트) 하나에만 의존했다. 이 스크립트는
외부 AI 리뷰에서 제안받은 "계층형(fallback) 검색" 구조를 실제로 적용한다:

    1순위: 무신사(musinsa.com) — 원래 허용 소싱처 목록에 있던 실제 판매처.
           결과가 있으면 이걸 우선 채택한다(별도 공식몰 판별 없이도
           "무신사 판매"라는 것 자체가 신뢰 가능한 출처).
    2순위: 다나와(danawa.com) — 무신사에 결과가 없을 때만 후보 발굴용으로
           보조 사용. 결과에는 항상 "판매처 확인 필요" 꼬리표가 붙는다.

이렇게 하면 다나와 사이트 구조가 바뀌거나 차단돼도 무신사 쪽은 영향을
안 받고, 반대의 경우도 마찬가지라 특정 사이트 장애에 대한 내구성이 생긴다.

사용법:
    python multi_source_finder.py "<검색어>"
    python multi_source_finder.py --batch <items_dir> <output.json> [<keywords_map.json>]
"""

import json
import sys
from pathlib import Path

import korea_price_finder as danawa
import musinsa_finder as musinsa


def find_price_layered(keyword: str, max_results: int = 5) -> dict:
    """무신사 먼저 시도하고, 없으면 다나와로 보조."""
    with musinsa.MusinsaSession() as ms:
        musinsa_results = ms.search(keyword, max_results)

    if musinsa_results:
        return {"source_used": "musinsa", "candidates": musinsa_results}

    danawa_results = danawa.find_price(keyword, max_results)
    return {"source_used": "danawa" if danawa_results else "none", "candidates": danawa_results}


def batch_find_layered(items_dir: str, out_path: str, keywords_map_path: str | None = None):
    out_file = Path(out_path)
    results = []
    done_goods_no = set()
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
        done_goods_no = {r["goods_no"] for r in results}
        print(f"[RESUME] 이미 처리된 {len(done_goods_no)}건부터 이어서 진행")

    keywords_map = {}
    if keywords_map_path and Path(keywords_map_path).exists():
        keywords_map = json.loads(Path(keywords_map_path).read_text(encoding="utf-8"))

    all_items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(items_dir).glob("*.json"))]
    todo = [it for it in all_items if it.get("goods_no") not in done_goods_no]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(all_items)}건")

    musinsa_hits = 0
    danawa_hits = 0
    needs_danawa = []  # (item, keyword) 무신사에서 못 찾은 것들만 모아서 나중에 처리

    # 1단계: 무신사 세션 하나로 전부 먼저 시도 (Playwright sync API는 세션
    # 두 개를 동시에 열면 asyncio 충돌이 나서 반드시 순차적으로 열어야 함)
    with musinsa.MusinsaSession() as ms:
        for item in todo:
            goods_no = item.get("goods_no")
            brand = item.get("brand_name") or ""
            name = item.get("item_name") or ""
            keyword = keywords_map.get(goods_no) or f"{brand} {name}"[:60]

            candidates = ms.search(keyword)
            if candidates:
                for c in candidates:
                    c["kr_site"] = "무신사 실판매(musinsa) — 허용 소싱처"
                results.append(
                    {
                        "goods_no": goods_no,
                        "qoo10_name": name,
                        "brand_name": brand,
                        "keyword_used": keyword,
                        "source_used": "musinsa",
                        "candidates": candidates,
                    }
                )
                danawa.atomic_write_json(out_file, results)
                musinsa_hits += 1
                print(f"[SEARCH] {goods_no}: {keyword} -> {len(candidates)}건(musinsa)")
            else:
                needs_danawa.append((goods_no, brand, name, keyword))
                print(f"[SEARCH] {goods_no}: {keyword} -> 무신사 없음, 다나와로 보류")

    # 2단계: 무신사에서 못 찾은 것만 다나와로 보조 검색
    if needs_danawa:
        with danawa.DanawaSession(use_cache=True) as ds:
            for goods_no, brand, name, keyword in needs_danawa:
                candidates = ds.search(keyword)
                source_used = "danawa" if candidates else "none"
                for c in candidates:
                    c["kr_site"] = "가격비교사이트 후보(danawa) — 실제 판매처/정가 여부 확인 필요"

                if source_used == "danawa":
                    danawa_hits += 1

                results.append(
                    {
                        "goods_no": goods_no,
                        "qoo10_name": name,
                        "brand_name": brand,
                        "keyword_used": keyword,
                        "source_used": source_used,
                        "candidates": candidates,
                    }
                )
                danawa.atomic_write_json(out_file, results)
                status = f"{len(candidates)}건(danawa)" if candidates else "후보없음"
                print(f"[SEARCH][fallback] {goods_no}: {keyword} -> {status}")

    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")
    print(f"       무신사 매칭 {musinsa_hits}건 / 다나와 매칭 {danawa_hits}건 / 매칭없음 {len(todo) - musinsa_hits - danawa_hits}건")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--batch":
        kw_map = sys.argv[4] if len(sys.argv) > 4 else None
        batch_find_layered(sys.argv[2], sys.argv[3], kw_map)
        return

    result = find_price_layered(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
