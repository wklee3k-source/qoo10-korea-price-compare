"""
build_review_batches.py

성공(구매링크 확보)한 항목들을 등급별로 나눈 뒤 100개씩 끊어서,
각 배치를 A_01.html, A_02.html, B_01.html, ... 형태의 별도 HTML파일로
만든다(v7.5.0 이전에는 review_01.html 식이라 열어보기 전엔 등급을 알 수 없었다). 기존 comparison/review.html
템플릿(카드형 UI + 20개씩 페이지네이션 JS)을 그대로 재사용한다.

사용법:
    python build_review_batches.py
        output/hwahae_verified_39.json 등을 읽어서
        comparison/batches/review_01.html, review_02.html, ... 을 생성한다.
"""

import re
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")
from collections import Counter  # noqa: E402
from build_review import build_pairs, esc, dim_minor_text, CONFIDENCE_TIERS  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
COMPARISON = BASE / "comparison"
# [발굴/수확 분리] 출력 폴더를 환경변수로 고른다. 발굴분은 docs/(기존
# 그대로, GitHub Pages 루트), 수확분은 QOO10_BATCH_SUBDIR=harvest를 줘서
# docs/harvest/에 따로 만든다 — 같은 프로세스를 그대로 타되 결과물만
# 분리해서 보이게 하는 게 목적.
BATCH_DIR = BASE / "docs" / os.environ.get("QOO10_BATCH_SUBDIR", "")
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
        # [v3.9.0] 브랜드를 확인하지 못한 건은 눈에 띄게 경고한다. 이 구간이
        # 오매칭이 숨는 곳이고(브랜드가 달라도 걸러낼 수단이 없다), 동시에
        # 채택하면 브랜드 대응이 사전에 새로 등록되는 구간이기도 하다.
        if p["brand_status"] == "unknown":
            brand_badge += ('<span class="badge warn">⚠ 브랜드 미확인 — 사진을 꼭 대조하세요'
                            ' (채택하면 브랜드 사전에 등록됩니다)</span>')
        elif p["brand_status"] == "mismatch":
            brand_badge += '<span class="badge mismatch">⚠ 브랜드가 다릅니다 — 오매칭 의심</span>'
        # 브랜드 등급과는 별개 축이므로 if/elif 사슬에 끼우지 않는다
        # (끼우면 브랜드 불일치 경고가 가려진다).
        # [v7.4.0] 제형을 한 줄로 보여준다. 등급만 보고는 무엇이 어긋났는지
        # 알 수 없어 매번 상품명을 다시 읽어야 했다.
        _qf = " · ".join(p.get("qoo10_forms") or []) or "?"
        _kf = " · ".join(p.get("kr_forms") or []) or "?"
        _fs = p.get("form_status") or "unknown"
        _fcolor = {"match": "#2a7d46", "mismatch": "#c0392b"}.get(_fs, "#a67a1f")
        _fmark = {"match": "일치", "mismatch": "다름"}.get(_fs, "확인불가")
        form_row = (f'<strong style="color:{_fcolor};">{esc(_qf)}</strong>'
                    f' <span style="color:#bbb;">/</span> '
                    f'<strong style="color:{_fcolor};">{esc(_kf)}</strong>'
                    f' <span class="badge tier-{"A" if _fs == "match" else "D" if _fs == "mismatch" else "B"}">'
                    f'{_fmark}</span>')
        _tier = p.get("tier") or "B"
        _tname, _tdesc = CONFIDENCE_TIERS.get(_tier, ("", ""))
        brand_badge = (f'<span class="badge tier-{_tier}">{_tier} · {_tname}</span>'
                       + brand_badge)
        if int(p.get("confidence", 4)) <= 1:
            brand_badge += ('<span class="badge warn">⚠ 신뢰도 낮음 — 다른 제품일 가능성이'
                            ' 높습니다. 사진·용량을 꼭 확인하세요</span>')
        if p.get("single_source_naver"):
            brand_badge += ('<span class="badge warn">⚠ 단독 매칭 — 네이버 한 곳만 찾았습니다.'
                            ' 사진을 반드시 대조하세요</span>')
        if p.get("naver_rematched"):
            brand_badge += ('<span class="badge unknown">재검색 매칭 — 다른 소스가 알려준'
                            ' 이름으로 찾은 건입니다</span>')
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
  <div class="card-header">
    <span class="badges">{brand_badge}{vol_badge}{qty_badge}{obsolete_badge}{set_badge}{trust_badge}</span>
    <button class="exclude-btn" onclick="toggleExclude(this)">❌ 이 상품 제외</button>
  </div>
  <div class="card-body">
  <div class="photo-row">
    <div class="photo-group qoo10">
      <div class="photo-group-label qoo10">큐텐 원본</div>
      {qoo10_img_html}
    </div>
    <div class="photo-group kr">
      <div class="photo-group-label kr">한국 구매처</div>
      <div class="photo-thumbs">{kr_img_html}</div>
    </div>
  </div>
  <table class="info-table">
    <tr>
      <td class="label">브랜드</td>
      <td>{esc(p.get('qoo10_brand') or '-')} <span style="color:#bbb;">/</span> <strong>{esc(p.get('kr_brand') or '-')}</strong></td>
    </tr>
    <tr>
      <td class="label">제형</td>
      <td>{form_row}</td>
    </tr>
    <tr>
      <td class="label">상품명</td>
      <td>
        {'<div class="vol-fix-preview">🔴 자동수정(용량/수량/발송지) 미리보기: ' + p['qoo10_title_highlighted'] + '</div>' if p.get('qoo10_title_highlighted') else ''}
        <textarea class="name-edit" data-goods="{goods_no}" rows="2">{p['qoo10_title']}</textarea>
        <div class="name-kr-readonly">{dim_minor_text(p['qoo10_name_kr'])}</div>
        <textarea class="kr-name-edit" data-goods="{goods_no}" rows="2">{esc(kr_name_full)}</textarea>
        {'<div class="name-kr-readonly" style="color:#a05fa0;">JP: ' + esc(p['kr_name_jp']) + '</div>' if p.get('kr_name_jp') else ''}
      </td>
    </tr>
    <tr>
      <td class="label">금액</td>
      <td><span class="price">{p['qoo10_price_jpy'] or '-'} 円</span> <span style="color:#bbb;">/</span> <span class="price">{p['kr_price'] or '-'} 원</span>{(' <span style="color:#999;font-size:12px;">정가 ' + f"{p['kr_list_price']:,}" + '원</span>') if p.get('kr_list_price') else ''}</td>
    </tr>
    <tr>
      <td class="label label-with-border">링크</td>
      <td class="label-with-border">
        {'<a href="' + p['qoo10_url'] + '" target="_blank">큐텐 원본</a>' if p.get('qoo10_url') else '-'}
        <span style="color:#bbb;">/</span>
        <a href="{p['kr_url']}" target="_blank">한국 구매처</a>
        <span class="site">({esc(kr_site_text)})</span>
        <span class="goods_no">goods_no: {goods_no}</span>
      </td>
    </tr>
  </table>
  </div>
</div>''')
    return "\n".join(cards_html) + '\n<div id="pagination-bottom" class="pagination"></div>'


# [v3.9.0] 브랜드 확실도 순 정렬.
#  브랜드가 사전으로 확인된 건(match)은 오매칭 가능성이 낮아 빠르게
#  넘길 수 있다. 반대로 판단불가(unknown)·불일치(mismatch)는 눈여겨봐야
#  하므로 뒤로 몰아 마지막에 집중해서 본다. 앞뒤를 섞어두면 주의가
#  분산돼 확실한 건에도 시간을 쓰게 된다.
#
#  뒤로 보낸 건이 오히려 더 값지다: 판단불가는 대부분 브랜드 사전에
#  없는 브랜드라, 여기서 채택하면 그 브랜드 대응이 사전에 새로 등록된다
#  (learn_from_decisions). 지금 사전 커버리지가 38.6%뿐이라, 이 구간을
#  검수할수록 다음 회차의 브랜드 판정 범위가 넓어진다.
BRAND_ORDER = {"match": 0, "unknown": 1, "mismatch": 2}
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def sort_by_brand_confidence(pairs: list[dict]) -> list[dict]:
    # 원래 순서를 보존하려고 인덱스를 함께 쓴다(같은 등급 안에서는
    # 기존 순서 그대로 — 정렬 때문에 매번 순서가 뒤바뀌면 어제 어디까지
    # 봤는지 알 수 없게 된다).
    # [v4.4.0] 1차 기준을 '매칭 신뢰도(confidence, 0~4)'로 바꾼다.
    #  브랜드만 보던 것을 브랜드+이름유사도+용량+단독여부를 합친 점수로
    #  대체했다. 검수페이지 2,100건 전수 점검 결과 신뢰도가 고르지 않아
    #  (확실 870 / 보통 818 / 의심 412), 섞여 있으면 확실한 건에도 같은
    #  주의를 쓰게 되고 정작 위험한 건을 놓친다.
    #  브랜드 등급은 동점일 때의 2차 기준으로 남긴다.
    return [x for _, _, _, x in sorted(
        ((-int(p.get("confidence", 0)),
          BRAND_ORDER.get(p.get("brand_status"), 1), i, p) for i, p in enumerate(pairs)),
        key=lambda t: (t[0], t[1], t[2]))]


def build_batches():
    all_pairs = build_pairs()
    all_pairs = sort_by_brand_confidence(all_pairs)
    dist = Counter(p.get("brand_status") for p in all_pairs)
    print(f"[정보] 성공(구매링크확보) 총 {len(all_pairs)}건 -> {BATCH_SIZE}개씩 배치 생성")
    print(f"[정렬] 브랜드 일치 {dist.get('match', 0)} / 판단불가 {dist.get('unknown', 0)} "
          f"/ 불일치 {dist.get('mismatch', 0)}")
    tdist = Counter(p.get("tier") for p in all_pairs)
    print(f"[등급] A 완전신뢰 {tdist.get('A', 0)} / B 확인필요 {tdist.get('B', 0)} "
          f"/ C 불일치의심 {tdist.get('C', 0)}")

    template = (COMPARISON / "review.html").read_text(encoding="utf-8")
    BATCH_DIR.mkdir(exist_ok=True, parents=True)

    # [v5.9.0] 한 페이지에 등급이 섞이지 않게 나눈다.
    #  예전엔 전체를 신뢰도 순으로 줄 세워 100개씩 잘랐다. 그러면 경계
    #  페이지에 'A 92 · B 8'처럼 섞여, 그 페이지에서 갑자기 검수 방식을
    #  바꿔야 한다. 등급별로 먼저 나눈 뒤 그 안에서 100개씩 자른다.
    #  마지막 페이지가 조금 비더라도 한 페이지 = 한 등급이 낫다.
    batches: list[list[dict]] = []
    for tier in ("A", "B", "C", "D"):
        group = [x for x in all_pairs if x.get("tier") == tier]
        for i in range(0, len(group), BATCH_SIZE):
            batches.append(group[i:i + BATCH_SIZE])
    # 등급이 없는 항목(예상치 못한 값)이 있으면 버리지 않고 뒤에 붙인다.
    known = {"A", "B", "C", "D"}
    leftovers = [x for x in all_pairs if x.get("tier") not in known]
    for i in range(0, len(leftovers), BATCH_SIZE):
        batches.append(leftovers[i:i + BATCH_SIZE])

    n_batches = len(batches)
    batch_meta = []  # 허브페이지용: 각 배치의 id/건수
    # [v7.5.0] 파일명을 등급별 번호로 짓는다(A_01, A_02, B_01 ...).
    #  예전엔 review_01~15라 어느 페이지가 어느 등급인지 열어봐야 알았다.
    #  등급별로 페이지를 나눠 놓았으니 이름도 그렇게 붙이는 게 맞다.
    # 옛 파일명(review_NN.html)이 남아 있으면 허브에 없는 유령 페이지가 된다.
    # ⚠️ *.html 을 통째로 지우면 허브(index.html)까지 날아간다. 배치 파일만
    # 골라서 지운다.
    for pattern in ("review_*.html", "A_*.html", "B_*.html", "C_*.html", "D_*.html", "X_*.html"):
        for stale in BATCH_DIR.glob(pattern):
            stale.unlink()
    tier_seq: dict = {}
    for i, batch in enumerate(batches):
        tier_of = (batch[0].get("tier") if batch else None) or "X"
        tier_seq[tier_of] = tier_seq.get(tier_of, 0) + 1
        batch_id = f"{tier_of}_{tier_seq[tier_of]:02d}"
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
        # [v4.6.0] 이 배치가 어떤 등급으로 이뤄져 있는지 허브에 보여준다.
        # 정렬이 신뢰도 순이라 앞 배치는 A로, 뒤 배치는 C로 채워진다 —
        # 어느 배치를 볼 때 시간이 더 드는지 미리 알 수 있다.
        tc = Counter(x.get("tier") for x in batch)
        label = " · ".join(f"{k} {tc[k]}" for k in ("A", "B", "C") if tc.get(k))
        batch_meta.append({"id": batch_id, "count": len(batch), "tier_label": label})
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
  <div class="batch-card-top" style="font-size:12px;color:#666;">
    <span>{b.get("tier_label", "")}</span>
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

