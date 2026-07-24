"""
build_review_batches.py

성공(구매링크 확보)한 항목들을 100개씩 끊어서, 각 배치를 review_01.html,
review_02.html, ... 형태의 별도 HTML파일로 만든다. 기존 comparison/review.html
템플릿(카드형 UI + 20개씩 페이지네이션 JS)을 그대로 재사용한다.

사용법:
    python build_review_batches.py
        output/hwahae_verified_39.json 등을 읽어서
        comparison/batches/review_01.html, review_02.html, ... 을 생성한다.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
from build_review import build_pairs, esc, dim_minor_text  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
COMPARISON = BASE / "comparison"
BATCH_DIR = COMPARISON / "batches"
BATCH_SIZE = 100


def render_cards(pairs: list[dict]) -> str:
    cards_html = []
    for p in pairs:
        goods_no = p["goods_no"]

        qoo10_img_html = (
            f'<div class="mainimg" data-side="qoo10" onclick="selectImage(\'{goods_no}\',\'qoo10\',\'{p["qoo10_image"]}\',this)">'
            f'<img src="{p["qoo10_image"]}" alt="qoo10" loading="lazy"></div>'
            if p.get("qoo10_image") else '<div class="noimg">이미지없음</div>'
        )

        kr_candidates = p.get("kr_candidates", [])
        kr_img_html = "".join(
            f'<div class="mainimg" data-side="kr" onclick="selectImage(\'{goods_no}\',\'kr\',\'{c["url"]}\',this)" title="{esc(c.get("mall"))}">'
            f'<img src="{c["url"]}" alt="kr" loading="lazy"></div>'
            for c in kr_candidates
        ) or '<div class="noimg">이미지없음</div>'

        brand_label = {"match": "일치", "mismatch": "불일치", "unknown": "판단불가"}[p["brand_status"]]
        brand_badge = f'<span class="badge {p["brand_status"]}">브랜드{brand_label}</span>'
        if p.get("vol_auto_corrected"):
            vol_badge = '<span class="badge unknown">용량 자동수정됨(업로드명 확인!)</span>'
        else:
            vol_badge = f'<span class="badge {"match" if p["vol_match"] else "mismatch"}">용량{"일치" if p["vol_match"] else "불일치"}</span>'
        obsolete_badge = '<span class="badge mismatch">단종</span>' if p.get("obsolete") else ""
        set_badge = '<span class="badge unknown">세트상품</span>' if p.get("is_set") else ""
        trust = p.get("kr_seller_trust")
        trust_badge = (
            f'<span class="badge {"match" if trust in ("공식몰", "브랜드직영추정", "신뢰채널", "스마트스토어") else "unknown"}">{trust or "판매처미확인"}</span>'
            if trust else ""
        )

        kr_site_text = p["kr_source"]
        if p.get("kr_mall"):
            kr_site_text += f" · {p['kr_mall']}"

        kr_name_val = p['kr_name'] or ''
        already_has_qty = bool(re.search(r"\d+\s*(개|매|セット|1\+1)", kr_name_val))
        qty_suffix = f" ({p['kr_qty']}개)" if p.get('kr_qty', 1) > 1 and not already_has_qty else ''
        kr_name_full = f"{kr_name_val}{qty_suffix}"

        cards_html.append(f'''
<div class="card" data-goods="{goods_no}" data-qoo10-name="" data-kr-name="" data-kr-site="{esc(kr_site_text)}">
  <div class="side">
    <h3>큐텐 원본{' — ' + esc(p['qoo10_brand']) if p.get('qoo10_brand') else ''}</h3>
    <div class="mainrow">{qoo10_img_html}</div>
    <div class="name-label">상품명(수정가능 — 업로드용 확정명):</div>
    {'<div class="vol-fix-preview">🔴 용량 자동수정: ' + p['qoo10_title_highlighted'] + '</div>' if p.get('qoo10_title_highlighted') else ''}
    <textarea class="name-edit" data-goods="{goods_no}" rows="2">{p['qoo10_title']}</textarea>
    <div class="name-kr-readonly">참고 한글번역: {dim_minor_text(p['qoo10_name_kr'])}</div>
    <div class="price">{p['qoo10_price_jpy'] or '-'} 円</div>
    <div class="goods_no">goods_no: {goods_no}</div>
  </div>
  <div class="side">
    <h3>한국 구매처{' — ' + esc(p['kr_brand']) if p.get('kr_brand') else ''} <span class="badges">{brand_badge}{vol_badge}{obsolete_badge}{set_badge}{trust_badge}</span></h3>
    <div class="mainrow">{kr_img_html}</div>
    <div class="name-label">한글 상품명(구매처 원본, 수정가능):</div>
    <textarea class="kr-name-edit" data-goods="{goods_no}" rows="2">{esc(kr_name_full)}</textarea>
    <div class="price">{p['kr_price'] or '-'} 원</div>
    <div class="site">{kr_site_text} — <a href="{p['kr_url']}" target="_blank">구매링크</a></div>
  </div>
  <div class="checklist">
    <button class="exclude-btn" onclick="toggleExclude(this)">❌ 이 상품 제외</button>
  </div>
</div>''')
    return "\n".join(cards_html) + '\n<div id="pagination-bottom" class="pagination"></div>'


def build_batches():
    all_pairs = build_pairs()
    print(f"[정보] 성공(구매링크확보) 총 {len(all_pairs)}건 -> {BATCH_SIZE}개씩 배치 생성")

    template = (COMPARISON / "review.html").read_text(encoding="utf-8")
    BATCH_DIR.mkdir(exist_ok=True, parents=True)

    n_batches = (len(all_pairs) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(n_batches):
        batch = all_pairs[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
        cards_str = render_cards(batch)
        new_html = re.sub(
            r"(<h1>.*?</h1>\n<p>큐텐 상품명은.*?</p>\n\n<div id=\"pagination-top\" class=\"pagination\"></div>\n\n).*?(\n<script>)",
            lambda m: m.group(1) + cards_str + m.group(2),
            template,
            flags=re.S,
        )
        new_html = re.sub(r"\(\d+건.*?\)", f"({len(batch)}건, 배치 {i+1}/{n_batches})", new_html, count=1)
        out_path = BATCH_DIR / f"review_{i+1:02d}.html"
        out_path.write_text(new_html, encoding="utf-8")
        print(f"  배치 {i+1:02d}: {len(batch)}건 -> {out_path.name}")

    print(f"[완료] 총 {n_batches}개 배치파일 생성 ({BATCH_DIR})")


if __name__ == "__main__":
    build_batches()
