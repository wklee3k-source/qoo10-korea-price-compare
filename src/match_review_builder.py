"""
match_review_builder.py

자동화가 아니라 "사람이 봐야 하는 영역"을 위한 게이트웨이 스크립트다.

지금까지의 자동화(검색 → 랭킹추출 → 상세정보 스크랩 → 브랜드/카테고리 매칭)는
"이게 진짜 같은 상품이 맞는지", "어떤 사진을 써도 되는지"를 판단하지 않는다.
이 두 가지는 오판 시 발생하는 리스크(오상품 등록, 이미지 저작권 침해)가 크므로
반드시 사람이 직접 눈으로 확인하고 승인해야 한다.

이 스크립트는 상호작용 가능한 HTML 검수 페이지를 만든다:
    - 큐텐 이미지 2장(고화질/일반) + 한국 이미지 2장 중 실제 쓸 사진을 라디오로 선택
    - 동일 제품 여부(match_confirmed) / 이미지 사용 가능 여부(image_usable)를 라디오로 표시
    - 큐텐 원본 일본어 상품명 아래에 한글 번역을 함께 보여준다
    - 페이지 안의 "결정 파일 저장" 버튼을 누르면 브라우저가 현재 선택 상태를
      decisions.json 형식 그대로 다운로드한다(별도 JSON을 손으로 채울 필요 없음)

사용법:
    python match_review_builder.py <items_dir> <korea_side.json> <output_prefix>

    예) python match_review_builder.py output/items output/wline_korea_side.json output/review/wline
        -> output/review/wline_review.html  (이 파일을 열어서 검수 + 저장)

korea_side.json 각 항목이 지원하는 필드:
    goods_no, name_ja, name_kr, name_ja_translated(선택, 일본어 원문 번역),
    price_krw, img_kr, img_kr2(선택, 두번째 후보 이미지), kr_site
"""

import json
import sys
from pathlib import Path

HTML_HEAD = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>상품 매칭 검수</title>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; background:#f4f4f4; margin:0; padding:24px; }}
  h1 {{ font-size:18px; }}
  .toolbar {{ position:sticky; top:0; background:#fff; padding:12px 16px; margin-bottom:16px;
              border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.15); z-index:10; }}
  .toolbar button {{ background:#2a7d46; color:#fff; border:none; padding:10px 18px;
                      border-radius:6px; font-size:14px; cursor:pointer; }}
  .toolbar button:hover {{ background:#1e5c33; }}
  .toolbar .status {{ margin-left:12px; font-size:13px; color:#555; }}
  .card {{ background:#fff; border-radius:8px; padding:16px; margin-bottom:16px;
           box-shadow:0 1px 3px rgba(0,0,0,0.15); }}
  .card-top {{ display:flex; gap:16px; }}
  .side {{ flex:1; }}
  .side h3 {{ margin:0 0 8px; font-size:14px; color:#555; }}
  .imgrow {{ display:flex; gap:8px; }}
  .imgopt {{ flex:1; text-align:center; border:2px solid transparent; border-radius:6px; padding:4px; cursor:pointer; }}
  .imgopt.selected {{ border-color:#2a7d46; background:#eafbee; }}
  .imgopt img {{ max-width:100%; max-height:150px; object-fit:contain; background:#fafafa; border:1px solid #ddd; }}
  .imgopt .label {{ font-size:11px; color:#888; margin-top:4px; }}
  .name {{ font-size:13px; margin:8px 0 2px; }}
  .name-kr {{ font-size:12px; color:#2a5fa0; margin:0 0 4px; }}
  .price {{ font-weight:bold; color:#d0392a; }}
  .site {{ font-size:12px; color:#888; }}
  .goods_no {{ font-size:12px; color:#999; }}
  .checklist {{ margin-top:12px; padding-top:12px; border-top:1px dashed #ccc;
                display:flex; gap:24px; align-items:center; flex-wrap:wrap; }}
  .checklist label {{ font-size:13px; margin-right:8px; }}
  .checklist .group {{ display:flex; align-items:center; gap:6px; }}
  .note {{ flex:1; min-width:200px; }}
  .note input {{ width:100%; box-sizing:border-box; padding:6px; font-size:13px; }}
</style>
</head>
<body>

<div class="toolbar">
  <button onclick="saveDecisions()">💾 결정 파일 저장 (decisions.json 다운로드)</button>
  <span class="status" id="status"></span>
</div>

<h1>큐텐 ↔ 한국 상품 매칭 검수 ({count}건)</h1>
<p>각 상품마다 실제로 쓸 사진을 클릭해서 선택하고, 동일 제품 여부와 이미지 사용
가능 여부를 표시한 뒤 위의 저장 버튼을 누르면 됩니다.</p>
"""

HTML_TAIL = """
<script>
function selectImage(goodsNo, side, url, el) {
  document.querySelectorAll('.imgopt[data-goods="' + goodsNo + '"][data-side="' + side + '"]')
    .forEach(function(n) { n.classList.remove('selected'); });
  el.classList.add('selected');
  document.getElementById('selimg-' + side + '-' + goodsNo).value = url;
}

function saveDecisions() {
  var cards = document.querySelectorAll('.card');
  var results = [];
  cards.forEach(function(card) {
    var goodsNo = card.dataset.goods;
    var match = card.querySelector('input[name="match-' + goodsNo + '"]:checked');
    var imgUsable = card.querySelector('input[name="imgusable-' + goodsNo + '"]:checked');
    var note = card.querySelector('.note input').value;
    var selQoo10 = document.getElementById('selimg-qoo10-' + goodsNo).value;
    var selKr = document.getElementById('selimg-kr-' + goodsNo).value;
    var imgSource = card.querySelector('input[name="imgsource-' + goodsNo + '"]:checked');
    var imgSourceVal = imgSource ? imgSource.value : "qoo10";
    var finalImage = imgSourceVal === "kr" ? selKr : selQoo10;
    results.push({
      goods_no: goodsNo,
      qoo10_name: card.dataset.qoo10Name,
      kr_name: card.dataset.krName,
      kr_site: card.dataset.krSite,
      match_confirmed: match ? (match.value === "true") : null,
      image_usable: imgUsable ? (imgUsable.value === "true") : null,
      selected_qoo10_image: selQoo10 || null,
      selected_kr_image: selKr || null,
      image_source: imgSourceVal,
      final_image: finalImage || null,
      note: note
    });
  });
  var blob = new Blob([JSON.stringify(results, null, 2)], {type: "application/json"});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = "decisions.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  document.getElementById('status').textContent =
    "저장됨 (" + new Date().toLocaleTimeString() + ") — 다운로드 폴더의 decisions.json 확인";
}
</script>
</body>
</html>
"""

CARD_TEMPLATE = """
<div class="card" data-goods="{goods_no}" data-qoo10-name="{qoo10_name_attr}" data-kr-name="{kr_name_attr}" data-kr-site="{kr_site_attr}">
  <div class="card-top">
    <div class="side">
      <h3>큐텐 원본</h3>
      <div class="imgrow">
        <div class="imgopt selected" data-goods="{goods_no}" data-side="qoo10" onclick="selectImage('{goods_no}','qoo10','{qoo10_img1}',this)">
          <img src="{qoo10_img1}" alt="qoo10-1"><div class="label">고화질</div>
        </div>
        <div class="imgopt" data-goods="{goods_no}" data-side="qoo10" onclick="selectImage('{goods_no}','qoo10','{qoo10_img2}',this)">
          <img src="{qoo10_img2}" alt="qoo10-2"><div class="label">목록용(작음)</div>
        </div>
      </div>
      <div class="name">{qoo10_name}</div>
      <div class="name-kr">→ {qoo10_name_kr}</div>
      <div class="price">{qoo10_price} 円</div>
      <div class="goods_no">goods_no: {goods_no}</div>
      <input type="hidden" id="selimg-qoo10-{goods_no}" value="{qoo10_img1}">
    </div>
    <div class="side">
      <h3>한국 매칭 후보</h3>
      <div class="imgrow">
        <div class="imgopt selected" data-goods="{goods_no}" data-side="kr" onclick="selectImage('{goods_no}','kr','{kr_img1}',this)">
          <img src="{kr_img1}" alt="kr-1"><div class="label">사진 1</div>
        </div>
        <div class="imgopt" data-goods="{goods_no}" data-side="kr" onclick="selectImage('{goods_no}','kr','{kr_img2}',this)">
          <img src="{kr_img2}" alt="kr-2"><div class="label">사진 2</div>
        </div>
      </div>
      <div class="name">{kr_name}</div>
      <div class="price">{kr_price} 원</div>
      <div class="site">{kr_site}</div>
      <input type="hidden" id="selimg-kr-{goods_no}" value="{kr_img1}">
    </div>
  </div>
  <div class="checklist">
    <div class="group">
      동일 제품:
      <label><input type="radio" name="match-{goods_no}" value="true"> 맞음</label>
      <label><input type="radio" name="match-{goods_no}" value="false"> 아님</label>
    </div>
    <div class="group">
      이미지 사용 가능:
      <label><input type="radio" name="imgusable-{goods_no}" value="true"> 가능</label>
      <label><input type="radio" name="imgusable-{goods_no}" value="false"> 불가</label>
    </div>
    <div class="group">
      최종 이미지 출처:
      <label><input type="radio" name="imgsource-{goods_no}" value="qoo10" checked> 큐텐</label>
      <label><input type="radio" name="imgsource-{goods_no}" value="kr"> 한국</label>
    </div>
    <div class="note"><input type="text" placeholder="메모 (선택)"></div>
  </div>
</div>
"""


def _esc_attr(s: str) -> str:
    return (s or "").replace('"', "&quot;")


def build_review(items_dir: str, korea_side_path: str, output_prefix: str):
    items = {
        json.loads(p.read_text(encoding="utf-8"))["goods_no"]: json.loads(p.read_text(encoding="utf-8"))
        for p in Path(items_dir).glob("*.json")
    }
    korea_side = json.loads(Path(korea_side_path).read_text(encoding="utf-8"))

    cards = []
    for kr in korea_side:
        goods_no = kr.get("goods_no") or kr.get("qoo10_goods_no")
        qoo10_item = items.get(goods_no, {})

        qoo10_name = qoo10_item.get("item_name", kr.get("name_ja", ""))
        qoo10_img1 = qoo10_item.get("image_main_url_hires") or qoo10_item.get("image_main_url", "")
        qoo10_img2 = qoo10_item.get("image_main_url") or qoo10_img1

        kr_img1 = kr.get("img_kr", "")
        kr_img2 = kr.get("img_kr2") or kr_img1

        cards.append(
            CARD_TEMPLATE.format(
                goods_no=goods_no or "?",
                qoo10_name_attr=_esc_attr(qoo10_name),
                kr_name_attr=_esc_attr(kr.get("name_kr", "")),
                kr_site_attr=_esc_attr(kr.get("kr_site", "")),
                qoo10_img1=qoo10_img1,
                qoo10_img2=qoo10_img2,
                qoo10_name=qoo10_name,
                qoo10_name_kr=kr.get("name_ja_translated", ""),
                qoo10_price=qoo10_item.get("price_jpy", kr.get("price_jpy", "")),
                kr_img1=kr_img1,
                kr_img2=kr_img2,
                kr_name=kr.get("name_kr", ""),
                kr_price=kr.get("price_krw", ""),
                kr_site=kr.get("kr_site", ""),
            )
        )

    out_html = Path(f"{output_prefix}_review.html")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(
        HTML_HEAD.format(count=len(cards)) + "".join(cards) + HTML_TAIL,
        encoding="utf-8",
    )
    return out_html


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    items_dir, korea_side_path, output_prefix = sys.argv[1:4]
    html_path = build_review(items_dir, korea_side_path, output_prefix)
    print(f"[INFO] 검수 페이지 -> {html_path}")
    print("[INFO] 브라우저로 열어서 사진 선택 + 라디오 체크 후 '결정 파일 저장' 버튼을 누르면")
    print("[INFO] decisions.json이 다운로드됩니다. 그 파일을 edit_item_list_builder.py에 넘기세요.")


if __name__ == "__main__":
    main()

