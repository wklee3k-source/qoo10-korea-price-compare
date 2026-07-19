"""
match_review_builder.py

자동화가 아니라 "사람이 봐야 하는 영역"을 위한 게이트웨이 스크립트다.

지금까지의 자동화(검색 → 랭킹추출 → 상세정보 스크랩 → 브랜드/카테고리 매칭)는
"이게 진짜 같은 상품이 맞는지", "이 사진을 그대로 써도 되는지"를 판단하지 않는다.
이 두 가지는 오판 시 발생하는 리스크(오상품 등록, 이미지 저작권 침해)가 크므로
반드시 사람이 직접 눈으로 확인하고 승인해야 한다.

이 스크립트는:
    1) 큐텐 원본 상품(qoo10_item_detail_scraper.py 출력)과
       한국 쪽 후보 상품(korea_side.json, 사람이 채운 값)을 나란히 보여주는
       정적 HTML 리뷰 페이지를 만든다.
    2) 사람이 채워야 할 결정 템플릿(JSON)을 만든다.
       - match_confirmed : true/false/null  (동일 제품이 맞는가)
       - image_usable    : true/false/null  (이 이미지를 리스팅에 써도 되는가)
       - note            : 자유 메모 (예: "패키지 리뉴얼돼서 다름", "이미지 워터마크 있음")

edit_item_list_builder.py는 이 결정 파일을 읽어서, match_confirmed와
image_usable이 모두 true인 상품만 업로드 양식에 채운다. 승인되지 않은 상품은
자동으로 스킵되고 이유가 로그에 남는다.

사용법:
    python match_review_builder.py <items_dir> <korea_side.json> <output_prefix>

    예) python match_review_builder.py output/items output/wline_korea_side.json output/review/wline
        -> output/review/wline_review.html
        -> output/review/wline_decisions.json   (사람이 채울 템플릿)
"""

import json
import sys
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>상품 매칭 검수</title>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; background:#f4f4f4; margin:0; padding:24px; }}
  h1 {{ font-size:18px; }}
  .card {{ display:flex; gap:16px; background:#fff; border-radius:8px; padding:16px; margin-bottom:16px;
           box-shadow:0 1px 3px rgba(0,0,0,0.15); }}
  .side {{ flex:1; }}
  .side h3 {{ margin:0 0 8px; font-size:14px; color:#555; }}
  .side img {{ max-width:100%; max-height:220px; object-fit:contain; border:1px solid #ddd; background:#fafafa; }}
  .name {{ font-size:13px; margin:8px 0 4px; }}
  .price {{ font-weight:bold; color:#d0392a; }}
  .site {{ font-size:12px; color:#888; }}
  .checklist {{ flex:0 0 220px; border-left:1px dashed #ccc; padding-left:16px; font-size:13px; }}
  .checklist label {{ display:block; margin:6px 0; }}
  .goods_no {{ font-size:12px; color:#999; }}
</style>
</head>
<body>
<h1>큐텐 ↔ 한국 상품 매칭 검수 ({count}건)</h1>
<p>아래는 시각 확인용입니다. 실제 승인/반려는 <code>{decisions_file}</code> 파일에
match_confirmed / image_usable 값을 true 또는 false로 채워서 표시하세요.</p>
{cards}
</body>
</html>
"""

CARD_TEMPLATE = """
<div class="card">
  <div class="side">
    <h3>큐텐 원본</h3>
    <img src="{qoo10_img}" alt="qoo10">
    <div class="name">{qoo10_name}</div>
    <div class="price">{qoo10_price} 円</div>
    <div class="goods_no">goods_no: {goods_no}</div>
  </div>
  <div class="side">
    <h3>한국 매칭 후보</h3>
    <img src="{kr_img}" alt="korea">
    <div class="name">{kr_name}</div>
    <div class="price">{kr_price} 원</div>
    <div class="site">{kr_site}</div>
  </div>
  <div class="checklist">
    <label>☐ 동일 제품 맞음 (match_confirmed)</label>
    <label>☐ 이미지 사용 가능 (image_usable)</label>
    <label>메모: ___________</label>
  </div>
</div>
"""


def build_review(items_dir: str, korea_side_path: str, output_prefix: str):
    items = {
        json.loads(p.read_text(encoding="utf-8"))["goods_no"]: json.loads(p.read_text(encoding="utf-8"))
        for p in Path(items_dir).glob("*.json")
    }
    korea_side = json.loads(Path(korea_side_path).read_text(encoding="utf-8"))

    cards = []
    decisions = []
    for kr in korea_side:
        goods_no = kr.get("goods_no") or kr.get("qoo10_goods_no")
        qoo10_item = items.get(goods_no, {})

        cards.append(
            CARD_TEMPLATE.format(
                qoo10_img=qoo10_item.get("image_main_url", ""),
                qoo10_name=qoo10_item.get("item_name", kr.get("name_ja", "")),
                qoo10_price=qoo10_item.get("price_jpy", kr.get("price_jpy", "")),
                goods_no=goods_no or "?",
                kr_img=kr.get("img_kr", ""),
                kr_name=kr.get("name_kr", ""),
                kr_price=kr.get("price_krw", ""),
                kr_site=kr.get("kr_site", ""),
            )
        )
        decisions.append(
            {
                "goods_no": goods_no,
                "qoo10_name": qoo10_item.get("item_name", kr.get("name_ja", "")),
                "kr_name": kr.get("name_kr", ""),
                "kr_site": kr.get("kr_site", ""),
                "match_confirmed": None,  # 사람이 true/false로 채움
                "image_usable": None,  # 사람이 true/false로 채움
                "note": "",
            }
        )

    out_html = Path(f"{output_prefix}_review.html")
    out_decisions = Path(f"{output_prefix}_decisions.json")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    out_html.write_text(
        HTML_TEMPLATE.format(
            count=len(decisions),
            decisions_file=out_decisions.name,
            cards="".join(cards),
        ),
        encoding="utf-8",
    )
    out_decisions.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_html, out_decisions


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    items_dir, korea_side_path, output_prefix = sys.argv[1:4]
    html_path, decisions_path = build_review(items_dir, korea_side_path, output_prefix)
    print(f"[INFO] 검수 페이지 -> {html_path}")
    print(f"[INFO] 결정 템플릿 -> {decisions_path}")
    print("[INFO] 사람이 이 HTML을 열어 눈으로 비교하고, 결정 JSON의 match_confirmed / image_usable을 채워주세요.")


if __name__ == "__main__":
    main()
