"""
build_review.py — comparison_pairs.json과 review.html을 일관된 로직으로
생성한다. 이전엔 대화할 때마다 인라인 파이썬으로 즉석에서 만들다 보니
같은 버그(용량필드 비어있을때 상품명에서 재추출 안 함 등)가 반복됐다.
이 스크립트로 고정해서 재사용한다.

사용법:
    python build_review.py
        output/discovery_state.json + archive/*.json (큐텐)
        output/hwahae_verified_39.json (국내검증결과)
        output/hwahae_input_39.json (참고 한글번역)
    을 읽어서 output/comparison_pairs.json과 comparison/review.html을 만든다.
"""

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "output"
DATA = BASE / "data"
COMPARISON = BASE / "comparison"

# 브랜드명 표기 변형(네이버/화해가 사전과 다른 표기를 쓰는 경우) — 실측으로
# 계속 채워나간다. 예: La'dor(사전표기 "라도르")를 네이버는 "아도르"로 표기.
BRAND_ALIASES = {
    "라도르": ["아도르"],
}


def load_qoo10_products():
    products = json.loads((OUTPUT / "discovery_state.json").read_text(encoding="utf-8"))["all_products"]
    archive_dir = OUTPUT / "archive"
    if archive_dir.exists():
        for f in archive_dir.glob("discovery_archive_*.json"):
            products.extend(json.loads(f.read_text(encoding="utf-8")))
    return {p["goods_no"]: p for p in products}


def extract_volume_ml(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mL|ml|g|L)", text)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2).lower()
    return num * 1000 if unit == "l" else num


def extract_quantity(text: str) -> int:
    """제목/상품명에서 실제 수량(묶음개수)을 추출한다(한글 상품명에 개수를
    명시적으로 표시하기 위함)."""
    if not text:
        return 1
    text_wo_choice = re.sub(r"\d+種(類)?から\d+つ選択", "", text)
    m = re.search(r"(\d+)\s*\+\s*(\d+)", text_wo_choice)
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"(\d+)\s*(個|개|매|입|병|枚|本|장)\b", text_wo_choice)
    if m:
        return int(m.group(1))
    if re.search(r"세트|SET|Set|1\+1", text_wo_choice):
        return 2
    return 1


def check_brand(orig_brand: str, kr_brand_text: str, brand_dict: dict) -> str:
    if not orig_brand:
        return "unknown"  # 원본에 브랜드 정보 자체가 없으면 "불일치"가 아니라 "판단불가"
    kr_brand_lower = (kr_brand_text or "").lower()
    expected = brand_dict.get(orig_brand, "")
    if expected:
        candidates = [expected] + BRAND_ALIASES.get(expected, [])
        if any(c.lower() in kr_brand_lower for c in candidates):
            return "match"
        return "mismatch"
    orig_alnum = re.sub(r"[^a-z0-9]", "", orig_brand.lower())
    kr_alnum = re.sub(r"[^a-z0-9]", "", kr_brand_lower)
    if orig_alnum and len(orig_alnum) >= 2 and orig_alnum in kr_alnum:
        return "match"
    if re.search(r"[\u30A0-\u30FF\u3040-\u309F]", orig_brand):
        return "unknown"
    return "mismatch"


def build_pairs():
    qoo10_by_goods = load_qoo10_products()
    kr = json.loads((OUTPUT / "hwahae_verified_39.json").read_text(encoding="utf-8"))
    brand_dict = json.loads((DATA / "brand_translations_learned.json").read_text(encoding="utf-8"))
    brand_dict.pop("_설명", None)
    brand_dict.pop("_아도르_참고", None)

    translations = {}
    input_path = OUTPUT / "hwahae_input_39.json"
    if input_path.exists():
        for x in json.loads(input_path.read_text(encoding="utf-8")):
            translations[x["goods_no"]] = x.get("translated_kr", "")

    pairs = []
    stats = {"no_link": 0, "sold_out": 0, "no_qoo10_match": 0, "ok": 0}
    for x in kr:
        if not x.get("product_url"):
            stats["no_link"] += 1
            continue
        if x.get("in_stock") is False:
            stats["sold_out"] += 1
            continue
        q = qoo10_by_goods.get(x["goods_no"])
        if not q:
            stats["no_qoo10_match"] += 1
            continue

        stats["ok"] += 1

        # 표시용 한글 상품명: 구매처(네이버) 원본 상품명을 최우선으로 쓴다.
        # 승자가 화해/Exa일 때는 그쪽 name/volume 필드가 부실한 경우가 많고
        # (개수·용량 누락), 실제 구매링크의 원본 제목엔 정확한 정보가 이미
        # 들어있는 경우가 대부분이라, 그걸 그대로 보여주는 게 가장 정확하다.
        naver_original_name = (x.get("candidates_summary") or {}).get("naver")
        kr_name_display = naver_original_name or x.get("name") or ""

        qoo10_vol = extract_volume_ml(q["title"])
        kr_vol = extract_volume_ml(kr_name_display) or extract_volume_ml(x.get("volume") or "")
        vol_match = qoo10_vol is not None and kr_vol is not None and abs(qoo10_vol - kr_vol) < 0.1

        orig_brand = q.get("brand", "")
        brand_status = check_brand(orig_brand, x.get("brand", ""), brand_dict)

        kr_candidates = x.get("image_candidates") or []
        if not kr_candidates and x.get("image_url"):
            kr_candidates = [{"url": x["image_url"], "mall": x.get("mall"), "link": x.get("product_url")}]

        kr_qty = extract_quantity(kr_name_display)
        pairs.append({
            "goods_no": x["goods_no"], "qoo10_title": q["title"], "qoo10_brand": orig_brand,
            "qoo10_image": q.get("image_url"), "qoo10_price_jpy": q.get("price_jpy"), "qoo10_url": q.get("item_url"),
            "qoo10_name_kr": translations.get(x["goods_no"], ""),
            "kr_brand": x.get("brand"), "kr_name": kr_name_display,
            "kr_volume": x.get("volume") or (f"{int(kr_vol)}ml" if kr_vol else ""),
            "kr_qty": kr_qty,
            "kr_candidates": kr_candidates, "kr_price": x.get("price"), "kr_url": x.get("product_url"),
            "kr_mall": x.get("mall"), "kr_seller_trust": x.get("seller_trust"),
            "kr_source": x.get("winner_source"), "vol_match": vol_match, "brand_status": brand_status,
            "obsolete": x.get("obsolete"),
        })

    print(f"[통계] 구매링크없음={stats['no_link']} 품절={stats['sold_out']} "
          f"큐텐매칭안됨={stats['no_qoo10_match']} 최종={stats['ok']}건")
    (OUTPUT / "comparison_pairs.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return pairs


def esc(s):
    if s is None:
        return ""
    return str(s).replace('"', "&quot;").replace("'", "&#39;")


def build_html(pairs: list[dict]):
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
        vol_badge = f'<span class="badge {"match" if p["vol_match"] else "mismatch"}">용량{"일치" if p["vol_match"] else "불일치"}</span>'
        obsolete_badge = '<span class="badge mismatch">단종</span>' if p.get("obsolete") else ""
        trust = p.get("kr_seller_trust")
        trust_badge = (
            f'<span class="badge {"match" if trust in ("공식몰", "브랜드직영추정", "신뢰채널", "스마트스토어") else "unknown"}">{trust or "판매처미확인"}</span>'
            if trust else ""
        )

        kr_site_text = p["kr_source"]
        if p.get("kr_mall"):
            kr_site_text += f" · {p['kr_mall']}"

        # 구매처 원본 이름을 그대로 쓰되, 개수(2개 이상)가 원본 텍스트에 이미
        # 안 드러나 있으면(브랜드/화해쪽 부실한 name이 승자였던 경우) 뒤에
        # 보충해서 붙인다. 원본에 이미 "2개"/"1+1" 등이 있으면 중복 방지로 안 붙임.
        kr_name_val = p['kr_name'] or ''
        already_has_qty = bool(re.search(r"\d+\s*(개|매|セット|1\+1)", kr_name_val))
        qty_suffix = f" ({p['kr_qty']}개)" if p.get('kr_qty', 1) > 1 and not already_has_qty else ''
        kr_name_full = f"{kr_name_val}{qty_suffix}"

        cards_html.append(f'''
<div class="card" data-goods="{goods_no}" data-qoo10-name="" data-kr-name="" data-kr-site="{esc(kr_site_text)}">
  <div class="side">
    <h3>큐텐 원본</h3>
    <div class="mainrow">{qoo10_img_html}</div>
    <div class="name-label">상품명(수정가능 — 업로드용 확정명):</div>
    <textarea class="name-edit" data-goods="{goods_no}" rows="2">{p['qoo10_title']}</textarea>
    <div class="name-kr-readonly">참고 한글번역: {p['qoo10_name_kr']}</div>
    <div class="price">{p['qoo10_price_jpy'] or '-'} 円</div>
    <div class="goods_no">goods_no: {goods_no}</div>
  </div>
  <div class="side">
    <h3>한국 구매처 <span class="badges">{brand_badge}{vol_badge}{obsolete_badge}{trust_badge}</span></h3>
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

    cards_str = "\n".join(cards_html) + '\n<div id="pagination-bottom" class="pagination"></div>'
    template = (COMPARISON / "review.html").read_text(encoding="utf-8")
    new_html = re.sub(
        r"(<h1>.*?</h1>\n<p>큐텐 상품명은.*?</p>\n\n<div id=\"pagination-top\" class=\"pagination\"></div>\n\n).*?(\n<script>)",
        lambda m: m.group(1) + cards_str + m.group(2),
        template,
        flags=re.S,
    )
    new_html = re.sub(r"\(\d+건.*?\)", f"({len(pairs)}건)", new_html, count=1)
    (COMPARISON / "review.html").write_text(new_html, encoding="utf-8")
    print(f"[완료] review.html 갱신 ({len(pairs)}건)")


if __name__ == "__main__":
    pairs = build_pairs()
    build_html(pairs)
