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

[반영하는 값] 상품명 · 정가 · 판매가 · 제품사진
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
    by_goods = {str(c.get("goods_no")): c for c in collected if c.get("name")}
    print(f"[입력] 검증본 {len(rows):,}건 · 수집분 {len(collected):,}건"
          f"(이름 있는 것 {len(by_goods):,}건)")

    n_name = n_price = n_image = 0
    for r in rows:
        c = by_goods.get(str(r.get("goods_no")))
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

        r["page_collected_at"] = c.get("collected_at")
        r["page_via"] = c.get("via")

    print(f"[반영] 상품명 {n_name:,} · 가격 {n_price:,} · 사진 {n_image:,}")
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
