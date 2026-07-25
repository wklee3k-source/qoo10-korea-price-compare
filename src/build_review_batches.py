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
    <div class="name-label">↓ 한글 상품명(구매처 원본, 수정가능) — 위 참고번역과 비교:</div>
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
    한다. file:// 로 로컬에서 열면 브라우저가 파일들끼리 localStorage를
    공유하므로(같은 출처로 취급), 이 허브 페이지에서 각 배치의 저장내역을
    직접 읽을 수 있다."""
    rows_html = "\n".join(
        f'<tr data-batch-id="{b["id"]}" data-total="{b["count"]}">'
        f'<td><a href="{b["id"]}.html" target="_blank" rel="noopener">{b["id"]}</a></td>'
        f'<td>{b["count"]}건</td>'
        f'<td class="progress-cell">-</td>'
        f'<td class="excluded-cell">-</td>'
        f'<td class="updated-cell">-</td>'
        f"</tr>"
        for b in batch_meta
    )
    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>검수 배치 관리 허브</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#1e1e1e; color:#eee; padding:24px; }}
  h1 {{ font-size:20px; }}
  table {{ border-collapse: collapse; width:100%; max-width:900px; margin-top:16px; }}
  th, td {{ border:1px solid #444; padding:10px 14px; text-align:left; }}
  th {{ background:#2a2a2a; }}
  tr:hover {{ background:#2a2a2a; }}
  a {{ color:#6ab0ff; text-decoration:none; font-weight:600; }}
  a:hover {{ text-decoration:underline; }}
  .summary {{ margin-top:20px; font-size:14px; color:#aaa; }}
  .done {{ color:#2ecc71; font-weight:700; }}
  .partial {{ color:#f39c12; }}
  .none {{ color:#777; }}
</style>
</head>
<body>
<h1>📋 검수 배치 관리 허브 (전체 {total}건, {len(batch_meta)}개 배치)</h1>
<p>배치를 클릭해서 검수를 이어가세요. 각 배치의 진행상황은 이 페이지를 열 때마다 자동으로 갱신됩니다(같은 브라우저에서 연 기록만 보임).</p>
<table>
  <thead><tr><th>배치</th><th>총 건수</th><th>진행상황(선택완료/전체)</th><th>제외처리</th><th>마지막 저장</th></tr></thead>
  <tbody>
{rows_html}
  </tbody>
</table>
<div class="summary" id="overall-summary"></div>

<script>
function refreshProgress() {{
  var rows = document.querySelectorAll('tr[data-batch-id]');
  var totalDone = 0, totalExcluded = 0, totalAll = 0;
  rows.forEach(function(row) {{
    var batchId = row.dataset.batchId;
    var total = parseInt(row.dataset.total, 10);
    totalAll += total;
    var key = 'qoo10_review_autosave_' + batchId;
    var raw;
    try {{ raw = localStorage.getItem(key); }} catch (e) {{ raw = null; }}
    var progressCell = row.querySelector('.progress-cell');
    var excludedCell = row.querySelector('.excluded-cell');
    var updatedCell = row.querySelector('.updated-cell');
    if (!raw) {{
      progressCell.innerHTML = '<span class="none">아직 안 열어봄</span>';
      excludedCell.textContent = '-';
      updatedCell.textContent = '-';
      return;
    }}
    var saved;
    try {{ saved = JSON.parse(raw); }} catch (e) {{ return; }}
    var results = saved.results || [];
    var confirmed = results.filter(function(r) {{ return r.match_confirmed; }}).length;
    var excluded = results.filter(function(r) {{ return r.excluded; }}).length;
    totalDone += confirmed;
    totalExcluded += excluded;
    var cls = confirmed >= total ? 'done' : (confirmed > 0 || excluded > 0 ? 'partial' : 'none');
    progressCell.innerHTML = '<span class="' + cls + '">' + confirmed + ' / ' + total + '</span>';
    excludedCell.textContent = excluded + '건';
    updatedCell.textContent = saved.savedAt ? new Date(saved.savedAt).toLocaleString() : '-';
  }});
  document.getElementById('overall-summary').textContent =
    '전체 진행: 선택완료 ' + totalDone + '건 / 제외 ' + totalExcluded + '건 / 전체 ' + totalAll + '건';
}}
refreshProgress();
</script>
</body>
</html>'''
    (BATCH_DIR / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build_batches()
