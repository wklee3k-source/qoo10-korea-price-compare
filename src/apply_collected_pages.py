"""apply_collected_pages.py — 로컬에서 수집한 판매페이지 정보를 검증본에 반영한다.

[배경] 네이버 검색 API의 title·price 는 요약형이라 실제 판매페이지와 다르다.
    API  : 케라시스 히트 액티브 극손상 바르는 트리트먼트, , 1개
    실제 : 케라시스 히트액티브 극손상 헤어드라이 에센스, 220ml, 2개
    API  : 리쥬란 더마 힐러 모이스처 트리트먼트 앰플     30,400원
    실제 : 리쥬란 더마 힐러 모이스처 크림 60ml, 1개      36,100원(정가 38,000)
상품명이 다르면 검수에서 같은 상품인지 판단할 수 없고, 가격이 다르면
마진 계산이 틀린다.

GitHub Actions 는 네이버가 IP 대역째 막아(HTTP 429) 페이지를 못 연다.
그래서 수집은 로컬 PC에서 실제 크롬으로 하고(상품정보수집기), 그 결과를
여기서 검증본에 넣는다.

[반영하는 값] 상품명 · 정가 · 판매가 · 제품사진 · 구매링크(검색 모드)
그 밖의 값(평점·리뷰수·재고·카테고리)도 수집돼 있지만 검수 화면에 쓸 자리가
없어 넣지 않는다. 필요해지면 그때 붙인다.

[안전장치]
 · 이름이 빈 건은 건너뛴다(수집 실패 107건). 덮어쓰면 화면이 비어버린다.
 · 원래 값을 api_name/api_price 로 남긴다. 잘못 반영됐을 때 되돌릴 근거다.
 · 수집 시각을 함께 기록한다. 가격은 시간이 지나면 낡는다.

사용법:
    python apply_collected_pages.py <검증본.json> <수집결과.json> [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def apply(verified_path: str, collected_path: str, dry_run: bool = False) -> int:
    vpath = Path(verified_path)
    cpath = Path(collected_path)
    if not vpath.exists():
        print(f"[중단] {vpath} 없음")
        return 1
    if not cpath.exists():
        print(f"[중단] {cpath} 없음")
        return 1

    rows = json.loads(vpath.read_text(encoding="utf-8"))
    collected = json.loads(cpath.read_text(encoding="utf-8"))
    # [v7.48.8] 예전엔 이름 있는 것만 by_goods에 담아서, 수집기를 돌렸지만
    # 이름을 못 가져온 건(실측 2,696건 중 107건)은 흔적이 전혀 안 남았다.
    # 그러면 나중에 "아직 안 돌린 것"과 "돌렸는데 실패한 것"을 구분할 수
    # 없어서 보완 잔여 건수를 정확히 셀 수 없다(실측 2026-08-14: 잔여를
    # api_name 유무로 역추적하다가 숫자가 안 맞았음). 시도 자체를 기록하는
    # attempted와, 실제 값 반영용 by_goods를 분리한다.
    attempted = {str(c.get("goods_no")): c for c in collected if c.get("goods_no")}
    by_goods = {str(c.get("goods_no")): c for c in collected if c.get("name")}
    print(f"[입력] 검증본 {len(rows):,}건 · 수집분 {len(collected):,}건"
          f"(이름 있는 것 {len(by_goods):,}건, 시도 {len(attempted):,}건)")

    n_name = n_price = n_image = n_url = n_attempt = 0
    for r in rows:
        gno = str(r.get("goods_no"))
        # [v7.48.8] 수집기가 이 상품을 시도했다는 사실은 성공/실패와
        # 무관하게 먼저 기록한다 — 이게 "보완 잔여 건수"를 세는 유일한
        # 정확한 근거다.
        a = attempted.get(gno)
        if a:
            r["page_collect_attempted_at"] = a.get("collected_at")
            if not (a.get("name") or "").strip():
                r["page_collect_failed"] = True
                r["page_collect_error"] = a.get("error") or "이름 없음"
            else:
                r.pop("page_collect_failed", None)
                r.pop("page_collect_error", None)
            n_attempt += 1

        c = by_goods.get(gno)
        if not c:
            continue

        name = (c.get("name") or "").strip()
        if name and name != (r.get("name") or ""):
            # 되돌릴 수 있게 원래 값을 남긴다.
            r.setdefault("api_name", r.get("name"))
            r["name"] = name
            n_name += 1

        sale = c.get("sale_price")
        if isinstance(sale, (int, float)) and sale > 0:
            if str(r.get("price")) != str(int(sale)):
                r.setdefault("api_price", r.get("price"))
                n_price += 1
            r["price"] = int(sale)
            lst = c.get("list_price")
            # 정가가 판매가와 같으면 할인이 없는 것이라 굳이 남기지 않는다.
            if isinstance(lst, (int, float)) and int(lst) != int(sale):
                r["list_price"] = int(lst)

        img = (c.get("image") or "").strip()
        if img and img != (r.get("image_url") or ""):
            r.setdefault("api_image_url", r.get("image_url"))
            r["image_url"] = img
            n_image += 1

        # [v7.41.0] 검색 모드(수집기 v2.3.x) 결과에는 구매링크가 들어 있다.
        #  네이버쇼핑 API 종료로 링크를 못 얻는 건이 생겼는데, 로컬 크롬으로
        #  네이버를 검색해 스마트스토어·브랜드스토어 링크를 직접 찾아온다.
        #  기존 수집 모드에는 이 값이 없으므로(원래 링크를 알고 시작한다)
        #  있을 때만 넣는다.
        url = (c.get("final_url") or c.get("url") or "").strip()
        if url and not r.get("product_url"):
            r["product_url"] = url
            r["url_from_local_search"] = True
            # 공식 스토어 여부는 검수 때 판단 근거가 된다. 공식이 아니면
            #  재고·가격이 들쭉날쭉하고 가품 위험도 있다.
            if c.get("official") is not None:
                r["official_store"] = bool(c.get("official"))
            if c.get("seller"):
                r["mall"] = c.get("seller")
            n_url += 1

        r["page_collected_at"] = c.get("collected_at")
        r["page_via"] = c.get("via")

    print(f"[반영] 상품명 {n_name:,} · 가격 {n_price:,} · 사진 {n_image:,} · 구매링크 {n_url:,}")
    print(f"[수집시도 기록] {n_attempt:,}건 — 이 값(page_collect_attempted_at)으로 "
          f"'아직 수집기 안 돌린 건'을 정확히 셀 수 있다")
    if dry_run:
        print("[모의실행] 파일을 쓰지 않았다")
        return 0

    tmp = str(vpath) + ".tmp"
    Path(tmp).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(tmp).replace(vpath)   # 원자적 교체 — 쓰는 중 죽어도 원본이 안 깨진다
    print(f"[저장] {vpath}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(apply(sys.argv[1], sys.argv[2], "--dry-run" in sys.argv))
