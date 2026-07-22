"""
match_review_builder.py

자동화가 아니라 "사람이 봐야 하는 영역"을 위한 게이트웨이 스크립트다.

지금까지의 자동화(검색 → 랭킹추출 → 상세정보 스크랩 → 브랜드/카테고리 매칭)는
"이게 진짜 같은 상품이 맞는지", "어떤 사진을 써도 되는지"를 판단하지 않는다.
이 두 가지는 오판 시 발생하는 리스크(오상품 등록, 이미지 저작권 침해)가 크므로
반드시 사람이 직접 눈으로 확인하고 승인해야 한다.

[레이아웃] 큐텐 원본(왼쪽) / 한국 매칭 후보(오른쪽) 두 칸으로 명확히 구분한다.
큐텐 쪽은 실제로 존재하는 사진이 사실상 1장뿐이라(재크롤링으로 확인 — "추가
이미지"처럼 보이는 건 대부분 구매후기 사진이거나 같은 상점의 다른 상품
썸네일이라 이 상품과 무관함) 사진 1장만 정직하게 보여준다. 한국 쪽은 공식몰에
실제로 다른 사진이 여러 장 있는 경우가 많아 flex:1로 칸 너비를 채우며 나란히
보여주고, 남는 서브사진은 작게 줄바꿈하며 나열한다. 오른쪽 여백에는 큰 "제외"
버튼만 둔다.

[조작] 사람이 할 일은 딱 두 가지뿐이다:
    1) 큐텐/한국 어느 쪽이든 쓸 사진을 클릭 -> 그 상품 채택 + 그 사진 사용
       (사진을 고르지 않은 상품은 저장 시 자동으로 제외 처리된다)
    2) 애초에 쓸 수 없는 상품이면 오른쪽 "제외" 버튼 클릭

[자동 필터] 큐텐 쪽에 옵션(색상/사이즈 등 선택형)이 있는 상품은 has_options=true로
표시되어 애초에 카드 자체를 만들지 않고 검수 대상에서 자동 제외한다.

사용법:
    python match_review_builder.py <items_dir> <korea_side.json> <output_prefix> [main_count=2]

korea_side.json 각 항목이 지원하는 필드:
    goods_no, name_ja, name_kr, name_ja_translated(선택, 일본어 원문 번역),
    price_krw, img_kr, img_kr2(선택, 두번째 후보 이미지), kr_site
"""

import json
import re
import sys
from pathlib import Path

IMG_SIZE_SUFFIX_RE = re.compile(r"\.g_\d+-w(?:-st)?_g(?=\.\w+$)")


def _qoo10_image_variants(item: dict) -> list[str]:
    """큐텐은 상세페이지에 실제로 존재하는 사진이 사실상 1장뿐이다(직접 재크롤링해서
    확인함 — "추가 이미지"로 잡히는 건 대부분 구매후기 사진이거나 같은 상점의 다른
    상품 썸네일이라 이 상품 사진이 아니다). 그래서 사이즈만 다른 가짜 여러장을
    만들지 않고, 실제 원본 사진 1장만 정직하게 돌려준다."""
    real = item.get("image_main_url_hires") or item.get("image_main_url")
    return [real] if real else []


def _kr_image_variants(kr: dict) -> list[str]:
    gallery = kr.get("img_kr_list")
    if gallery:
        return [u for u in gallery if u]
    variants = []
    for key in ("img_kr", "img_kr2"):
        u = kr.get(key)
        if u and u not in variants:
            variants.append(u)
    return variants


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
  .mainrow {{ display:flex; gap:6px; }}
  .mainimg {{ flex:0 0 200px; max-width:200px; aspect-ratio:1; cursor:pointer; border:3px solid transparent;
              border-radius:6px; }}
  .mainimg.selected {{ border-color:#2a7d46; }}
  .mainimg img {{ width:100%; height:100%; object-fit:contain; border:1px solid #ddd; background:#fafafa; display:block; }}
  .altrow {{ margin-top:6px; display:flex; gap:5px; flex-wrap:wrap; }}
  .altimg {{ width:38px; height:38px; cursor:pointer; border:2px solid transparent; border-radius:4px; }}
  .altimg.selected {{ border-color:#2a7d46; }}
  .altimg img {{ width:100%; height:100%; object-fit:contain; border:1px solid #ddd; background:#fafafa; display:block; }}
  .name {{ font-size:13px; margin:8px 0 2px; }}
  .name-kr {{ font-size:12px; color:#2a5fa0; margin:0 0 4px; }}
  .price {{ font-weight:bold; color:#d0392a; }}
  .site {{ font-size:12px; color:#888; }}
  .goods_no {{ font-size:12px; color:#999; }}
  .checklist {{ flex:0 0 140px; border-left:1px dashed #ccc; padding-left:16px;
                display:flex; align-items:center; justify-content:center; }}
  .exclude-btn {{ background:#c0392b; color:#fff; border:none; padding:16px 10px;
                   border-radius:8px; font-size:14px; cursor:pointer; width:100%; line-height:1.4; }}
  .exclude-btn.active {{ background:#7f8c8d; }}
  .pagination {{ display:flex; gap:6px; flex-wrap:wrap; margin:16px 0; }}
  .pagination button {{ background:#fff; border:1px solid #ccc; border-radius:6px; padding:6px 12px;
                         font-size:13px; cursor:pointer; }}
  .pagination button.current {{ background:#2a7d46; color:#fff; border-color:#2a7d46; }}
  .page-group {{ display:none; }}
  .page-group.active {{ display:block; }}
</style>
</head>
<body>

<div class="toolbar">
  <button onclick="saveDecisions()">💾 결정 파일 저장 (decisions.json 다운로드)</button>
  <span class="status" id="status"></span>
</div>

<h1>큐텐 ↔ 한국 상품 매칭 검수 ({count}건, 페이지당 {page_size}개, 메인사진 {main_count}장)</h1>
<p>쓸 사진을 클릭하면 그 상품은 그 사진으로 자동 채택됩니다. 아예 못 쓰는
상품이면 오른쪽 "제외" 버튼을 누르세요. 저장 버튼을 누르면 전체 페이지의
결정사항이 한 번에 저장됩니다.</p>
{skip_notice}
<div class="pagination" id="pagination-top"></div>
"""

HTML_TAIL = """
<div class="pagination" id="pagination-bottom"></div>
<script>
var PAGE_SIZE = {page_size};
var currentPage = 1;

function setupPagination() {{
  var groups = document.querySelectorAll('.page-group');
  var totalPages = groups.length;
  function renderControls(containerId) {{
    var el = document.getElementById(containerId);
    el.innerHTML = '';
    for (var i = 1; i <= totalPages; i++) {{
      var btn = document.createElement('button');
      btn.textContent = i;
      if (i === currentPage) btn.classList.add('current');
      btn.onclick = (function(pageNum) {{ return function() {{ goToPage(pageNum); }}; }})(i);
      el.appendChild(btn);
    }}
  }}
  window.goToPage = function(n) {{
    currentPage = n;
    groups.forEach(function(g, idx) {{
      g.classList.toggle('active', idx === n - 1);
    }});
    renderControls('pagination-top');
    renderControls('pagination-bottom');
    window.scrollTo(0, 0);
  }};
  goToPage(1);
}}
setupPagination();

function selectImage(goodsNo, side, url, el) {{
  var card = el.closest('.card');
  card.querySelectorAll('.mainimg, .altimg').forEach(function(n) {{ n.classList.remove('selected'); }});
  el.classList.add('selected');
  card.dataset.selectedSource = side;
  card.dataset.selectedUrl = url;
  setExcluded(card, false);
}}

function toggleExclude(btn) {{
  var card = btn.closest('.card');
  var nowExcluded = !card.classList.contains('excluded');
  setExcluded(card, nowExcluded);
}}

function setExcluded(card, excluded) {{
  var btn = card.querySelector('.exclude-btn');
  if (excluded) {{
    card.classList.add('excluded');
    btn.classList.add('active');
    btn.textContent = '제외됨\\n(클릭해서 취소)';
  }} else {{
    card.classList.remove('excluded');
    btn.classList.remove('active');
    btn.textContent = '❌ 이 상품 제외';
  }}
}}

function saveDecisions() {{
  var cards = document.querySelectorAll('.card');
  var results = [];
  cards.forEach(function(card) {{
    var goodsNo = card.dataset.goods;
    var excluded = card.classList.contains('excluded');
    var hasSelection = !!card.dataset.selectedUrl;
    var included = !excluded && hasSelection;
    results.push({{
      goods_no: goodsNo,
      qoo10_name: card.dataset.qoo10Name,
      kr_name: card.dataset.krName,
      kr_site: card.dataset.krSite,
      match_confirmed: included,
      image_usable: included,
      image_source: included ? card.dataset.selectedSource : null,
      final_image: included ? card.dataset.selectedUrl : null
    }});
  }});
  var blob = new Blob([JSON.stringify(results, null, 2)], {{type: "application/json"}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = "decisions.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  document.getElementById('status').textContent =
    "저장됨 (" + new Date().toLocaleTimeString() + ") — 다운로드 폴더의 decisions.json 확인 (전체 " + cards.length + "건 포함)";
}}
</script>
</body>
</html>
"""


def _esc_attr(s: str) -> str:
    return (s or "").replace('"', "&quot;")


def _render_side(goods_no: str, side: str, label: str, images: list[str], main_count: int) -> str:
    images = [u for u in images if u] or [""]
    main_imgs = images[:main_count]
    sub_imgs = images[main_count:]

    main_html = "".join(
        f'<div class="mainimg" data-side="{side}" onclick="selectImage(\'{goods_no}\',\'{side}\',\'{u}\',this)">'
        f'<img src="{u}" alt="{side}-main"></div>'
        for u in main_imgs
    )
    sub_html = "".join(
        f'<div class="altimg" data-side="{side}" onclick="selectImage(\'{goods_no}\',\'{side}\',\'{u}\',this)">'
        f'<img src="{u}" alt="{side}-sub"></div>'
        for u in sub_imgs
    )
    sub_row = f'<div class="altrow">{sub_html}</div>' if sub_html else ""

    return f'<h3>{label}</h3><div class="mainrow">{main_html}</div>{sub_row}'


def build_review(items_dir: str, korea_side_path: str, output_prefix: str, main_count: int = 2, page_size: int = 20):
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
        qoo10_images = _qoo10_image_variants(qoo10_item)
        kr_images = _kr_image_variants(kr)

        qoo10_side_html = _render_side(goods_no, "qoo10", "큐텐 원본", qoo10_images, main_count)
        kr_side_html = _render_side(goods_no, "kr", "한국 매칭 후보", kr_images, main_count)

        card = f"""
<div class="card" data-goods="{goods_no}" data-qoo10-name="{_esc_attr(qoo10_name)}" data-kr-name="{_esc_attr(kr.get('name_kr', ''))}" data-kr-site="{_esc_attr(kr.get('kr_site', ''))}">
  <div class="side">
    {qoo10_side_html}
    <div class="name">{qoo10_name}</div>
    <div class="name-kr">→ {kr.get('name_ja_translated', '')}</div>
    <div class="price">{qoo10_item.get('price_jpy', kr.get('price_jpy', ''))} 円</div>
    <div class="goods_no">goods_no: {goods_no}</div>
  </div>
  <div class="side">
    {kr_side_html}
    <div class="name">{kr.get('name_kr', '')}</div>
    <div class="price">{kr.get('price_krw', '')} 원</div>
    <div class="site">{kr.get('kr_site', '')}</div>
  </div>
  <div class="checklist">
    <button class="exclude-btn" onclick="toggleExclude(this)">❌ 이 상품 제외</button>
  </div>
</div>
"""
        cards.append(card)

    skip_notice = ""
    if auto_skipped:
        items_html = "".join(f"<li>{gid} — {name}</li>" for gid, name in auto_skipped)
        skip_notice = (
            f'<div class="skipped"><b>큐텐 옵션상품이라 자동 제외됨 ({len(auto_skipped)}건)</b>'
            f"<ul>{items_html}</ul></div>"
        )

    # 카드를 page_size개씩 묶어서 page-group div로 감싼다 (1페이지만 보이고 나머지는 JS로 전환)
    page_groups = []
    for i in range(0, len(cards), page_size):
        chunk = cards[i:i + page_size]
        page_groups.append(f'<div class="page-group">{"".join(chunk)}</div>')

    out_html = Path(f"{output_prefix}_review.html")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(
        HTML_HEAD.format(count=len(cards), page_size=page_size, main_count=main_count, skip_notice=skip_notice)
        + "".join(page_groups)
        + HTML_TAIL.format(page_size=page_size),
        encoding="utf-8",
    )
    return out_html, auto_skipped


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    items_dir, korea_side_path, output_prefix = sys.argv[1:4]
    main_count = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    page_size = int(sys.argv[5]) if len(sys.argv) > 5 else 20

    html_path, auto_skipped = build_review(items_dir, korea_side_path, output_prefix, main_count, page_size)
    print(f"[INFO] 검수 페이지 -> {html_path} (메인사진 {main_count}장, 페이지당 {page_size}개)")
    if auto_skipped:
        print(f"[INFO] 옵션상품이라 자동 제외: {len(auto_skipped)}건")
        for gid, name in auto_skipped:
            print(f"       - {gid}: {name}")
    print("[INFO] 브라우저로 열어서 사진 클릭(=채택) 또는 제외 버튼 클릭 후 저장 버튼을 누르면")
    print("[INFO] decisions.json이 다운로드됩니다. 그 파일을 edit_item_list_builder.py에 넘기세요.")


if __name__ == "__main__":
    main()
