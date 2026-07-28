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

import os
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


def to_pc_url(mobile_url: str) -> str:
    """모바일 큐텐 URL(m.qoo10.jp/gmkt.inc/Mobile/Goods/goods.aspx?...)을
    PC버전(www.qoo10.jp/gmkt.inc/Goods/Goods.aspx?...)으로 바꾼다."""
    if not mobile_url:
        return mobile_url
    m = re.search(r"goodscode=(\d+)", mobile_url)
    if m:
        return f"https://www.qoo10.jp/gmkt.inc/Goods/Goods.aspx?goodscode={m.group(1)}"
    return mobile_url.replace("m.qoo10.jp/gmkt.inc/Mobile/Goods/goods.aspx", "www.qoo10.jp/gmkt.inc/Goods/Goods.aspx")


def load_qoo10_products():
    # [발굴/수확 분리] 환경변수로 어느 통합본을 읽을지 고른다. 기본은
    # 발굴본(discovery_state.json), 수확분을 처리할 땐
    # QOO10_STATE_FILE=fullcatalog_state.json을 준다. 두 파일은 형식이
    # 동일하므로(merge_fullcatalog_states.py가 list로 맞춰서 저장) 이
    # 함수 아래 로직은 하나도 안 바꿔도 된다.
    state_file = os.environ.get("QOO10_STATE_FILE", "discovery_state.json")
    products = json.loads((OUTPUT / state_file).read_text(encoding="utf-8"))["all_products"]
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


def extract_sheet_count(text: str) -> int | None:
    """시트마스크/패치류는 mL이 아니라 "장수"(枚/매)로 스펙을 표시하는 게
    일반적이다. mL 정보가 없어도 이 장수끼리는 정확히 비교 가능하다
    (실측 확인된 사례: 큐텐원본 "10枚", 구매처 "21ml 10매"는 실제로
    같은 상품인데, mL만 비교하면 큐텐쪽에 mL 자체가 없어서 비교가
    안 됐었음 — 枚/매 개수를 대신 비교하면 정확히 일치를 판정할 수 있다)."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*(枚|매)\b", text)
    return int(m.group(1)) if m else None


def extract_quantity(text: str) -> int:
    """제목/상품명에서 실제 수량(묶음개수)을 추출한다(한글 상품명에 개수를
    명시적으로 표시하기 위함).
    주의: "N종세트"는 서로 다른 상품 N가지가 합쳐진 "1세트"를 뜻하므로
    수량 N이 아니라 1로 처리한다(예: "2종세트 (2개)"는 실제로 1세트)."""
    if not text:
        return 1
    text_wo_choice = re.sub(r"\d+種(類)?から\d+つ選択", "", text)
    if re.search(r"\d+종\s*(세트|SET|Set)", text_wo_choice):
        return 1
    m = re.search(r"(\d+)\s*\+\s*(\d+)", text_wo_choice)
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"(\d+)\s*(個|개|입|병|本)\b", text_wo_choice)
    if m:
        return int(m.group(1))
    if re.search(r"세트|SET|Set|1\+1", text_wo_choice):
        return 2
    return 1


def check_brand(orig_brand: str, kr_brand_text: str, brand_dict: dict) -> str:
    if not orig_brand:
        return "unknown"  # 원본에 브랜드 정보 자체가 없으면 "불일치"가 아니라 "판단불가"
    kr_brand_lower = (kr_brand_text or "").lower()
    if not kr_brand_lower:
        # [수정] 구매처쪽 브랜드정보 자체가 없으면(예: 승자가 exa인데 exa는
        # 애초에 brand를 안 줌) "불일치"가 아니라 "판단불가"다 — 실측으로
        # 확인된 버그: 이전엔 원본이 가타카나일 때만 unknown 처리했는데,
        # 영문/한글 원본 브랜드도 똑같이 정보부족을 mismatch로 잘못
        # 표시하고 있었다.
        return "unknown"
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
    # [발굴/수확 분리] 검증결과 파일도 환경변수로 고른다.
    verified_file = os.environ.get("QOO10_VERIFIED_FILE", "hwahae_verified_39.json")
    kr = json.loads((OUTPUT / verified_file).read_text(encoding="utf-8"))
    brand_dict = json.loads((DATA / "brand_translations_learned.json").read_text(encoding="utf-8"))
    brand_dict.pop("_설명", None)
    brand_dict.pop("_아도르_참고", None)

    # [일본어 역번역] 한글 상품명(구매처 원본) 아래에 참고용 일본어 번역을
    # 보여주기 위한 배치번역 결과(translate_kr_to_jp.py가 생성). 없으면
    # 빈 딕셔너리로 폴백 — 이 파일이 없다고 페이지 생성 자체가 실패하면
    # 안 된다.
    kr_to_jp = {}
    kr_to_jp_path = OUTPUT / "kr_to_jp_translations.json"
    if kr_to_jp_path.exists():
        try:
            kr_to_jp = json.loads(kr_to_jp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # [구조변경 대응] 1,2단계 통합 이후엔 별도 hwahae_input_39.json이 없다.
    # discovery_state.json의 translated_kr을 보조로 쓰되, 최우선은 검증
    # 시점에 실제로 사용된 값(hwahae_verified_39.json 각 항목 자체의
    # translated_kr) — 이게 정확히 그 상품을 검증할 때 쓴 번역문이고,
    # discovery_state.json 쪽은 이후 상태가 달라졌을 수 있어 신뢰도가 낮다.
    translations = {gn: p.get("translated_kr", "") for gn, p in qoo10_by_goods.items() if p.get("translated_kr")}
    input_path = OUTPUT / "hwahae_input_39.json"
    if input_path.exists():
        for x in json.loads(input_path.read_text(encoding="utf-8")):
            translations.setdefault(x["goods_no"], x.get("translated_kr", ""))

    pairs = []
    stats = {"no_link": 0, "sold_out": 0, "obsolete": 0, "no_qoo10_match": 0, "select_type": 0, "collab": 0, "ok": 0}
    for x in kr:
        if not x.get("product_url"):
            stats["no_link"] += 1
            continue
        if x.get("in_stock") is False:
            stats["sold_out"] += 1
            continue
        if x.get("obsolete"):
            stats["obsolete"] += 1
            continue
        q = qoo10_by_goods.get(x["goods_no"])
        if not q:
            stats["no_qoo10_match"] += 1
            continue
        # [제외] "3종"처럼 숫자+종 표기는 "그중 하나를 선택"(옵션 3가지 중
        # 1개)인지 "3개가 다 들어있는 세트"인지 텍스트만으로는 확실히
        # 구분이 안 된다(예: "셰이킹 시너지 미스트 50ml 3종" — 3가지
        # 향 중 하나를 고르는 건지, 3개가 다 오는 건지 애매함). 애매한 걸
        # 억지로 판정하기보다, 사용자 지시대로 이런 상품은 전부 제외한다.
        translated_kr = x.get("translated_kr") or ""
        if re.search(r"\d+종\b", q["title"]) or re.search(r"\d+종\b", translated_kr):
            stats["select_type"] += 1
            continue
        # [제외] "콜라보"(협업/한정판) 상품도 사용자 지시로 전부 제외한다
        # — 이런 상품은 패키지/구성이 일반판과 달라서(예: "야구단
        # 콜라보/2회분" 골라담기류) 정확한 매칭 신뢰도가 낮다.
        if re.search(r"콜라보|コラボ", q["title"]) or re.search(r"콜라보|コラボ", translated_kr):
            stats["collab"] += 1
            continue

        stats["ok"] += 1

        # 표시용 한글 상품명: 우선순위는
        # 1) 실제 구매링크 페이지에서 직접 가져온 진짜 상품명(real_page_title,
        #    가장 정확 — 실측으로 확인된 문제: 네이버 API의 title은 실제
        #    판매페이지와 다를 수 있었음, 예: "에스트라 NEW 아토베리어365
        #    캡슐 토너" vs 실제페이지 "NEW 아토베리어365 캡슐 토너 300ml")
        # 2) 네이버 API의 title(위 스크래핑이 실패한 사이트의 경우 폴백)
        # 3) 승자(화해/Exa 등)의 name
        naver_original_name = (x.get("candidates_summary") or {}).get("naver")
        kr_name_display = x.get("real_page_title") or naver_original_name or x.get("name") or ""

        qoo10_vol = extract_volume_ml(q["title"])
        kr_vol = extract_volume_ml(kr_name_display) or extract_volume_ml(x.get("volume") or "")
        vol_match = qoo10_vol is not None and kr_vol is not None and abs(qoo10_vol - kr_vol) < 0.1
        vol_status = "match" if vol_match else ("unknown" if qoo10_vol is None or kr_vol is None else "mismatch")

        # [개선] mL로 비교가 안 되면(둘 중 하나라도 mL정보 없음) 그냥
        # "판단불가"로 남기지 않고, 시트/장수(枚/매) 개수로 대신 비교해서
        # 진짜 일치/불일치를 가려낸다 — 시트마스크류는 mL이 아니라 장수로
        # 스펙을 표시하는 게 일반적이라, 장수가 정확히 맞으면 실제로는
        # 같은 상품인 경우가 많다(실측 사례: 큐텐 "10枚" vs 구매처
        # "21ml 10매" → mL은 큐텐에 없지만 枚/매 개수 10=10으로 정확히
        # 일치 판정 가능).
        if vol_status == "unknown":
            qoo10_sheets = extract_sheet_count(q["title"])
            kr_sheets = extract_sheet_count(kr_name_display) or extract_sheet_count(x.get("volume") or "")
            if qoo10_sheets is not None and kr_sheets is not None:
                vol_status = "match" if qoo10_sheets == kr_sheets else "mismatch"
                vol_match = vol_status == "match"

        orig_brand = q.get("brand", "")
        brand_status = check_brand(orig_brand, x.get("brand", ""), brand_dict)
        kr_qty = extract_quantity(kr_name_display)
        # SET(서로 다른 상품이 결합된 세트) 감지: 큐텐 원문에 [SET] 표기가
        # 있거나, 구매처 원본명에 "세트/SET"가 있는 경우(예: "선물세트",
        # "기획세트"도 포함 — "N종"이 꼭 붙어야만 세트인 게 아니다).
        # [중요] extract_quantity()는 "세트"라는 단어만 있어도 수량=2로
        # 간주하는데, 이건 "같은 상품 2개"와 "서로 다른 상품이 묶인 세트"를
        # 구분 못 한다(실측 사례: "펩타이드 크림+앰플+파우치+쇼핑백"을
        # 묶은 "기미케어 선물세트"에 큐텐원본 크림을 "X 2個"로 잘못
        # 표시함). is_set이면 아래 수량자동수정 자체를 건너뛴다.
        is_set = bool(
            re.search(r"\[SET\]|\[세트\]", q["title"], re.I)
            or re.search(r"세트|SET", kr_name_display, re.I)
        )

        # [자동수정] 실제로 소싱하는 물건은 한국쪽 구매처 상품이므로, 큐텐
        # 원본과 용량이 다르면 큐텐 쪽 업로드용 상품명을 한국쪽(실제 소싱)
        # 용량으로 맞춰서 고쳐준다. 세트상품(예: "50g+20g")은 첫 번째
        # 숫자(주 용량)만 바꾸고 나머지는 그대로 둔다.
        # [안전장치] 브랜드 자체가 확실히 불일치(mismatch)면 애초에 매칭이
        # 틀렸을 가능성이 높으므로 용량자동수정을 하지 않는다 — 틀린 매칭
        # 위에 그럴듯한 수정을 얹으면 오히려 더 진짜처럼 보여서 위험하다
        # (실측: 브랜드가 완전히 다른 상품에 용량자동수정까지 적용되어
        # 혼란을 키운 사고가 있었다).
        qoo10_title_display = q["title"]
        qoo10_title_highlighted = ""  # 바뀐 부분을 <mark>로 감싼 미리보기용(읽기전용)
        vol_auto_corrected = False
        if not vol_match and qoo10_vol is not None and kr_vol is not None and brand_status != "mismatch":
            kr_vol_int = int(kr_vol) if kr_vol == int(kr_vol) else kr_vol
            qoo10_title_display = re.sub(
                r"\d+(?:\.\d+)?\s*(mL|ml|g|L)",
                lambda m: f"{kr_vol_int}{m.group(1)}",
                q["title"], count=1,
            )
            escaped_title = re.sub(
                r"\d+(?:\.\d+)?\s*(mL|ml|g|L)",
                lambda m: f'<mark class="vol-fix">{kr_vol_int}{m.group(1)}</mark>',
                q["title"], count=1,
            )
            qoo10_title_highlighted = escaped_title
            vol_auto_corrected = True

        # [자동수정: 수량] 한국쪽 실제 구매처 상품이 "X 2개"처럼 여러 개
        # 묶음인데, 큐텐 원본 제목엔 그 수량 표시가 전혀 없으면(예: 원문이
        # "PDRN 핑크 콜라겐 볼륨 멀티밤 10g"뿐인데 실제 구매처는 "X 2개"),
        # 업로드용 제목 끝에 "X {N}個"를 붙여서 실제 소싱수량을 반영한다.
        # 이미 원문 자체에 수량표기(個/個入 등)가 있으면 건드리지 않는다
        # (중복표기 방지). 브랜드불일치일 때는 용량수정과 동일하게 건너뛴다.
        qty_auto_corrected = False
        qoo10_qty = extract_quantity(q["title"])
        if kr_qty > 1 and brand_status != "mismatch" and qoo10_qty <= 1 and not is_set:
            # [수정] 큐텐원문에 이미 "1個"처럼 수량이 명시되어 있으면, 뒤에
            # "X N個"를 덧붙이지 않고 그 "1"이라는 숫자 자체를 실제 수량으로
            # 바꾼다(실측 사례: "...1個 X 2個"처럼 중복표기가 되던 문제).
            # 원문에 수량표기 자체가 아예 없을 때만 새로 추가한다.
            explicit_one_pattern = re.compile(r"(?<!\d)1(\s*(?:個|개|입|병|本))\b")
            explicit_match = explicit_one_pattern.search(qoo10_title_display)
            if explicit_match:
                qoo10_title_display = explicit_one_pattern.sub(
                    lambda m: f"{kr_qty}{m.group(1)}", qoo10_title_display, count=1)
                base_for_highlight = qoo10_title_highlighted or q["title"]
                qoo10_title_highlighted = explicit_one_pattern.sub(
                    lambda m: f'<mark class="vol-fix">{kr_qty}{m.group(1)}</mark>', base_for_highlight, count=1)
            else:
                qty_suffix_jp = f" X {kr_qty}個"
                qoo10_title_display = qoo10_title_display.rstrip() + qty_suffix_jp
                if qoo10_title_highlighted:
                    qoo10_title_highlighted = qoo10_title_highlighted.rstrip() + f' <mark class="vol-fix">{qty_suffix_jp.strip()}</mark>'
                else:
                    qoo10_title_highlighted = q["title"].rstrip() + f' <mark class="vol-fix">{qty_suffix_jp.strip()}</mark>'
            qty_auto_corrected = True
        # [반대 케이스] 한국쪽은 실제로 1개만 사는데(kr_qty<=1), 큐텐
        # 원본 제목에는 "2個"처럼 수량표기가 있으면 그 표기를 제거한다 —
        # 실측 사례: 큐텐원문 "...50ml 2個"인데 실제 소싱처는 1개짜리
        # ("50ml" 단품)였음. 표기를 안 지우면 "2개 준다"고 오해할 수 있어
        # 위험하다.
        qty_removed_original = None
        if kr_qty <= 1 and qoo10_qty > 1 and brand_status != "mismatch" and not is_set:
            # [1+1]처럼 대괄호로 감싼 "덤" 표기와, "2個"류 단위수량 표기를
            # 둘 다 잡아서 제거한다(실측 사례: 큐텐원문 "[1+1]...100g"인데
            # 실제 소싱은 1개뿐이었음 — "1+1"을 그대로 두면 "하나 더
            # 준다"고 오해하게 됨).
            qty_removal_pattern = re.compile(r"\s*[\(\[]?\d+\s*\+\s*\d+[\)\]]?|\s*[\(\[]?[Xx×]?\s*\d+\s*(個|개|입|병|本)[\)\]]?")
            m = qty_removal_pattern.search(qoo10_title_display)
            if m:
                qty_removed_original = m.group(0).strip()
                qoo10_title_display = qty_removal_pattern.sub("", qoo10_title_display, count=1).strip()
                if qoo10_title_highlighted:
                    qoo10_title_highlighted = qty_removal_pattern.sub(
                        lambda mm: f' <del class="vol-fix" style="color:#c0392b;">{mm.group(0).strip()}</del>', qoo10_title_highlighted, count=1)
                else:
                    qoo10_title_highlighted = qty_removal_pattern.sub(
                        lambda mm: f' <del class="vol-fix" style="color:#c0392b;">{mm.group(0).strip()}</del>', q["title"], count=1)
                qty_auto_corrected = True

        # [제외] "国内当日発送"류 일본 국내발송 문구는 실제로는 한국에서
        # 발송하므로 사실과 다르다 — 지워서 오해를 방지한다. 지워졌다는
        # 걸 취소선으로 표시한다(사용자 지시: "나는 한국에서 보낼꺼니까").
        shipping_removal_pattern = re.compile(
            r"[\[［【(]?\s*国内\s*(当日|即日)?\s*発送\s*[\]］】)]?|あす楽(対応)?|\s*即日出荷"
        )
        m2 = shipping_removal_pattern.search(qoo10_title_display)
        if m2:
            removed_text = m2.group(0).strip()
            qoo10_title_display = shipping_removal_pattern.sub("", qoo10_title_display, count=1).strip()
            base_for_highlight = qoo10_title_highlighted or q["title"]
            qoo10_title_highlighted = shipping_removal_pattern.sub(
                lambda mm: f' <del class="vol-fix" style="color:#c0392b;">{mm.group(0).strip()}</del>', base_for_highlight, count=1)
            qty_auto_corrected = True

        kr_candidates = x.get("image_candidates") or []
        if not kr_candidates and x.get("image_url"):
            kr_candidates = [{"url": x["image_url"], "mall": x.get("mall"), "link": x.get("product_url")}]

        pairs.append({
            "goods_no": x["goods_no"], "qoo10_title": qoo10_title_display, "qoo10_title_original": q["title"],
            "vol_auto_corrected": vol_auto_corrected, "qty_auto_corrected": qty_auto_corrected, "vol_status": vol_status, "qoo10_title_highlighted": qoo10_title_highlighted, "qoo10_brand": orig_brand,
            "qoo10_image": q.get("image_url"), "qoo10_price_jpy": q.get("price_jpy"), "qoo10_url": to_pc_url(q.get("item_url")),
            "qoo10_name_kr": x.get("translated_kr") or translations.get(x["goods_no"], ""),
            "kr_brand": x.get("brand"), "kr_name": kr_name_display,
            "kr_volume": x.get("volume") or (f"{int(kr_vol)}ml" if kr_vol else ""),
            "kr_qty": kr_qty, "is_set": is_set, "kr_name_jp": kr_to_jp.get(x["goods_no"], ""),
            "kr_candidates": kr_candidates, "kr_price": x.get("price"), "kr_url": x.get("product_url"),
            "kr_mall": x.get("mall"), "kr_seller_trust": x.get("seller_trust"),
            "kr_source": x.get("winner_source"), "vol_match": vol_match, "brand_status": brand_status,
            "obsolete": x.get("obsolete"),
            "naver_rematched": x.get("naver_rematched"),
        })

    print(f"[통계] 구매링크없음={stats['no_link']} 품절={stats['sold_out']} 단종={stats['obsolete']} "
          f"큐텐매칭안됨={stats['no_qoo10_match']} 선택형제외={stats['select_type']} 콜라보제외={stats['collab']} 최종={stats['ok']}건")
    (OUTPUT / "comparison_pairs.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return pairs


def esc(s):
    if s is None:
        return ""
    return str(s).replace('"', "&quot;").replace("'", "&#39;")


def dim_minor_text(text: str) -> str:
    """번역문 안에서 프로모션/부가문구(해시태그, 대괄호 안 홍보문구, '증정'
    '기획' '한정' 등)를 회색으로 옅게 표시하고, 핵심 상품정보는 그대로
    둔다. 완전한 의미분석은 아니지만 실측 패턴 기반으로 상당수를 잡아낸다."""
    if not text:
        return text
    escaped = esc(text)
    # #해시태그
    escaped = re.sub(r"(#\S+)", r'<span class="dim">\1</span>', escaped)
    # 대괄호 안 내용 중 홍보성 키워드가 있으면 통째로 옅게
    promo_kw = r"(신상품|신상|한정|증정|기획|선물|이벤트|사은품|프로모션|NEW|new)"
    escaped = re.sub(
        r"(\[[^\]]*" + promo_kw + r"[^\]]*\])",
        r'<span class="dim">\1</span>',
        escaped,
    )
    return escaped


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

        # 구매처 원본 이름을 그대로 쓰되, 개수(2개 이상)가 원본 텍스트에 이미
        # 안 드러나 있으면(브랜드/화해쪽 부실한 name이 승자였던 경우) 뒤에
        # 보충해서 붙인다. 원본에 이미 "2개"/"1+1" 등이 있으면 중복 방지로 안 붙임.
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
      <td><span class="price">{p['qoo10_price_jpy'] or '-'} 円</span> <span style="color:#bbb;">/</span> <span class="price">{p['kr_price'] or '-'} 원</span></td>
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

    cards_str = "\n".join(cards_html) + '\n<div id="pagination-bottom" class="pagination"></div>'
    # [중요] 템플릿(review.html)과 출력파일을 반드시 분리한다 — 예전엔 같은
    # 경로에 읽고 쓰기를 해서, 이 스크립트를 한 번이라도 직접 실행하면
    # 템플릿 자체가 카드데이터로 영구 오염되는 사고가 있었다(실측 확인:
    # 템플릿이 3854줄까지 부풀어서, build_review_batches.py가 그 오염된
    # 템플릿을 읽어 배치를 만들면서 페이지네이션/undo버튼이 깨지는 원인이
    # 됐다). 템플릿은 항상 읽기전용으로만 다루고, 결과는 별도 파일에 쓴다.
    template = (COMPARISON / "review.html").read_text(encoding="utf-8")
    new_html = re.sub(
        r"(<h1>.*?</h1>\n<p>큐텐 상품명은.*?</p>\n\n<div id=\"pagination-top\" class=\"pagination\"></div>\n\n).*?(\n<script>)",
        lambda m: m.group(1) + cards_str + m.group(2),
        template,
        flags=re.S,
    )
    new_html = re.sub(r"\(\d+건.*?\)", f"({len(pairs)}건)", new_html, count=1)
    (COMPARISON / "review_full.html").write_text(new_html, encoding="utf-8")
    print(f"[완료] review_full.html 생성 ({len(pairs)}건) — 템플릿(review.html)은 건드리지 않음")


if __name__ == "__main__":
    pairs = build_pairs()
    build_html(pairs)
