"""
match_review_builder.py

자동화가 아니라 "사람이 봐야 하는 영역"을 위한 게이트웨이 스크립트다.

지금까지의 자동화(검색 → 랭킹추출 → 상세정보 스크랩 → 브랜드/카테고리 매칭)는
"이게 진짜 같은 상품이 맞는지", "어떤 사진을 써도 되는지"를 판단하지 않는다.
이 두 가지는 오판 시 발생하는 리스크(오상품 등록, 이미지 저작권 침해)가 크므로
반드시 사람이 직접 눈으로 확인하고 승인해야 한다.

[레이아웃] 큐텐 원본(왼쪽) / 한국 매칭 후보(오른쪽) 두 칸으로 명확히 구분하고,
각 칸마다 큰 대표사진 1장 + 그 아래 작은 대체사진 1장(클릭하면 대표사진 자리를
대신 채택)을 보여준다. 오른쪽 여백에는 큰 "제외" 버튼만 둔다.

[조작] 사람이 할 일은 딱 두 가지뿐이다:
    1) 큐텐/한국 어느 쪽이든 쓸 사진을 클릭 -> 그 상품 채택 + 그 사진 사용
       (사진을 고르지 않은 상품은 저장 시 자동으로 제외 처리된다)
    2) 애초에 쓸 수 없는 상품이면 오른쪽 "제외" 버튼 클릭

[자동 필터] 큐텐 쪽에 옵션(색상/사이즈 등 선택형)이 있는 상품은 has_options=true로
표시되어 애초에 카드 자체를 만들지 않고 검수 대상에서 자동 제외한다.

사용법:
    python match_review_builder.py <items_dir> <korea_side.json> <output_prefix>

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
  .skipped {{ background:#fff8e6; border:1px solid #f0d98c; border-radius:8px; padding:10px 16px;
              margin-bottom:16px; font-size:13px; color:#7a5c00; }}
  .card {{ display:flex; gap:16px; background:#fff; border-radius:8px; padding:16px; margin-bottom:16px;
           box-shadow:0 1px 3px rgba(0,0,0,0.15); }}
  .card.excluded {{ opacity:0.4; }}
  .side {{ flex:1; }}
  .side h3 {{ margin:0 0 8px; font-size:14px; color:#555; }}
  .mainimg {{ cursor:pointer; border:3px solid transparent; border-radius:6px; display:inline-block; }}
  .mainimg.selected {{ border-color:#2a7d46; }}
  .mainimg img {{ max-width:100%; max-height:220px; object-fit:contain; border:1px solid #ddd; background:#fafafa; display:block; }}
  .altrow {{ margin-top:6px; }}
  .altimg {{ cursor:pointer; border:2px solid transparent; border-radius:4px; display:inline-block; }}
  .altimg.selected {{ border-color:#2a7d46; }}
  .altimg img {{ max-height:60px; object-fit:contain; border:1px solid #ddd; background:#fafafa; display:block; }}
  .name {{ font-size:13px; margin:8px 0 2px; }}
  .name-kr {{ font-size:12px; color:#2a5fa0; margin:0 0 4px; }}
  .price {{ font-weight:bold; color:#d0392a; }}
  .site {{ font-size:12px; color:#888; }}
  .goods_no {{ font-size:12px; color:#999; }}
  .checklist {{ flex:0 0 160px; border-left:1px dashed #ccc; padding-left:16px;
                display:flex; align-items:center; justify-content:center; }}
  .exclude-btn {{ background:#c0392b; color:#fff; border:none; padding:16px 12px;
                   border-radius:8px; font-size:14px; cursor:pointer; width:100%; line-height:1.4; }}
  .exclude-btn.active {{ background:#7f8c8d; }}
</style>
</head>
<body>

<div class="toolbar">
  <button onclick="saveDecisions()">💾 결정 파일 저장 (decisions.json 다운로드)</button>
  <span class="status" id="status"></span>
</div>

<h1>큐텐 ↔ 한국 상품 매칭 검수 ({count}건)</h1>
<p>쓸 사진을 클릭하면 그 상품은 그 사진으로 자동 채택됩니다. 아예 못 쓰는
상품이면 오른쪽 "제외" 버튼을 누르세요.</p>
{skip_notice}
"""

HTML_TAIL = """
<script>
function selectImage(goodsNo, side, url, el) {
  var card = el.closest('.card');
  card.querySelectorAll('.mainimg, .altimg').forEach(function(n) { n.classList.remove('selected'); });
  el.classList.add('selected');
  card.dataset.selectedSource = side;
  card.dataset.selectedUrl = url;
  setExcluded(card, false);
}

function toggleExclude(btn) {
  var card = btn.closest('.card');
  var nowExcluded = !card.classList.contains('excluded');
  setExcluded(card, nowExcluded);
}

function setExcluded(card, excluded) {
  var btn = card.querySelector('.exclude-btn');
  if (excluded) {
    card.classList.add('excluded');
    btn.classList.add('active');
    btn.textContent = '제외됨\\n(클릭해서 취소)';
  } else {
    card.classList.remove('excluded');
    btn.classList.remove('active');
    btn.textContent = '❌ 이 상품 제외';
  }
}

function saveDecisions() {
  var cards = document.querySelectorAll('.card');
  var results = [];
  cards.forEach(function(card) {
    var goodsNo = card.dataset.goods;
    var excluded = card.classList.contains('excluded');
    var hasSelection = !!card.dataset.selectedUrl;
    var included = !excluded && hasSelection;
    results.push({
      goods_no: goodsNo,
      qoo10_name: card.dataset.qoo10Name,
      kr_name: card.dataset.krName,
      kr_site: card.dataset.krSite,
      match_confirmed: included,
      image_usable: included,
      image_source: included ? card.dataset.selectedSource : null,
      final_image: included ? card.dataset.selectedUrl : null
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
  <div class="side">
    <h3>큐텐 원본</h3>
    <div class="mainimg" data-side="qoo10" onclick="selectImage('{goods_no}','qoo10','{qoo10_img1}',this)">
      <img src="{qoo10_img1}" alt="qoo10-1">
    </div>
    <div class="altrow">
      <div class="altimg" data-side="qoo10" onclick="selectImage('{goods_no}','qoo10','{qoo10_img2}',this)">
        <img src="{qoo10_img2}" alt="qoo10-2">
      </div>
    </div>
    <div class="name">{qoo10_name}</div>
    <div class="name-kr">→ {qoo10_name_kr}</div>
    <div class="price">{qoo10_price} 円</div>
    <div class="goods_no">goods_no: {goods_no}</div>
  </div>
  <div class="side">
    <h3>한국 매칭 후보</h3>
    <div class="mainimg" data-side="kr" onclick="selectImage('{goods_no}','kr','{kr_img1}',this)">
      <img src="{kr_img1}" alt="kr-1">
    </div>
    <div class="altrow">
      <div class="altimg" data-side="kr" onclick="selectImage('{goods_no}','kr','{kr_img2}',this)">
        <img src="{kr_img2}" alt="kr-2">
      </div>
    </div>
    <div class="name">{kr_name}</div>
    <div class="price">{kr_price} 원</div>
    <div class="site">{kr_site}</div>
  </div>
  <div class="checklist">
    <button class="exclude-btn" onclick="toggleExclude(this)">❌ 이 상품 제외</button>
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
    auto_skipped = []
    for kr in korea_side:
        goods_no = kr.get("goods_no") or kr.get("qoo10_goods_no")
        qoo10_item = items.get(goods_no, {})

        if qoo10_item.get("has_options") is True:
            auto_skipped.append((goods_no, qoo10_item.get("item_name", kr.get("name_ja", ""))))
            continue

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

    skip_notice = ""
    if auto_skipped:
        items_html = "".join(f"<li>{gid} — {name}</li>" for gid, name in auto_skipped)
        skip_notice = (
            f'<div class="skipped"><b>큐텐 옵션상품이라 자동 제외됨 ({len(auto_skipped)}건)</b>'
            f"<ul>{items_html}</ul></div>"
        )

    out_html = Path(f"{output_prefix}_review.html")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(
        HTML_HEAD.format(count=len(cards), skip_notice=skip_notice) + "".join(cards) + HTML_TAIL,
        encoding="utf-8",
    )
    return out_html, auto_skipped


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    items_dir, korea_side_path, output_prefix = sys.argv[1:4]
    html_path, auto_skipped = build_review(items_dir, korea_side_path, output_prefix)
    print(f"[INFO] 검수 페이지 -> {html_path}")
    if auto_skipped:
        print(f"[INFO] 옵션상품이라 자동 제외: {len(auto_skipped)}건")
        for gid, name in auto_skipped:
            print(f"       - {gid}: {name}")
    print("[INFO] 브라우저로 열어서 사진 클릭(=채택) 또는 제외 버튼 클릭 후 저장 버튼을 누르면")
    print("[INFO] decisions.json이 다운로드됩니다. 그 파일을 edit_item_list_builder.py에 넘기세요.")


if __name__ == "__main__":
    main()
