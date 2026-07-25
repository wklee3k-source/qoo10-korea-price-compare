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
BATCH_DIR = BASE / "docs"
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
        elif p.get("vol_status") == "unknown":
            vol_badge = '<span class="badge unknown">용량판단불가</span>'
        else:
            vol_badge = f'<span class="badge {"match" if p["vol_match"] else "mismatch"}">용량{"일치" if p["vol_match"] else "불일치"}</span>'
        qty_badge = '<span class="badge unknown">수량 자동수정됨(업로드명 확인!)</span>' if p.get("qty_auto_corrected") else ''
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
        # [수정] 세트상품(is_set)은 extract_quantity가 "세트=최소2개"라는
        # 기본값을 주는데, 이건 "같은 상품 2개"가 아니라 "서로 다른 상품이
        # 묶인 것"이므로 "(2개)"를 붙이면 오해를 준다(실측 사례: "오일+폼"
        # 세트에 "(2개)"가 붙어서 "같은 걸 2개 준다"처럼 보였음).
        qty_suffix = f" ({p['kr_qty']}개)" if p.get('kr_qty', 1) > 1 and not already_has_qty and not p.get('is_set') else ''
        kr_name_full = f"{kr_name_val}{qty_suffix}"

        cards_html.append(f'''
<div class="card" data-goods="{goods_no}" data-qoo10-name="" data-kr-name="" data-kr-site="{esc(kr_site_text)}">
  <div class="side">
    <h3>큐텐 원본{' — ' + esc(p['qoo10_brand']) if p.get('qoo10_brand') else ''}</h3>
    <div class="mainrow">{qoo10_img_html}</div>
    <div class="name-label">상품명(수정가능 — 업로드용 확정명):</div>
    {'<div class="vol-fix-preview">🔴 자동수정(용량/수량) 미리보기: ' + p['qoo10_title_highlighted'] + '</div>' if p.get('qoo10_title_highlighted') else ''}
    <textarea class="name-edit" data-goods="{goods_no}" rows="2">{p['qoo10_title']}</textarea>
    <div class="price">{p['qoo10_price_jpy'] or '-'} 円</div>
    <div class="goods_no">goods_no: {goods_no}{' — <a href="' + p['qoo10_url'] + '" target="_blank">큐텐 원본 링크</a>' if p.get('qoo10_url') else ''}</div>
  </div>
  <div class="side">
    <h3>한국 구매처{' — ' + esc(p['kr_brand']) if p.get('kr_brand') else ''} <span class="badges">{brand_badge}{vol_badge}{qty_badge}{obsolete_badge}{set_badge}{trust_badge}</span></h3>
    <div class="mainrow">{kr_img_html}</div>
    <div class="name-kr-readonly">📎 참고 한글번역(큐텐원문): {dim_minor_text(p['qoo10_name_kr'])}</div>
    
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
    batch_meta = []  # 허브페이지용: 각 배치의 id/건수
    for i in range(n_batches):
        batch = all_pairs[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
        batch_id = f"review_{i+1:02d}"
        cards_str = render_cards(batch)
        new_html = re.sub(
            r"(<h1>.*?</h1>\n<p>큐텐 상품명은.*?</p>\n\n<div id=\"pagination-top\" class=\"pagination\"></div>\n\n).*?(\n<script>)",
            lambda m: m.group(1) + cards_str + m.group(2),
            template,
            flags=re.S,
        )
        new_html = re.sub(r"\(\d+건.*?\)", f"({len(batch)}건, 배치 {i+1}/{n_batches})", new_html, count=1)
        new_html = new_html.replace("__BATCH_ID__", batch_id)
        out_path = BATCH_DIR / f"{batch_id}.html"
        out_path.write_text(new_html, encoding="utf-8")
        batch_meta.append({"id": batch_id, "count": len(batch)})
        print(f"  배치 {i+1:02d}: {len(batch)}건 -> {out_path.name}")

    build_hub(batch_meta, len(all_pairs))
    print(f"[완료] 총 {n_batches}개 배치파일 + 허브페이지 생성 ({BATCH_DIR})")


def build_hub(batch_meta: list[dict], total: int):
    """모든 배치를 한 곳에서 관리하는 허브(인덱스) 페이지. 각 배치파일이
    localStorage에 자동저장해둔 진행상황(qoo10_review_autosave_<batch_id>)을
    그대로 읽어서, 배치별로 몇 건 처리했는지 보여주고 바로 이동할 수 있게
    한다. GitHub Pages(같은 출처)로 서빙되므로, 이 허브 페이지에서 각
    배치의 저장내역을 직접 읽을 수 있다."""
    cards_html = "\n".join(
        f'''<a class="batch-card" data-batch-id="{b["id"]}" data-total="{b["count"]}" href="{b["id"]}.html" target="_blank" rel="noopener">
  <div class="batch-card-top">
    <span class="batch-name">{b["id"]}</span>
    <span class="batch-total">{b["count"]}건</span>
  </div>
  <div class="progress-bar-track"><div class="progress-bar-fill" style="width:0%"></div></div>
  <div class="batch-card-bottom">
    <span class="progress-text">-</span>
    <span class="excluded-text">-</span>
  </div>
  <div class="updated-text">-</div>
</a>'''
        for b in batch_meta
    )
    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>검수 배치 관리 허브</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif;
    background: linear-gradient(160deg, #14161a 0%, #1c1f26 100%);
    color: #e8e8ea; padding: 32px 20px; margin: 0; min-height: 100vh;
  }}
  .wrap {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin: 0 0 6px; display:flex; align-items:center; gap:10px; }}
  .sub {{ color: #9a9ba3; font-size: 14px; margin: 0 0 28px; line-height:1.6; }}
  .overall {{
    background: linear-gradient(135deg, #2a3f5f 0%, #1f2a3d 100%);
    border: 1px solid #3a4a63; border-radius: 14px; padding: 20px 24px;
    margin-bottom: 28px; display: flex; gap: 32px; flex-wrap: wrap;
  }}
  .overall .stat {{ display:flex; flex-direction:column; gap:4px; }}
  .overall .stat .num {{ font-size: 28px; font-weight: 800; }}
  .overall .stat .lbl {{ font-size: 12px; color: #a9b4c7; }}
  .overall .stat.confirmed .num {{ color: #4ade80; }}
  .overall .stat.excluded .num {{ color: #f87171; }}
  .overall .stat.remaining .num {{ color: #facc15; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 16px;
  }}
  .batch-card {{
    display: block; background: #22252c; border: 1px solid #35383f; border-radius: 12px;
    padding: 16px 18px; text-decoration: none; color: inherit; transition: all 0.15s ease;
  }}
  .batch-card:hover {{ border-color: #6ab0ff; transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.35); }}
  .batch-card-top {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }}
  .batch-name {{ font-size: 16px; font-weight: 700; color: #fff; }}
  .batch-total {{ font-size: 12px; color: #8b8d95; }}
  .progress-bar-track {{ height: 8px; background: #35383f; border-radius: 4px; overflow: hidden; margin-bottom: 10px; }}
  .progress-bar-fill {{ height: 100%; background: linear-gradient(90deg, #4ade80, #22c55e); border-radius: 4px; transition: width 0.3s ease; }}
  .batch-card-bottom {{ display: flex; justify-content: space-between; font-size: 13px; }}
  .progress-text {{ color: #c7c9d1; font-weight: 600; }}
  .excluded-text {{ color: #f87171; }}
  .updated-text {{ font-size: 11px; color: #6b6d75; margin-top: 8px; }}
  .none-badge {{ color: #6b6d75; }}
</style>
</head>
<body>
<div class="wrap">
<h1>📋 검수 배치 관리 허브</h1>
<p class="sub">전체 {total}건 · {len(batch_meta)}개 배치로 나뉨. 배치 카드를 클릭하면 새 탭에서 열립니다.<br>진행상황은 이 페이지를 열 때마다 자동으로 갱신됩니다(이 브라우저에서 작업한 기록 + GitHub에 저장한 기록).</p>

<div class="overall" id="overall-stats">
  <div class="stat confirmed"><span class="num" id="stat-confirmed">-</span><span class="lbl">선택완료</span></div>
  <div class="stat excluded"><span class="num" id="stat-excluded">-</span><span class="lbl">제외처리</span></div>
  <div class="stat remaining"><span class="num" id="stat-remaining">-</span><span class="lbl">미처리</span></div>
</div>

<div class="grid">
{cards_html}
</div>
</div>

<script>
async function refreshProgress() {{
  var cards = document.querySelectorAll('.batch-card');
  var totalDone = 0, totalExcluded = 0, totalAll = 0;
  var ghToken = localStorage.getItem('qoo10_gh_save_token');

  for (var i = 0; i < cards.length; i++) {{
    var card = cards[i];
    var batchId = card.dataset.batchId;
    var total = parseInt(card.dataset.total, 10);
    totalAll += total;
    var key = 'qoo10_review_autosave_' + batchId;
    var raw = null;
    try {{ raw = localStorage.getItem(key); }} catch (e) {{}}

    if (ghToken) {{
      try {{
        var apiUrl = 'https://api.github.com/repos/wklee3k-source/qoo10-korea-price-compare/contents/comparison/decisions/' + batchId + '.json';
        var res = await fetch(apiUrl, {{headers: {{Authorization: 'token ' + ghToken}}}});
        if (res.ok) {{
          var data = await res.json();
          var content = decodeURIComponent(escape(atob(data.content)));
          raw = JSON.stringify({{savedAt: new Date().toISOString(), results: JSON.parse(content)}});
        }}
      }} catch (e) {{}}
    }}

    var fill = card.querySelector('.progress-bar-fill');
    var progressText = card.querySelector('.progress-text');
    var excludedText = card.querySelector('.excluded-text');
    var updatedText = card.querySelector('.updated-text');

    if (!raw) {{
      progressText.innerHTML = '<span class="none-badge">아직 안 열어봄</span>';
      excludedText.textContent = '';
      updatedText.textContent = '';
      fill.style.width = '0%';
      continue;
    }}
    var saved;
    try {{ saved = JSON.parse(raw); }} catch (e) {{ continue; }}
    var results = saved.results || [];
    var confirmed = results.filter(function(r) {{ return r.match_confirmed; }}).length;
    var excluded = results.filter(function(r) {{ return r.excluded; }}).length;
    totalDone += confirmed;
    totalExcluded += excluded;
    fill.style.width = Math.round((confirmed / total) * 100) + '%';
    progressText.textContent = confirmed + ' / ' + total;
    excludedText.textContent = excluded > 0 ? '제외 ' + excluded : '';
    updatedText.textContent = saved.savedAt ? '마지막 저장: ' + new Date(saved.savedAt).toLocaleString() : '';
  }}

  document.getElementById('stat-confirmed').textContent = totalDone;
  document.getElementById('stat-excluded').textContent = totalExcluded;
  document.getElementById('stat-remaining').textContent = totalAll - totalDone - totalExcluded;
}}
refreshProgress();
</script>
</body>
</html>'''
    (BATCH_DIR / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build_batches()

