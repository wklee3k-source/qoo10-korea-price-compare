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
    # [v7.25.0] '매\b' 만으로는 "10매입"(뒤가 단어문자라 \b 실패)과
    #  "70장"을 아예 못 읽었다 — 미스드래곤 매수 오매칭이 그동안 안 잡힌
    #  실제 원인. 실측: A등급에서 '5장 vs 5매' 같은 표기차 6건이 매수
    #  비교 불가로 남아 있었다.
    #  뒤에 한글이 이어지면 다른 단어다("장짜리" 등). 라틴문자는 허용해야
    #  "60장x2개" 같은 배수 표기가 읽힌다. 실측 오탐으로 추가된 표기:
    #  "6장입"(장+들이 입), "10EA"(시트류 개수 표기).
    m = re.search(r"(\d+)\s*(?:枚|매입|매|장입|장|EA\b)(?![가-힣])", text)
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
    # [v7.25.0] "2PACK"·"2팩" 묶음 표기. 실측: '[2pack] 인테카 수딩 패드
    #  70매'가 큐텐 단품(70장)에 A등급으로 붙어 있었다. 숫자가 앞에 붙은
    #  경우만 잡으므로 '마스크팩' 같은 제품명은 걸리지 않는다.
    m = re.search(r"(\d+)\s*(?:PACK|팩)\b", text_wo_choice, re.I)
    if m:
        return int(m.group(1))
    if re.search(r"세트|SET|Set|1\+1", text_wo_choice):
        return 2
    return 1


def total_count(text: str) -> int:
    """상품명에서 '총 매수·개수'를 환산한다.

    [v7.25.0] 매수(매/장/枚)와 묶음개수(個/개/팩)가 양쪽에 교차 표기되는
    경우가 있어 단순 비교로는 오탐이 난다 — 실측 A등급 273건 대조에서:
        "다이브인 마스크 10개"      vs "마스크 10매, 1개"     같은 상품
        "페이스 필름 (3+1)"         vs "페이스필름 4매"        같은 상품
        "60장x2개"                  vs "[1+1] 60매"           같은 상품(120매)
    표기 조합을 총량으로 환산하면 측정 사례 36건이 전부 올바르게 갈린다.

    환산 규칙:
    - 매수 표기가 없으면 묶음개수(extract_quantity, 무표기=1)가 총량이다.
    - 매수 + 묶음단위(個/개/병/本/팩)가 함께 있으면 곱한다("70매 (2개)"=140).
    - 매수 + "N+M" 표기는 숫자가 매수와 이어지면 매수 합산("9매입 (9+1)"=10),
      안 이어지면 묶음 배수("[1+1] ... 60매"=120)다. N+M의 뜻이 문맥에 따라
      정반대라 이 구분이 없으면 어느 한쪽이 반드시 오탐난다.
    """
    if not text:
        return 1
    sheets = extract_sheet_count(text)
    qty = extract_quantity(text)
    if sheets is None:
        return qty
    m = re.search(r"(\d+)\s*\+\s*(\d+)", text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a == sheets or a + b == sheets:
            return max(sheets, a + b)          # 매수 합산 표기 (9매입 9+1)
        return sheets * (a + b)                # 묶음 배수 표기 (1+1 60매)
    if re.search(r"(\d+)\s*(?:個|개|병|本|PACK|팩)\b", text, re.I):
        return sheets * max(qty, 1)            # 60매 x 2개 = 120
    return sheets


# [v7.26.0] '본품 + α' 구성에서 α가 무엇인지 가른다.
#  큐텐은 본품 단품인데 한국 판매처는 기획 구성인 경우가 많다. 이걸
#  전부 세트로 묶으면 멀쩡한 매칭이 S로 사라지고, 전부 무시하면 실제로
#  두 배를 사는 건이 A로 남는다. α를 세 갈래로 나눠야 한다.
#
#      증정(gift)   파우치·미니·샘플 등. 가격에 거의 영향 없다 -> 무시
#      본품추가(main) 동량 리필·1+1 등. 실제 수량이 늘어난다   -> 총량 합산
#      다른제품(other) 토너+크림 같은 구성. 비교 자체가 안 된다 -> 세트(S)
#
#  판정 순서가 중요하다. 용량 비율을 제형보다 먼저 보면 '토너 350ml +
#  크림 20ml'(다른 제품)이 소량이라는 이유로 증정이 된다 — 실측에서
#  이 순서를 뒤집자 other 13건 -> 39건으로 늘고 오분류가 사라졌다.
# [v7.28.0] '+' 로 조각을 나누기 전에 지워야 하는 표기들.
#  수량('1+1', '9+1')과 성분 함량 나열('AHA 30% + BHA 2%')은 제품 구성이
#  아니라 표기다. 안 지우면 뒤 조각이 상품명 전체가 되어('1] 아누아 선크림')
#  거기 든 제형어 때문에 별개 제품으로 읽힌다 — 실측 83건 오탐.
QTY_PLUS_RE = re.compile(r"\d+\s*[+＋]\s*\d+")
PCT_PLUS_RE = re.compile(r"\d+\s*%\s*[+＋]")


def _bonus_text(name: str) -> str:
    text = SPF_NOTATION_RE.sub(" ", name or "")
    text = QTY_PLUS_RE.sub(" ", text)
    return PCT_PLUS_RE.sub("% ", text)


GIFT_NONPRODUCT_RE = re.compile(
    r"파우치|쇼핑백|가방|브러[시쉬]|미니거울|거울|약통|화장솜|스파[츄출]러|"
    r"케이스|포토카드|밴드|치약|퍼프|헤어밴드|텀블러|키링|스티커")
GIFT_WORD_RE = re.compile(r"증정|사은품|샘플|체험분|미니어처")
REFILL_RE = re.compile(r"리필")

# 부가 용량이 본품의 절반 이상이면 증정이 아니라 본품 추가로 본다.
#  실측: 절반 미만은 '휴대용 미니 15ml'·'기획(+4ml)' 처럼 맛보기였고,
#  절반 이상은 '250ml+리필250ml'·'60매+리필60매' 처럼 실제 두 배였다.
BONUS_MAIN_RATIO = 0.5


def classify_bonus(seg: str, main_vol, main_sheets, main_forms) -> str:
    """'+' 뒤 한 조각이 증정인지 본품인지 다른 제품인지 가른다."""
    s = (seg or "").strip()
    if not s or re.fullmatch(r"\s*\d+\s*\W*", s):
        return "empty"          # '1+1' 처럼 수량 표기가 쪼개진 것
    if GIFT_NONPRODUCT_RE.search(s) or GIFT_WORD_RE.search(s):
        return "gift"
    # '리필'은 제형어가 뒤에 붙어 있어도 본품 추가다 — 실측 오분류:
    #  '그로우턴 앰플 100ml + 리필 100ml 기획상품 탈모 두피에센스'가
    #  뒤의 '에센스' 때문에 다른 제품으로 읽혔다.
    if REFILL_RE.search(s):
        return "main"
    forms = _narrow_forms(extract_forms(s))
    vol, sheets = extract_volume_ml(s), extract_sheet_count(s)
    # [v7.28.0] 제형이 같아도 별개 제품일 수 있다. 사장님 지적:
    #  '부스터 120ml + 세럼 45ml' 은 증정이 아니라 2종 세트인데, '부스터'가
    #  제형 사전에서 세럼으로 매핑돼 본품과 같은 제형이 되는 바람에 용량
    #  비율만 보고 증정이 됐다.
    #  조각이 **제형어와 자체 용량을 모두** 가지고 본품에도 용량이 있으면
    #  두 제품이 나란히 있는 것으로 본다. 셋 중 하나라도 빠지면 성분·설명
    #  나열일 뿐이다 — 실측 오탐: '레티놀 0.1 + 카페인 아이크림'(용량 없음),
    #  '유산균 + 시카 세럼 50ml'(본품 용량 없음), 'Vitamin C + AHA 클렌저'.
    if forms and vol is not None and main_vol and (
            forms != main_forms or vol / main_vol < BONUS_MAIN_RATIO):
        return "other"
    if forms and main_forms and forms != main_forms:
        return "other"
    if vol is not None and main_vol:
        return "main" if vol / main_vol >= BONUS_MAIN_RATIO else "gift"
    if sheets is not None and main_sheets:
        return "main" if sheets / main_sheets >= BONUS_MAIN_RATIO else "gift"
    return "unknown"            # 판단 근거 없음 -> 현행 유지


def split_bonus(name: str) -> tuple[str, int, bool]:
    """상품명을 (증정 뺀 본품 이름, 본품 배수, 다른제품 포함 여부)로 나눈다.

    사장님 방침: 증정은 가격에 사실상 영향이 없으니 무시하고 본품끼리만
    비교한다. 따라서 증정 조각은 이름에서 잘라내고, 본품 추가만 배수로
    센다. 다른 제품이 섞여 있으면 애초에 비교가 성립하지 않으므로
    세트로 넘긴다.
    """
    text = _bonus_text(name)
    if "+" not in text and "＋" not in text:
        return (name or "", 1, False)
    parts = re.split(r"[+＋]", text)
    main = parts[0]
    m_vol, m_sheets = extract_volume_ml(main), extract_sheet_count(main)
    m_forms = _narrow_forms(extract_forms(main))
    kept, extra, has_other = [main], 0, False
    for seg in parts[1:]:
        kind = classify_bonus(seg, m_vol, m_sheets, m_forms)
        if kind == "gift":
            continue                       # 잘라낸다
        if kind == "main":
            extra += 1
            continue
        if kind == "other":
            has_other = True
        kept.append(seg)                   # other/unknown/empty 는 그대로 둔다
    return ("+".join(kept), 1 + extra, has_other)


def counts_mismatch(qoo10_name_kr: str, kr_name: str, is_set: bool = False) -> bool:
    """[v7.25.0] 총 매수·개수가 다르면 가격 비교에 환산이 필요하다 -> B.

    confidence_tier 주석의 설계("B = 용량/수량만 다름")에 수량이 처음부터
    포함돼 있었는데 구현은 용량만 보고 있었다. 실측: A등급(완전일치) 273건
    중 24건이 '1+1 vs 단품', '10매 vs 1매' 같은 수량 불일치였고, 그중
    뉴클리드 마스크팩은 10매 가격(2,500円)과 1매 가격(2,000원)이 나란히
    놓여 있었다 — 그대로 쓰면 원가 계산이 10배 틀어진다.

    무표기는 단품(1)으로 본다. 성분 판정(v7.16.0)과 달리 수량은 상거래
    관행상 표기가 없으면 실제로 1개다. 세트는 S등급에서 따로 처리하므로
    여기서 보지 않는다. 제외가 아니라 등급 강등만 한다(설계이력 1-1).
    """
    if is_set:
        return False
    # [v7.26.0] 증정을 무시하는 건 **한국측(사는 쪽)만**이다. 큐텐측은
    #  내가 파는 구성이라 '크림 50ml + 미니 15ml' 로 올려놨으면 미니도
    #  사서 보내야 한다 — 여기서 지우면 못 맞추는 구성이 A로 남는다.
    #  한국 판매처가 끼워주는 사은품은 반대로 더 받는 것이라 무시해도 된다.
    k_name, k_mult, _ = split_bonus(kr_name)
    return total_count(qoo10_name_kr) != total_count(k_name) * k_mult


def _remove_gift_segment(title: str, seg: str) -> str:
    """제목에서 증정 조각 하나를 지우고 남은 구두점을 정리한다.

    그냥 지우면 '(+7ml)' 가 '(' 로, '【120ml+15ml】' 가 '【120ml' 로 남는다.
    조각 앞의 '+' 와, 짝을 잃은 여는 괄호를 함께 치운다.
    """
    if not seg or seg not in title:
        return title
    # 조각 끝에 닫는 괄호가 붙어 있으면 그건 조각이 아니라 상품명의
    #  구조다. 같이 지우면 '(20ml+20ml)' 가 '(20ml' 로, '【120ml+15ml】'
    #  가 '【120ml' 로 짝을 잃는다.
    closers = ")）]】"
    trail = ""
    core = seg
    while core and core[-1] in closers:
        trail = core[-1] + trail
        core = core[:-1]
    if not core or core not in title:
        return title
    # 뒤에서부터 찾는다 — 지우는 건 언제나 마지막 초과분이고, 앞에서
    #  찾으면 '(20ml+20ml)' 에서 첫 조각이 지워져 '(+20ml)' 가 된다.
    idx = title.rindex(core)
    head, tail = title[:idx], title[idx + len(core):]
    head = re.sub(r"[+＋]\s*$", "", head)
    out = (head + tail)
    # 내용이 통째로 사라져 빈 괄호만 남으면 그것도 치운다
    for op, cl in (("(", ")"), ("（", "）"), ("[", "]"), ("【", "】")):
        out = re.sub(re.escape(op) + r"\s*" + re.escape(cl), "", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,、/")


def gift_indexes(name: str, strict: bool = False) -> tuple[list[int], int]:
    """'+' 로 나눈 조각 중 증정으로 볼 것들의 위치와 전체 조각 수.

    strict 는 '큐텐 쪽에서 지워도 되는가'를 볼 때 쓴다. 지우는 건 실제로
    파는 구성을 줄이는 일이라 기준을 더 좁힌다 — 조각에 제형어가 있거나
    본품 제형을 모르면 지우지 않는다. 실측 오분류: '부스터 120ml + 세럼
    45ml'(2종 구성)이 '부스터'가 제형 사전에 없어 비교가 안 되는 바람에
    증정으로 읽혔다. 이 기준으로 31건 -> 16건이 된다.
    """
    text = _bonus_text(name)
    if "+" not in text and "＋" not in text:
        return [], 0
    parts = re.split(r"[+＋]", text)
    m_vol, m_sheets = extract_volume_ml(parts[0]), extract_sheet_count(parts[0])
    m_forms = _narrow_forms(extract_forms(parts[0]))
    found = []
    for i, seg in enumerate(parts[1:], 1):
        if classify_bonus(seg, m_vol, m_sheets, m_forms) != "gift":
            continue
        if strict and (_narrow_forms(extract_forms(seg)) or not m_forms):
            continue
        if strict and len(seg.strip()) > 12:
            # 조각이 길면 증정 표기가 아니라 별개 제품명일 가능성이 크다.
            #  실측 오분류: '큐리베어SOS 멜더 시스템 (1.5ml x 20本)' 이
            #  제형어가 없어 증정으로 읽혔다. 지우면 파는 물건이 바뀐다.
            continue
        found.append(i)
    return found, len(parts)


def strip_excess_gifts(jp_title: str, translated_kr: str,
                       kr_name: str) -> tuple[str, list[str]]:
    """큐텐 쪽 증정이 한국 구매처보다 많으면 초과분을 상품명에서 지운다.

    [v7.27.0] 사장님 지시. 큐텐에 '크림 50ml + 15ml + 15ml' 로 올려놨는데
    한국에서는 50ml 단품밖에 못 사면 15ml 두 개를 줄 수가 없다. 그대로
    두면 못 지킬 구성을 파는 셈이라, 초과분을 업로드용 제목에서 뺀다.

    판정은 번역본으로 하고 삭제는 일본어 원문에서 한다. 둘의 '+' 조각
    수가 같을 때만 손댄다 — 번역 과정에서 조각이 붙거나 갈라졌으면 어느
    조각이 어느 조각인지 대응시킬 수 없다.

    지운 내용은 반드시 change_notes 로 남긴다(설계이력 1-1: 조용히
    사라지면 잘못 지워도 알 수 없다).
    """
    q_gifts, q_parts = gift_indexes(translated_kr, strict=True)
    k_gifts, _ = gift_indexes(kr_name)
    excess = len(q_gifts) - len(k_gifts)
    if excess <= 0:
        return jp_title, []
    jp_parts = re.split(r"([+＋])", _bonus_text(jp_title))
    seg_count = (len(jp_parts) + 1) // 2
    if seg_count != q_parts:
        return jp_title, []          # 대응시킬 수 없다
    drop = set(q_gifts[-excess:])    # 뒤쪽부터 지운다
    kept, removed = [], []
    for i in range(seg_count):
        seg = jp_parts[i * 2]
        if i in drop:
            removed.append(seg.strip())
            continue
        kept.append(seg)
    if not removed:
        return jp_title, []
    return "+".join(kept).strip(), removed


# [v4.3.0] 브랜드가 다르고 이름까지 안 맞으면 오매칭으로 보고 검수에서 뺀다.
#  실측: 브랜드 불일치 569건 중 184건이 이 유형이었고, 표본 6건을 눈으로
#  확인한 결과 6건 모두 실제 오매칭이었다(선크림→파운데이션, 크림→컨디셔너,
#  심지어 '광고 출연자 모집' 게시글까지).
#
#  두 가지 척도를 모두 통과해야 뺀다. 한 척도만 쓰면 멀쩡한 매칭을 버린다 —
#  단어겹침만 보면 '맑은쌀 꿀채운 마스크'와 '맑은쌀꿀채운마스크'가 남남이
#  되고(띄어쓰기), 글자조각만 보면 'UV'와 '유브이'가 남남이 된다.
NAME_STOPWORDS = {"세트", "대용량", "본품", "공식", "정품", "무료배송", "리필",
                  "신상", "인기", "한국", "단독", "증정"}


def _name_tokens(text: str) -> set:
    t = re.sub(r"[\[\]【】()（）/,+#\-]", " ", text or "")
    t = re.sub(r"\d+\s*(ml|g|매|장|개|종|%)", " ", t, flags=re.I)
    return {w for w in re.findall(r"[가-힣A-Za-z]{2,}", t) if w not in NAME_STOPWORDS}


def _sim_token(a: str, b: str) -> float:
    A, B = _name_tokens(a), _name_tokens(b)
    return len(A & B) / min(len(A), len(B)) if A and B else 0.0


def _sim_bigram(a: str, b: str) -> float:
    """공백·기호를 무시한 2글자 조각 겹침 — 띄어쓰기 차이를 흡수한다."""
    A, B = re.sub(r"[^가-힣A-Za-z]", "", a or ""), re.sub(r"[^가-힣A-Za-z]", "", b or "")
    if len(A) < 2 or len(B) < 2:
        return 0.0
    sa = {A[i:i + 2] for i in range(len(A) - 1)}
    sb = {B[i:i + 2] for i in range(len(B) - 1)}
    return len(sa & sb) / min(len(sa), len(sb))


# [v4.8.0] 상품이 아니라 블로그·광고·추천글이 구매링크로 잡히는 경우.
#  실측: '2026 상반기 스킨케어 트렌드, 딱 이것만 챙기세요'가 14건에,
#  '추천글루타치온필름팩 10종 인기 제품 지금 바로!'가 12건에 붙어 있었다.
#  이런 페이지는 검색어와 느슨하게 맞아떨어져서 여러 상품을 빨아들인다.
AD_TITLE_RE = re.compile(
    r"(추천\s*(글|템|제품|순위)|인기\s*(제품|템|순위)|트렌드|지금\s*바로|"
    # [v5.7.0] 영문 BEST와 '비교 분석'도 추가. 실측: '각질 제거기 추천
    # BEST 5, 비교 분석'이라는 블로그 글이 구매링크로 잡혀 있었다.
    r"베스트\s*\d|BEST\s*\d|TOP\s*\d|\d+\s*종\s*(인기|추천)|후기\s*모음|"
    r"비교\s*(정리|분석)|이것만|알아보기|총정리|모집)"
)


def looks_like_article(title: str) -> bool:
    return bool(AD_TITLE_RE.search(title or ""))


# [v5.4.0] 상품명이라기엔 너무 일반적인 값. 실측: 매칭 결과에 '화장품'
#  하나만 들어온 건이 4건 있었다. 이런 값은 어떤 검색어에도 느슨하게
#  맞아 여러 상품을 빨아들이고, 사람이 봐도 무엇인지 알 수 없다.
GENERIC_NAMES = {"화장품", "코스메틱", "스킨케어", "세트", "기획세트", "본품",
                 "상품", "제품", "뷰티", "미용", "선물세트"}


def looks_too_generic(name: str) -> bool:
    stripped = re.sub(r"[^가-힣A-Za-z0-9]", "", name or "")
    if len(stripped) < 4:
        return True
    return (name or "").strip() in GENERIC_NAMES


# [v7.1.0] 검수 대상이 아닌 큐텐 카테고리.
#  색조(013·014·016)는 발굴에서 이미 빠지고, 네일·향수는 v7.1.0부터 뺀다.
#  색상·호수·향으로 갈리는 상품군이라 이름만으로 같은 제품인지 알 수 없고,
#  하나 틀리면 반품 사유가 된다.
EXCLUDED_CATEGORIES = {"120000013", "120000014", "120000016",
                       "120000021", "120000022"}


# [v7.6.0] 판매페이지에서 가져온 제목이 상품명이 아닌 경우.
#  fetch_page_title.py가 걸러내지만, 이미 저장된 데이터에는 남아 있다.
JUNK_PAGE_TITLE_RE = re.compile(
    r"(에러|오류|error|not found|찾을 수 없|존재하지 않|삭제된|로그인|login|"
    r"접근|권한|차단|점검|준비\s*중|페이지를|잘못된|만료|쇼핑몰 제목|네이버쇼핑)", re.I)
STORE_ONLY_TITLE_RE = re.compile(
    r"^[^\s]{0,20}\s*(스토어|쇼핑몰|공식몰|store|mall|샵|shop)\s*$", re.I)


def looks_like_junk_page_title(title: str) -> bool:
    text = (title or "").strip()
    if len(text) < 5:
        return True
    return bool(JUNK_PAGE_TITLE_RE.search(text) or STORE_ONLY_TITLE_RE.match(text))


def _flat(text: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", text or "").lower()


def _brand_cross_reference(qoo10_brand: str, kr_brand: str,
                           qoo10_name: str, kr_name: str) -> bool:
    """어느 한쪽 브랜드가 반대편 문자열 안에 들어있으면 같은 브랜드로 본다.

    사전이 없어도 살릴 수 있는 경우들이다(공백·기호 무시 비교).
        큐텐 'LE LABO 르 라보 매차 26'  vs  매칭 브랜드 '르라보'
        큐텐 브랜드 '花王'(큐레루)       vs  매칭 이름 'Curel_딥 모이스처'
    이 보호가 없으면 브랜드 사전 부실이 곧 삭제로 이어진다.
    """
    pairs = ((kr_brand, qoo10_name), (qoo10_brand, kr_name),
             (qoo10_brand, kr_brand), (kr_brand, qoo10_brand))
    return any(len(_flat(a)) >= 2 and _flat(a) in _flat(b) for a, b in pairs)


def is_clear_mismatch(qoo10_brand: str, kr_brand: str,
                      qoo10_name: str, kr_name: str) -> bool:
    """오매칭이 거의 확실한 건 — 브랜드도 다르고 이름도 어긋난다.

    `looks_like_mismatch`(이름만 본다)보다 임계가 느슨한 대신,
    브랜드가 서로 다르고 어느 쪽도 반대편에 나타나지 않을 때만 적용한다.

    [왜 이렇게 좁게 잡나] 글자만으로는 완벽히 못 가른다. 임계를 조금만
    낮추면 정상 매칭이 함께 사라진다 —
        花王 '큐레루 딥 모이스처 스프레이'  =  '나수 Curel_딥 모이스처 스프레이'
        原料工房 '티트리 그린 바디워시'      =  '원료공방 그린더마 티트리 바디워시'
    둘 다 같은 제품인데 브랜드 표기만 다르다. 애매하면 남긴다 —
    남으면 사람이 3초 보고 넘기지만, 잘못 지우면 사라진 줄도 모른다.
    """
    if _brand_cross_reference(qoo10_brand, kr_brand, qoo10_name, kr_name):
        return False
    return _sim_token(qoo10_name, kr_name) < 0.5 and _sim_bigram(qoo10_name, kr_name) < 0.42


def looks_like_mismatch(qoo10_name: str, kr_name: str) -> bool:
    """[v4.4.0] 이름이 두 척도 모두 낮으면 다른 상품으로 본다.

    브랜드 상태와 무관하게 적용한다. 전수 점검에서 확인된 실패 유형이
    '같은 브랜드의 다른 제품'이었기 때문이다 — 브랜드가 일치해도 틀린다.
        워터뱅크 UV 배리어 선 세럼   -> 워터뱅크 UV 베리어 선크림
        퍼펙트 UV 스킨케어 젤        -> 퍼펙트 유브이 스프레이
        케라스타즈 블론드 압솔루 샴푸 -> 케라스타즈 방 안티 댄드러프
    브랜드만 보면 전부 통과한다.

    글자조각 임계를 0.35에서 0.45로 올렸다. 정상 매칭의 실측 하한이
    0.62였고(화이트샷 세럼 유브이 / POLA 화이트 샷 세럼 UV = 0.62,
    센텔리안24 = 1.00), 0.45까지는 여유가 있다.
    """
    return _sim_token(qoo10_name, kr_name) < 0.3 and _sim_bigram(qoo10_name, kr_name) < 0.45


def should_exclude(qoo10_brand: str, kr_brand: str, qoo10_name: str, kr_name: str,
                   brand_status: str) -> bool:
    """검수에서 뺄지 최종 판단 — 두 갈래를 합치고, 보호를 공통으로 씌운다.

    [갈래 1] 이름이 두 척도 모두 낮으면 뺀다(브랜드 무관).
             주된 실패가 '같은 브랜드의 다른 제품'이라 브랜드를 조건에
             걸면 놓친다(워터뱅크 선세럼->선크림, 퍼펙트 젤->스프레이).
    [갈래 2] 브랜드까지 다르면 임계를 조금 느슨하게 적용한다.

    [브랜드 상호참조 보호는 갈래 2에만 적용한다]
    처음엔 두 갈래 공통으로 씌웠다가 되돌렸다. 실측하니 29건이 되살아났는데
    그중 4건꼴이 '같은 브랜드의 다른 제품'이었다.
        W.DRESSROOM 퍼퓸 160ml   -> 더블유드레스룸 핸드크림 50ml
        W.DRESSROOM 퍼퓨듐 No.97 -> 더블유드레스룸 탈모완화 샴푸 No.97
    브랜드가 같으니 보호가 걸리고, 정작 다른 제품이 통과한다 — 갈래 1이
    잡으려던 바로 그 유형이다. 반면 살아난 정상 매칭은 2건꼴이었다
    (LE LABO='르라보', AESTURA='에스트라'). 이득보다 손해가 커서 뺐다.
    LE LABO 같은 건은 지워지지만, 그건 표기 차이를 글자로 못 재는 한계다.
    """
    if looks_like_mismatch(qoo10_name, kr_name):
        return True
    return brand_status == "mismatch" and is_clear_mismatch(
        qoo10_brand, kr_brand, qoo10_name, kr_name)


# [v4.6.0] 신뢰도 점수를 사람이 읽는 3등급으로 묶는다.
#  실측 분포(1,739건): A 870(50.0%) / B 752(43.2%) / C 117(6.7%)
#  A는 브랜드와 이름이 모두 확인된 구간이라 빠르게 넘길 수 있고,
#  C는 표본에서 오매칭이 다수였다. 등급을 눈에 보이게 해야 어디에
#  시간을 쓸지 정할 수 있다.
CONFIDENCE_TIERS = {
    "A": ("완전일치", "브랜드·제형·이름·용량 모두 일치"),
    "B": ("용량·수량 다름", "브랜드·제형·이름 일치. 용량이나 구성만 다름"),
    "C": ("이름 비슷", "브랜드·제형 일치. 제품명이 정확히 같지는 않음"),
    "D": ("확인 불가", "브랜드나 제형을 확인하지 못함 — 사진을 꼭 대조"),
    "S": ("세트·기획", "여러 제품이 묶인 구성 — 구성품과 수량을 확인"),
}


# [v6.4.0] 제형(형태) 사전. A등급은 '제형이 같다고 확인된 것'만 받는다.
#  같은 브랜드·같은 라인이라도 제형이 다르면 다른 상품이다. 실측 오매칭에서
#  가장 자주 나온 형태가 이것이다.
#      클렌징폼 -> 클렌징 오일   선크림 -> 선세럼   샴푸 -> 컨디셔너
#      독도 클렌저 -> 독도 클렌징 밤   미스트 -> 스프레이
#  한국에서 섞어 쓰는 말은 한 묶음으로 둔다(세럼=에센스=앰플, 토너=스킨).
#  묶지 않으면 정상 매칭이 대량으로 걸린다.
FORM_GROUPS: dict[str, list[str]] = {
    # [v6.6.0] 큐텐 소카테고리 100종 + 올리브영 카테고리 40종을 대조해
    #  만들었다. 손으로 적은 목록이 아니라 두 쇼핑몰이 실제로 나눠 파는
    #  기준이다. 큐텐이 '클렌징 오일'과 '클렌징 밤'을 다른 소카테고리로
    #  두는 것처럼, 여기서 나뉘면 소비자에게도 다른 상품이다.
    "토너": ["토너", "스킨", "화장수", "밸런싱워터"],
    "토너패드": ["토너패드", "패드"],
    "세럼": ["세럼", "에센스", "앰플", "원액", "부스터"],
    "크림": ["크림"],
    "로션": ["로션", "에멀전", "에멀젼", "밀크"],
    "아이크림": ["아이크림", "아이젤"],
    "페이스오일": ["페이스오일", "페이셜오일"],
    "올인원": ["올인원"],
    "보습젤": ["보습젤", "수딩젤", "젤리", "젤"],
    "슬리핑팩": ["슬리핑", "수면팩", "나이트팩"],
    "마스크팩": ["마스크팩", "마스크", "시트마스크"],
    "워시오프팩": ["워시오프", "씻어내는팩", "클레이팩"],
    "모공팩": ["모공팩", "코팩"],
    "아이패치": ["아이패치", "아이팩", "아이존패치"],
    "립팩": ["립팩", "립마스크"],
    "필름": ["필름"],
    "미스트": ["미스트"],
    "픽서": ["픽서", "픽스", "세팅스프레이", "메이크업픽서"],
    "스크럽": ["스크럽", "필링", "고마주", "각질제거"],
    "마사지": ["마사지크림", "마사지오일", "마사지에센스"],
    "클렌징폼": ["클렌징폼", "폼클렌저", "세안폼", "워시", "거품", "휩"],
    # --- 대분류(총칭) ---
    #  큐텐·올리브영의 중카테고리에 해당한다. 한쪽이 총칭만 말하고 다른
    #  쪽이 그 아래 소분류면 어긋난 게 아니다(FORM_PARENTS 참고).
    "클렌징": ["클렌저", "클렌징"],
    "선케어": ["선케어", "썬케어", "UV차단", "유브이차단"],
    "헤어케어": ["헤어케어"],
    "두피케어": ["두피케어", "스칼프케어"],
    "바디케어": ["바디케어"],
    "팩": ["페이스팩"],
    "클렌징오일": ["클렌징오일"],
    "클렌징밤": ["클렌징밤"],
    "클렌징워터": ["클렌징워터", "미셀라"],
    "클렌징밀크": ["클렌징밀크"],
    "클렌징크림": ["클렌징크림"],
    "클렌징젤": ["클렌징젤"],
    "세안비누": ["세안비누", "비누", "소프"],
    "세안파우더": ["세안파우더", "효소파우더"],
    "리무버": ["리무버", "클렌징티슈", "클렌징시트"],
    "선크림": ["선크림", "썬크림", "선블럭", "선블록", "선스크린", "자외선차단"],
    "선세럼": ["선세럼", "썬세럼", "선에센스"],
    "선스틱": ["선스틱"],
    "선쿠션": ["선쿠션"],
    "선젤": ["선젤"],
    "선스프레이": ["선스프레이", "선패치"],
    "태닝": ["태닝", "애프터선"],
    "쿠션": ["쿠션"],
    "파운데이션": ["파운데이션", "베이스마스터"],
    "파우더": ["파우더"],
    "마스카라": ["마스카라"],
    "립": ["립밤", "립스틱", "립글로우", "틴트", "립글로스"],
    "네일": ["네일", "매니큐어"],
    "샴푸": ["샴푸"],
    "드라이샴푸": ["드라이샴푸"],
    "컨디셔너": ["컨디셔너", "린스"],
    "트리트먼트": ["트리트먼트", "헤어팩", "아웃바스"],
    "헤어오일": ["헤어오일"],
    "헤어에센스": ["헤어에센스", "헤어세럼", "헤어앰플"],
    "헤어향수": ["헤어향수", "헤어퍼퓸", "헤어미스트"],
    "스타일링": ["왁스", "포마드", "스타일링젤", "스타일링무스", "스타일링크림", "스타일링스프레이", "헤어스프레이", "무스"],
    "염색": ["염색", "헤어컬러", "컬러트리트먼트", "컬러스프레이", "헤나", "헤어매니큐어", "새치커버", "탈색"],
    "두피에센스": ["두피에센스", "스칼프에센스", "두피토닉", "스칼프토닉", "헤어토닉", "발모"],
    "두피클렌징": ["두피클렌징", "스칼프클렌징", "스케일러"],
    "바디워시": ["바디워시", "샤워젤", "샤워", "바디샴푸", "바디클렌저"],
    "바디로션": ["바디로션", "바디밀크"],
    "바디크림": ["바디크림", "바디버터", "바디밤"],
    "바디오일": ["바디오일"],
    "바디미스트": ["바디미스트", "바디스프레이"],
    "바디파우더": ["바디파우더"],
    "데오도란트": ["데오도란트", "데오드란트", "데오", "땀시트"],
    "핸드크림": ["핸드크림", "핸드로션"],
    "핸드워시": ["핸드워시", "손소독"],
    "풋케어": ["풋크림", "풋로션", "발각질", "발바닥패치", "풋패치"],
    "여성청결": ["여성청결", "이너케어"],
    "제모": ["제모제", "제모시트", "왁싱"],
    "면도기": ["면도기", "셰이버"],
    "향수": ["향수", "퍼퓸", "오드", "파르팜", "롤온", "코롱"],
    "입욕": ["입욕", "배스솔트", "바스밤", "입욕제"],
    "브러시": ["브러시", "브러쉬", "빗", "퍼프"],
    "디바이스": ["디바이스", "고데기", "롤러", "이어스틱", "족집게", "가위", "헤어롤"],
}



# [v7.15.0] 복합 제형 표기. '크림 마스크'는 크림이 아니라 마스크팩이다.
#  제형 사전이 글자를 찾는 방식이라 '크림'과 '마스크팩'을 둘 다 잡고,
#  큐텐 쪽 '크림'과 교집합이 생겨 같은 제품으로 판정됐다.
#  실측: 셀리맥스 '브라이트닝 크림 35ml' -> '브라이트닝 크림 마스크 4매'.
#
#  뒤에 오는 말이 제품의 정체다. '크림 마스크'는 마스크, '앰플 마스크'도
#  마스크다. 앞의 말은 내용물을 설명할 뿐이다. 그래서 앞쪽 제형을 지운다.
COMPOUND_FORMS = [
    (re.compile(r"크림\s*마스크"), "크림", "마스크팩"),
    (re.compile(r"젤\s*마스크"), "보습젤", "마스크팩"),
    (re.compile(r"(?:세럼|에센스|앰플)\s*마스크"), "세럼", "마스크팩"),
    (re.compile(r"오일\s*미스트"), "헤어오일", "미스트"),
    (re.compile(r"밤\s*스틱"), "밤", "선스틱"),
]


def extract_forms(text: str) -> set:
    flat = _flat(text)
    found = {group for group, words in FORM_GROUPS.items()
             if any(_flat(w) in flat for w in words)}
    # 복합 표기는 뒤에 오는 말이 제품의 정체다. 앞의 말은 내용물 설명이다.
    for rx, drop, keep in COMPOUND_FORMS:
        if rx.search(text or "") and keep in found:
            found.discard(drop)
    return found


# [v6.7.0] 대분류 -> 소분류. 큐텐·올리브영의 중카테고리와 소카테고리
#  관계를 그대로 옮겼다. 한쪽이 '클렌징'까지만 말하고 다른 쪽이
#  '클렌징 폼'이면 같은 것을 가리킨다 — 상품명에 총칭만 쓰는 경우가 흔하다.
FORM_PARENTS: dict[str, set] = {
    "클렌징": {"클렌징폼", "클렌징오일", "클렌징밤", "클렌징워터", "클렌징밀크",
              "클렌징크림", "클렌징젤", "세안비누", "세안파우더", "리무버"},
    "선케어": {"선크림", "선세럼", "선스틱", "선쿠션", "선젤", "선스프레이", "태닝"},
    "헤어케어": {"샴푸", "드라이샴푸", "컨디셔너", "트리트먼트", "헤어오일",
               "헤어에센스", "헤어향수", "스타일링", "염색"},
    "두피케어": {"두피에센스", "두피클렌징"},
    "바디케어": {"바디워시", "바디로션", "바디크림", "바디오일", "바디미스트",
               "바디파우더", "데오도란트", "핸드크림", "핸드워시", "풋케어"},
    "팩": {"마스크팩", "워시오프팩", "모공팩", "아이패치", "립팩", "필름", "슬리핑팩"},
}


# [v7.2.0] 색상·호수. 같은 제품의 다른 색은 다른 상품이다.
#  실측: 달바 '워터풀 톤업 선크림 그린'과 '퍼플'은 브랜드·제형·용량이
#  모두 같아 걸러낼 요소가 없었다. 실제로는 핑크/퍼플/그린 세 종류이고
#  피부톤에 따라 고르는 별개 상품이다(공식 상세페이지 확인).
COLOR_WORDS = ["핑크", "퍼플", "그린", "블루", "레드", "옐로우", "오렌지",
               "화이트", "블랙", "베이지", "브라운", "라벤더", "민트", "피치",
               "로즈", "아이보리", "실버", "골드", "바이올렛", "코랄", "누드",
               "그레이", "네이비"]
SHADE_RE = re.compile(r"(\d{1,2})\s*호")


def extract_colors(text: str) -> set:
    flat = _flat(text)
    found = {c for c in COLOR_WORDS if c in flat}
    found |= {f"{m}호" for m in SHADE_RE.findall(text or "")}
    return found


def color_status(qoo10_name: str, kr_name: str) -> str:
    """색상·호수 일치 여부. 한쪽이라도 없으면 'unknown'(판단 보류).

    한쪽에만 색이 적힌 경우가 흔하다(큐텐은 '그린'을 쓰는데 한국은
    옵션으로 빼서 상품명에 없음). 그건 어긋난 게 아니라 알 수 없는 것이다.
    """
    a, b = extract_colors(qoo10_name), extract_colors(kr_name)
    if not a or not b:
        return "unknown"
    return "match" if (a & b) else "mismatch"


# [v7.12.0] 대립 제형쌍 — 이 둘이 서로 어긋나면 다른 상품이다.
#  제형 사전만으로는 못 가른다. 예를 들어 '아이크림'과 '크림'은 둘 다
#  '크림'을 품고 있어 교집합이 생기고, '선세럼'과 '선크림'도 마찬가지다.
#  실측 오매칭 목록 261건과 정상 매칭을 대조해 이 쌍들만 뽑았다.
#      샴푸 vs 컨디셔너      올라플렉스 No.5 컨디셔너 -> No.4 샴푸
#      샴푸 vs 트리트먼트    케라시스 스칼프 트리트먼트 -> 스칼프 샴푸
#      선세럼 vs 선크림      라네즈 워터뱅크 선세럼 -> 선크림
#      클렌징폼 vs 클렌징오일/밤   1025 독도 클렌저 -> 클렌징 밤
#      크림 vs 아이/핸드/바디크림  네이처리퍼블릭 콜라겐 크림 -> 아이크림
#      미스트 vs 픽서
#
#  ⚠️ '한쪽에만 있을 때'만 적용한다. 세트 상품은 여러 제형을 함께 담아
#  ('샴푸+트리트먼트 세트') 양쪽에 다 들어 있으면 대립이 아니다.
CONFLICTING_FORMS = [
    ("아이크림", "크림"), ("핸드크림", "크림"), ("바디크림", "크림"),
    ("선세럼", "선크림"), ("샴푸", "컨디셔너"), ("샴푸", "트리트먼트"),
    ("미스트", "픽서"), ("클렌징폼", "클렌징오일"), ("클렌징폼", "클렌징밤"),
    # [v7.23.0] 세럼과 크림. 흔한 조합이라 영향이 클까 걱정했는데 실측
    #  4건뿐이고 전부 실제 오매칭이었다. 같은 라인에서 제형만 다른 제품이
    #  많아 이름 유사도로는 안 걸린다.
    #      리쥬란 더마힐러 모이스처 앰플 30ml -> 모이스처 크림 60ml
    #      아누아 어성초77 B3 징크 세럼 -> 어성초77 B3 징크 수딩 크림
    ("세럼", "크림"),
]


# 세부 제형은 상위어를 문자열로 포함한다('아이크림'에 '크림'). 그래서
#  '아이크림'이 잡히면 '크림'도 함께 잡혀, 단순 비교로는 대립을 못 본다.
#  세부 쪽이 있으면 상위어는 없는 것으로 친다.
FORM_SPECIALIZATIONS = {"아이크림": "크림", "핸드크림": "크림", "바디크림": "크림",
                        "선세럼": "세럼", "선크림": "크림", "헤어오일": "오일",
                        "바디오일": "오일", "페이스오일": "오일",
                        "클렌징오일": "오일", "바디로션": "로션"}


def _narrow_forms(forms: set) -> set:
    out = set(forms)
    for special, broad in FORM_SPECIALIZATIONS.items():
        if special in out:
            out.discard(broad)
    return out


def has_form_conflict(qoo10_name: str, kr_name: str) -> bool:
    a = _narrow_forms(extract_forms(qoo10_name))
    b = _narrow_forms(extract_forms(kr_name))
    if not a or not b:
        return False
    for x, y in CONFLICTING_FORMS:
        if x in a and y in b and x not in b and y not in a:
            return True
        if y in a and x in b and y not in b and x not in a:
            return True
    return False


# [v7.16.0] 핵심 성분·라인 키워드. 화장품은 성분으로 라인을 나누는 경우가
#  많아, 같은 브랜드라도 성분이 다르면 다른 제품이다.
#  실측: 아누아 'PDRN 히알루론산 미스트'가 'PDRN 콜라겐 글로우 세럼
#  미스트'와 A등급으로 묶여 있었다. 브랜드·제형·용량이 모두 같아
#  걸러낼 요소가 없었다.
#
#  ⚠️ 브랜드가 확인된 경우에만 쓴다. 브랜드도 모르는데 성분까지 따지면
#  판단 근거가 약한 것들이 무더기로 걸린다(전체 40건 중 브랜드 일치는 8건).
#  또 '한쪽에만 있을 때'가 아니라 '양쪽 다 있는데 전혀 안 겹칠 때'만 본다 —
#  한쪽이 성분을 생략한 경우는 흔하다.
INGREDIENT_KEYWORDS = [
    "히알루론산", "히알루론", "콜라겐", "PDRN", "레티놀", "레티날",
    "나이아신아마이드", "세라마이드", "펩타이드", "글루타치온", "어성초",
    "시카", "판테놀", "아젤라", "트라넥삼산", "살리실산", "스쿠알란",
    "병풀", "프로폴리스", "녹두", "쑥", "율무",
]


def extract_ingredients(text: str) -> set:
    flat = _flat(text)
    return {k for k in INGREDIENT_KEYWORDS if _flat(k) in flat}


def ingredient_conflict(qoo10_name: str, kr_name: str) -> bool:
    """양쪽이 서로에게 없는 성분을 각각 내세우면 다른 제품이다.

    '하나도 안 겹칠 때'만 보면 놓친다. 실측 사례가 그랬다.
        아누아 'PDRN 히알루론산 미스트'  vs  'PDRN 콜라겐 글로우 세럼 미스트'
        -> PDRN 이 겹쳐서 통과했지만 히알루론산과 콜라겐은 다른 라인이다.

    한쪽만 성분을 밝힌 경우는 걸리지 않는다 — 상품명에서 성분을 생략하는
    일이 흔하기 때문이다. 양쪽 다 밝혔는데 서로 다를 때만 본다.
    """
    a, b = extract_ingredients(qoo10_name), extract_ingredients(kr_name)
    if not a or not b:
        return False
    return bool(a - b) and bool(b - a)


def form_status(qoo10_name: str, kr_name: str) -> str:
    """제형 일치 여부. 한쪽이라도 못 읽으면 'unknown'(판단 보류).

    [v6.7.0] 대분류/소분류를 나눠서 본다.
      · 소분류끼리 겹치면 일치
      · 한쪽이 대분류만 말하고 다른 쪽이 그 아래 소분류면 일치
        ('클렌징' vs '클렌징 폼', '선케어' vs '선크림')
      · 소분류가 서로 다르면 불일치 ('클렌징 폼' vs '클렌징 오일')
    대분류 이름은 소분류 문자열에 포함돼 있어서('클렌징폼'에 '클렌징'),
    그냥 교집합을 보면 서로 다른 소분류가 같은 것으로 잡힌다. 그래서
    비교는 소분류로만 하고, 대분류는 포함관계 판정에만 쓴다.
    """
    a, b = extract_forms(qoo10_name), extract_forms(kr_name)
    if not a or not b:
        return "unknown"
    # 대립 제형은 교집합이 있어도 다른 상품이다('아이크림'과 '크림').
    if has_form_conflict(qoo10_name, kr_name):
        return "mismatch"
    parents = set(FORM_PARENTS)
    spec_a, spec_b = a - parents, b - parents
    if spec_a & spec_b:
        return "match"
    if not spec_a and not spec_b:          # 양쪽 다 대분류만 말했다
        return "match" if (a & b) else "mismatch"
    if not spec_a and _covers(a, spec_b):
        return "match"
    if not spec_b and _covers(b, spec_a):
        return "match"
    return "mismatch"


def _covers(broad: set, specific: set) -> bool:
    """broad가 '대분류만' 말하고 있고, specific이 그 아래 소분류인가.

    ⚠️ broad 쪽에 자기 소분류가 이미 있으면 적용하지 않는다. 안 그러면
    '클렌징 폼'과 '클렌징 오일'이 둘 다 '클렌징'을 품고 있어 서로 같은
    것이 돼버린다 — 정작 갈라야 할 경우를 놓친다.
    """
    for parent in broad:
        children = FORM_PARENTS.get(parent)
        if not children:
            continue
        if broad & children:      # 대분류를 말하면서 소분류도 특정했다
            continue
        if children & specific:
            return True
    return False


# [v7.13.0] 세트·기획 상품. 여러 제품이 묶여 있어 다른 등급의 판정이
#  통하지 않는다.
#   · 제형이 여러 개 잡혀 대립 판정이 오작동한다. 실측: '퍼펙트9 토너
#     로션 크림 세트'와 '퍼펙트9 2종세트+핸드크림 증정'이 크림 vs 핸드크림
#     대립으로 읽혀 잘못 걸렸다(27건 중 4건, 14.8%).
#   · 용량 비교도 성립하지 않는다. 구성품이 여럿이라 어느 용량인지 모른다.
#   · 가격 비교도 구성이 같아야 의미가 있다.
#  그래서 따로 S등급으로 빼고, 검수에서 구성품과 수량을 직접 보게 한다.
SET_PATTERN = re.compile(
    r"세트|SET|기획|증정|본품\s*\+|택\s*\d|\d+\s*종\b|묶음|패키지|선물|"
    r"\+\s*\d+\s*(개|매|장|ml|g)|\d+\s*(개입|매입|본|병)\s*세트", re.I)


# [v7.21.0] 자외선 차단 등급 표기. 여기 쓰인 '+'는 등급을 나타내는
#  기호이지 '제품 A + 제품 B'의 '+'가 아니다. 둘을 구분하지 않으면
#  'SPF50+ PA++++ 50ml' 이 '+ 50ml' 로 읽혀 멀쩡한 선크림이 세트로 잡힌다.
#
#  실측으로 확인된 표기 형태(전부 같은 뜻이다):
#      SPF50+ PA++++      SPF 50+ PA++++     SPF50+/PA++++
#      SPF50+PA++++       SPF50+, PA++++     SPF50+ / PA++++
#      SPF38 PA++         SPF20 PA++         SPF50+
#  PA 등급은 PA+ ~ PA++++ 네 단계이고, SPF 는 숫자 뒤에 '+'가 붙을 수 있다
#  (SPF50+ 는 'SPF 50 이상'이라는 뜻). 둘 사이 구분자는 공백·슬래시·쉼표가
#  섞여 나오고 아예 붙어 있기도 하다.
SPF_NOTATION_RE = re.compile(
    r"SPF\s*\d+\s*\+?(?:\s*[/,]?\s*PA\s*\+{1,4})?|PA\s*\+{1,4}", re.I)


def is_set_by_plus(text: str) -> bool:
    """'+' 양쪽에 서로 다른 제형이 있으면 세트다.

    [왜 이 방식인가] 제형이 두 개 이상 잡히면 세트로 보는 방식은 못 쓴다.
    상품명에 카테고리 설명이 붙거나 대분류·소분류가 함께 잡히는 일이 흔해
    실측 255건이 걸렸고 그중 A등급 86건이 멀쩡한 단품이었다
    ('클렌징'+'클렌징밤', '토너'+'토너패드', '미스트'+'바디미스트').

    '+' 를 경계로 나눠 양쪽 제형을 각각 보면 이 문제가 사라진다.
        큐리페어 멜라 크림 35ml + 큐리페어 더마 앰플 50ml
          좌 {크림}  우 {세럼}  -> 서로 다름 -> 세트
        워터 슬리핑 마스크 1+1
          우쪽에 제형어가 없음 -> 세트 아님
    1+1·2+1 같은 수량 표기는 '+' 뒤에 제형어가 없어 자동으로 걸러진다.
    실측 24건이 잡히고 대부분 진짜 세트였다.
    """
    text = SPF_NOTATION_RE.sub(" ", text or "")
    if "+" not in text and "＋" not in text:
        return False
    parts = re.split(r"[+＋]", text)
    forms = [_narrow_forms(extract_forms(part)) for part in parts]
    nonempty = [f for f in forms if f]
    if len(nonempty) < 2:
        return False
    return bool(nonempty[0] ^ nonempty[1])


def is_set_product(qoo10_name: str, kr_name: str) -> bool:
    # SPF/PA 표기를 먼저 지운다. 'SPF50+ PA++++ 50ml' 에서 마지막 '+'와
    # 용량이 붙어 '+ 50ml' 로 읽히면서 멀쩡한 선크림이 세트로 잡혔다.
    # [v7.26.0] 증정 조각을 먼저 떼고 판정한다(사장님 방침: 증정은
    #  가격에 사실상 영향이 없으니 본품끼리만 비교한다). 떼지 않으면
    #  '크림 50ml + 휴대용 미니 15ml' 같은 단품이 세트로 사라진다.
    # [v7.26.0] 증정 조각을 떼고 판정한다(사장님 방침: 증정은 가격에
    #  사실상 영향이 없으니 본품끼리만 비교한다). 떼지 않으면 '크림 50ml
    #  + 휴대용 미니 15ml' 같은 단품이 세트로 사라진다.
    #  단, 떼는 건 **한국측만**이다. 큐텐측은 내가 파는 구성이라 증정도
    #  준비해야 하고, 구성이 다르면 그건 실제로 문제가 되는 차이다.
    k_main, _, k_other = split_bonus(kr_name)
    combined = SPF_NOTATION_RE.sub(" ", f"{qoo10_name} {k_main}")
    if SET_PATTERN.search(combined):
        return True
    if k_other:
        return True             # '+' 뒤가 다른 제품이면 비교가 성립 안 함
    return is_set_by_plus(qoo10_name) or is_set_by_plus(k_main)


def confidence_tier(confidence: int, brand_status: str = "match",
                    vol_mismatch: bool = False, name_ok: bool = True,
                    single_source: bool = False, form: str = "match",
                    name_exact: bool = True, color: str = "unknown",
                    is_set: bool = False, ingredient_mismatch: bool = False,
                    count_mismatch: bool = False) -> str:
    """등급을 '무엇이 어긋났는가'로 나눈다.

    [v7.0.0 개편] 비교 요소를 브랜드 -> 제형 -> 이름 -> 용량 순으로 본다.
        A  네 가지 모두 일치
        B  브랜드·제형·이름 일치, 용량/수량만 다름 (가격 비교 시 환산 필요)
        C  브랜드·제형 일치, 제품명이 정확히 같지는 않음 (표기 차이~다른 제품)
        D  브랜드나 제형을 확인하지 못함 (사진 대조 필요)

    D를 마지막에 둔 이유: 앞의 셋은 '무엇이 얼마나 일치하는가'인데 D는
    '판단할 근거가 없다'로 성격이 다르다. 실측 1,413건 중 437건이 여기
    해당하고, 이 구간이 실제 검수의 본체다.

    단독통과(소스 1곳)는 등급이 아니라 배지로 표시한다 — '몇 곳이
    확인해줬는가'는 일치 여부와 다른 축이라, 등급에 섞으면 이름이 다른
    단독통과가 C인지 D인지 정해지지 않는다.
    """
    # 세트는 제형·용량·가격 비교가 모두 성립하지 않는다. 브랜드조차
    #  확인 못 했으면 D가 맞지만, 브랜드가 맞으면 S로 따로 뺀다.
    # 성분이 전혀 안 겹치면 같은 브랜드라도 다른 제품이다.
    #  세트보다 먼저 본다 — 세트 구성이 달라도 성분이 아예 다르면 오매칭이다.
    if ingredient_mismatch and brand_status == "match":
        return "D"
    if is_set and brand_status == "match":
        return "S"
    if brand_status != "match" or form != "match":
        return "D"
    # 색이 서로 다르면 같은 제품의 다른 색이다 — 별개 상품으로 본다.
    if color == "mismatch":
        return "D"
    # [v7.24.0] 이름을 먼저 보되, 이름이 애매하면 용량까지 확인하고 나서
    #  등급을 정한다. 예전엔 이름에서 걸리면 바로 C로 보내고 용량을 아예
    #  안 봤다. 그 탓에 '같은 제품인데 용량만 다른' 건이 C에 숨었다.
    #      라보에이치 두피강화 탈모샴푸 700ml -> 400ml   (이름 유사도 0.33)
    #      스킨1004 마다가스카르 센텔라 앰플 55ml -> 100ml
    #      닥터지 레드블레미쉬 수딩 토너 300ml -> 500ml
    #  실측 41건이 이 경우였고 전부 '용량만 다른 같은 제품'이었다.
    #
    #  C 에 있으면 '이름이 왜 다른지'를 봐야 하고, B 에 있으면 '용량만'
    #  확인하면 된다. 어느 쪽을 봐야 하는지가 등급으로 갈려야 한다.
    if not name_exact:
        return "B" if vol_mismatch else "C"
    # [v7.25.0] 총 매수·개수 불일치도 용량 불일치와 같이 B로 내린다
    #  (가격 비교 시 환산 필요). 이름이 일치하는 구간(A 후보)만 적용한다 —
    #  실측한 범위가 여기까지다. C 구간(이름 불일치)까지 넓히는 건 영향을
    #  측정한 뒤에 한다(설계이력 1-2).
    if vol_mismatch or count_mismatch:
        return "B"
    return "A"


# [v5.8.0] 용량 파싱을 믿을 수 있는 최소값. 상품명에서 숫자를 뽑다 보니
#  세트 표기나 성분 함량에서 엉뚱한 값을 집는다 — 실측: '큐리페어 멜라크림
#  35ml'의 한국 쪽 용량이 3ml로, '리드르 샷 1000 에센스 15ml'가 1ml로
#  잡혔다. 이런 값으로 '용량 불일치' 판정을 내리면 같은 제품이 B로
#  내려간다. 5ml 미만은 판단 보류로 본다(진짜 5ml 미만 제품은 향수
#  샘플 정도이고, 그건 애초에 가격 비교 대상이 아니다).
MIN_TRUSTED_VOLUME_ML = 5.0


def volume_mismatch(qoo10_vol, kr_vol) -> bool:
    if qoo10_vol is None or kr_vol is None:
        return False
    if qoo10_vol < MIN_TRUSTED_VOLUME_ML or kr_vol < MIN_TRUSTED_VOLUME_ML:
        return False          # 파싱을 믿을 수 없다
    return abs(qoo10_vol - kr_vol) >= 0.1


def match_confidence(qoo10_name: str, kr_name: str, brand_status: str,
                     vol_mismatch: bool, single_source: bool) -> int:
    """이 매칭이 얼마나 믿을 만한지 0~4로 매긴다(높을수록 확실).

    [왜 필요한가] 검수페이지 2,100건을 전수 점검해보니 신뢰도가 고르지 않다.
    브랜드가 확인되고 이름도 거의 일치하는 건이 있는가 하면, 브랜드도 못
    맞추고 이름도 절반만 겹치는 건이 섞여 있다. 섞여 있으면 확실한 건에도
    같은 주의를 쓰게 되고, 정작 위험한 건을 놓친다.

    자동으로 버리지는 않는다. 낮은 점수 구간에도 정상 매칭이 30%쯤 있다
    (실측 표본 10건 중 3건 — '花王 큐레루'와 '나수 Curel'은 같은 제품,
    'LE LABO'와 '르라보'도 같은 제품). 순서만 바꾸고 판단은 사람이 한다.
    """
    score = 0
    score += 2 if brand_status == "match" else (1 if brand_status == "unknown" else 0)
    t, b = _sim_token(qoo10_name, kr_name), _sim_bigram(qoo10_name, kr_name)
    score += 2 if (t >= 0.5 or b >= 0.6) else (1 if (t >= 0.3 or b >= 0.35) else 0)
    if vol_mismatch:
        score -= 1          # 용량이 다르면 다른 SKU이거나 오매칭이다
    if single_source:
        score -= 1          # 합의 없이 네이버 단독으로 통과한 건
    return max(score, 0)


def check_brand(orig_brand: str, kr_brand_text: str, brand_dict: dict,
                kr_product_name: str = "") -> str:
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
        # [v5.2.0] 양방향으로 본다. 사전값이 판매처명 표기라 더 길 수 있고
        # (Purito -> '퓨리토서울'), 반대로 판매처가 짧게 쓸 수도 있다.
        # 한 방향만 보면 '퓨리토서울'과 '퓨리토'가 서로 남남이 된다.
        if any(c.lower() in kr_brand_lower or kr_brand_lower in c.lower()
               for c in candidates if c):
            return "match"
        # [v5.3.0] 브랜드 칸에 판매처명이 들어오는 경우가 많다.
        #     cellmedics -> 브랜드칸 '더리즈', 상품명 '셀메딕스 MGF 리턴 크림'
        #     DANONAL    -> 브랜드칸 '마실',   상품명 '다노날 헤어 두피토닉'
        # 브랜드 칸만 보면 같은 제품인데도 '브랜드가 다릅니다'가 된다.
        # 상품명에 브랜드가 들어있으면 맞은 것으로 본다.
        name_lower = (kr_product_name or "").lower()
        if name_lower and any(c.lower() in name_lower for c in candidates if c and len(c) >= 2):
            return "match"
        return "mismatch"
    orig_alnum = re.sub(r"[^a-z0-9]", "", orig_brand.lower())
    kr_alnum = re.sub(r"[^a-z0-9]", "", kr_brand_lower)
    if orig_alnum and len(orig_alnum) >= 2 and orig_alnum in kr_alnum:
        return "match"

    # [v7.11.0] 사전에 없어도, 큐텐 브랜드가 한국 상품명에 그대로 들어
    #  있으면 같은 브랜드다. 네이버가 주는 brand 칸에는 브랜드가 아니라
    #  판매처명이 자주 들어온다 — 실측 D등급 78건 중 72건이 이 경우였다.
    #      viviscal -> brand '슈퍼대디',  상품명 '비비스칼 프로 viviscal pro'
    #      SYRS     -> brand '디디에즈',  상품명 'SYRS 시르즈 시카 엑소좀'
    #      呂       -> brand '아모레퍼시픽', 상품명 '려 루트젠 두피에센스'
    #  v5.3.0에서 상품명 참조를 넣었지만 '사전에 대응이 있을 때'로 한정해,
    #  사전에 없는 이 브랜드들은 상품명을 볼 기회조차 없었다.
    #
    #  ⚠️ 4자 이하는 받지 않는다. 짧은 영문은 다른 단어에 우연히 들어간다
    #  ('LOA'가 'FLOAT'에, 'CURE'가 'SECURE'에). 한글·한자 브랜드는
    #  2자만 돼도 상품명에 그대로 쓰이므로 따로 허용한다.
    name_alnum = re.sub(r"[^a-z0-9]", "", (kr_product_name or "").lower())
    #  4자는 받되 상품명 '앞부분'에 있을 때만 — 상품명은 대개 브랜드로
    #  시작한다. 중간에 우연히 들어간 경우를 걸러낸다.
    if orig_alnum and len(orig_alnum) >= 5 and orig_alnum in name_alnum:
        return "match"
    if orig_alnum and len(orig_alnum) == 4 and name_alnum.startswith(orig_alnum):
        return "match"
    orig_cjk = re.sub(r"[^가-힣\u4E00-\u9FFF]", "", orig_brand)
    if orig_cjk and len(orig_cjk) >= 1 and orig_cjk in (kr_product_name or ""):
        return "match"
    if re.search(r"[\u30A0-\u30FF\u3040-\u309F]", orig_brand):
        return "unknown"
    # [v4.2.1] 영문 원본 브랜드를 한글 판매처명과 직접 비교할 수는 없다.
    # 가나와 똑같은 이유인데 영문만 빠져 있었다 — 실측 사고:
    #     큐텐 'LE LABO' vs 네이버 '르라보'  -> mismatch로 표시
    # 같은 브랜드인데 '브랜드가 다릅니다' 경고가 붙었다. 브랜드 불일치
    # 813건 중 245건(30%)이 이 유형이었다. 사전에 대응이 없으면 비교
    # 자체가 불가능하므로 '판단불가'가 맞다. 판매처명에 라틴문자가
    # 섞여 있으면(예: '르라보 (LE LABO)') 위 alnum 비교가 이미 처리한다.
    if not re.search(r"[A-Za-z]", kr_brand_lower):
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
    # 제외한 건은 버리지 않고 파일로 남긴다 — 자동 판정이 틀렸을 때
    # 무엇이 사라졌는지 볼 수 없으면 고칠 수도 없다.
    excluded_mismatch: list[dict] = []
    # [v4.7.0] 사람이 눈으로 확인해 뺀 목록. 자동 규칙으로는 못 거르지만
    # 명백히 다른 제품인 것들이다(C등급 117건을 전수 확인해 98건 제외,
    # 19건은 같은 제품으로 판단해 남겼다 — 花王 큐레루=나수 Curel,
    # 資生堂 엘릭서=시세이도 엘릭시르 등 브랜드 표기만 다른 경우).
    # 파일로 두는 이유: 자동 규칙을 무리하게 넓히면 정상 매칭까지 사라진다.
    # 판단 근거가 사람인 건 사람이 관리하는 목록에 둔다.
    # [v5.6.0 기준 변경] 판단 기준은 '원산지'가 아니라 '한국에서 살 수 있는가'다.
    #  이 사업은 한국에서 사서 큐텐재팬에 파는 구조이므로, 해외 브랜드라도
    #  국내 유통이 있으면 매입가와 큐텐 판매가를 비교할 여지가 있다.
    #  실제로 비오더마·라로슈포제·큐렐·케라스타즈·시세이도·록시탕 등은
    #  국내 약국·올리브영·백화점·살롱에서 정상 유통된다 — 처음엔 이걸
    #  '일본·유럽 브랜드'라는 이유로 통째로 뺐는데 잘못된 기준이었다.
    #  이제 목록에는 '국내 유통이 없는' 브랜드만 남긴다(일본 드럭스토어·
    #  통신판매 전용 등 34종).
    #
    # [v5.0.0] 국내 유통이 없는 브랜드는 애초에 검수 대상이 아니다.
    #  이 사업은 한국에서 사서 큐텐재팬에 파는 구조라, 일본·유럽 브랜드
    #  상품은 한국 매입가가 더 비싸거나 아예 유통되지 않는다. 그런데도
    #  발굴에 섞여 들어와 검증을 소모하고, 억지로 매칭되면 오매칭이 된다
    #  (실측: 花王 비오레 -> 지에프코스 선크림, ブルガリ 향수 -> 노에비아 크림).
    #  브랜드 목록으로 관리한다 — 자동 판별이 어렵다. 가타카나라고 해외가
    #  아니다(アヌア=아누아, メディキューブ=메디큐브는 한국 브랜드다).
    # [v7.14.0] 로컬 크롬으로 수집한 판매페이지 정보. 검증 데이터의 brand
    #  칸은 판매처가 자기 스토어명을 넣는 경우가 많아 신뢰도가 낮은데,
    #  여기 담긴 brand 는 상품 페이지에서 직접 읽은 값이라 정확하다.
    #  실측: 이걸로 대조해 오매칭 187건을 찾아냈다(나이키 운동화·후지필름
    #  카메라·프라모델까지 검수 목록에 올라와 있었다).
    #  다음 회차에도 자동으로 대조되도록 자료를 저장소에 남긴다.
    collected_path = DATA / "collected_pages.json"
    collected = {}
    if collected_path.exists():
        try:
            collected = json.loads(collected_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[경고] collected_pages.json 읽기 실패: {e}")
    print(f"[수집자료] {len(collected)}건 "
          f"(브랜드 {sum(1 for v in collected.values() if v.get('brand'))}건)")

    foreign_path = DATA / "foreign_brands.json"
    foreign_brands = set()
    if foreign_path.exists():
        try:
            foreign_brands = set(json.loads(foreign_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"[경고] foreign_brands.json 읽기 실패: {e}")
    print(f"[해외브랜드] {len(foreign_brands)}종 등록됨")

    manual_path = DATA / "manual_exclusions.json"
    manual_excluded = set()
    if manual_path.exists():
        try:
            manual_excluded = {str(m.get("goods_no"))
                               for m in json.loads(manual_path.read_text(encoding="utf-8"))}
        except (OSError, ValueError) as e:
            print(f"[경고] manual_exclusions.json 읽기 실패: {e}")
    print(f"[수동제외] {len(manual_excluded)}건 등록됨")

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
    stats = {"no_link": 0, "sold_out": 0, "obsolete": 0, "no_qoo10_match": 0,
             "select_type": 0, "collab": 0, "brand_name_mismatch": 0, "manual": 0, "article": 0, "foreign": 0, "generic": 0, "excluded_category": 0, "ok": 0}
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

        # [v4.4.0 제외] 이름이 두 척도 모두 낮으면 다른 상품으로 보고 뺀다.
        # v4.3.0에서는 '브랜드도 다를 때'만 뺐는데, 전수 점검에서 드러난
        # 주된 실패가 '같은 브랜드의 다른 제품'이었다(선세럼↔선크림,
        # 젤↔스프레이, 블론드샴푸↔비듬샴푸). 브랜드 조건을 떼야 잡힌다.
        # 브랜드만 다르고 이름이 맞는 건은 그대로 남긴다 — 사전이 부실해
        # 생기는 오판이 많기 때문이다.
        # [v4.5.0 추가] 브랜드까지 다른 건은 임계를 조금 더 느슨하게 적용한다.
        # 브랜드가 서로 다르고 어느 쪽도 반대편 이름에 안 나타나면, 이름이
        # 절반쯤 겹쳐도 다른 제품인 경우가 대부분이었다(실측 표본 8건 전부).
        # [v7.1.0] 네일·향수는 색조와 같은 이유로 대상이 아니다. 발굴 단계에서
        #  빼도록 고쳤지만, 이미 쌓인 238건은 여기서 거른다.
        if str(q.get("category_gdlc_cd")) in EXCLUDED_CATEGORIES:
            stats["excluded_category"] += 1
            continue

        if (q.get("brand") or "").strip() in foreign_brands:
            stats["foreign"] += 1
            continue

        if looks_too_generic(x.get("name") or ""):
            stats["generic"] += 1
            continue

        if looks_like_article(x.get("name") or ""):
            stats["article"] += 1
            excluded_mismatch.append({
                "goods_no": x.get("goods_no"), "qoo10": translated_kr,
                "matched": x.get("name"), "url": x.get("product_url"),
                "reason": "상품이 아니라 광고/추천글로 보임",
            })
            continue

        if str(x.get("goods_no")) in manual_excluded:
            stats["manual"] += 1
            continue

        if should_exclude(q.get("brand", ""), x.get("brand", ""), translated_kr,
                          x.get("name") or "",
                          check_brand(q.get("brand", ""), x.get("brand", ""), brand_dict, x.get("name") or "")):
            stats["brand_name_mismatch"] += 1
            excluded_mismatch.append({
                "goods_no": x.get("goods_no"),
                "qoo10": translated_kr, "qoo10_brand": q.get("brand"),
                "matched": x.get("name"), "matched_brand": x.get("brand"),
                "url": x.get("product_url"),
            })
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
        # [v7.6.0] 이미 저장된 값에도 '에러 페이지'·'○○ 스토어'가 섞여 있다.
        #  재검증 전까지 그대로 화면에 뜨므로 표시 단계에서도 거른다.
        _real = x.get("real_page_title") or ""
        if _real and looks_like_junk_page_title(_real):
            _real = ""
        kr_name_display = _real or naver_original_name or x.get("name") or ""

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
        # [v7.14.0] 수집한 실제 브랜드가 있으면 그걸로도 대조한다. 검증
        #  브랜드칸으로는 맞았는데 실제 브랜드가 다르면 오매칭이다.
        #  실측: NEEDLY 상품에 앤티퍼디(뉴질랜드 브랜드)가 붙어 있었다.
        brand_status = check_brand(orig_brand, x.get("brand", ""), brand_dict, x.get("name") or "")
        _col = collected.get(str(x.get("goods_no"))) or {}
        _col_brand = (_col.get("brand") or "").strip()
        if _col_brand and brand_status == "match":
            if check_brand(orig_brand, _col_brand, brand_dict,
                           _col.get("name") or "") == "mismatch":
                brand_status = "mismatch"
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
        # [v7.26.0] 등급 판정용 세트 여부는 '검수 화면에 보이는 이름'으로
        #  낸다. 예전엔 검증 승자의 name 을 넣었는데, 로컬 수집(v7.10.0)으로
        #  갱신된 정확한 상품명에 '더블기획'·'기획(+10ml)' 이 적혀 있어도
        #  판정이 그걸 못 봤다 — 실측 38건이 이 이유로 세트를 놓쳤다.
        # [v7.27.0] 큐텐 증정이 한국 구매처보다 많으면 그 초과분을 업로드용
        #  제목에서 지운다(사장님 지시). 못 지킬 구성을 파는 셈이 되기
        #  때문이다. 등급 판정도 지운 뒤 기준으로 낸다 — 지웠는데도 세트로
        #  남으면 검수에서 볼 이유가 없다.
        _stripped_jp, _dropped_gifts = strip_excess_gifts(
            q["title"], translated_kr, kr_name_display)
        translated_for_tier = translated_kr
        if _dropped_gifts:
            _tk_parts = re.split(r"[+＋]", _bonus_text(translated_kr))
            _tk_gifts, _ = gift_indexes(translated_kr, strict=True)
            _tk_drop = set(_tk_gifts[-len(_dropped_gifts):])
            translated_for_tier = "+".join(
                s for i, s in enumerate(_tk_parts) if i not in _tk_drop).strip()

        is_set_tier = is_set_product(translated_for_tier, kr_name_display)

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
        # [v7.18.0] "무엇에서 무엇으로" 바뀌었는지 기록한다. 미리보기 문장
        # ("자동수정 미리보기: ...")만으로는 원래 값이 뭐였는지 안 보여서,
        # 실제로 얼마나 바뀐 건지 판단하려면 원문을 따로 찾아봐야 했다.
        change_notes: list[str] = []
        if not vol_match and qoo10_vol is not None and kr_vol is not None and brand_status != "mismatch":
            kr_vol_int = int(kr_vol) if kr_vol == int(kr_vol) else kr_vol
            _orig_m = re.search(r"\d+(?:\.\d+)?\s*(mL|ml|g|L)", q["title"])
            _orig_vol_str = _orig_m.group(0) if _orig_m else f"{qoo10_vol}"
            change_notes.append(f"용량 {_orig_vol_str} → {kr_vol_int}{_orig_m.group(1) if _orig_m else 'ml'}")
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
                change_notes.append(f"수량 1{explicit_match.group(1)} → {kr_qty}{explicit_match.group(1)}")
                qoo10_title_display = explicit_one_pattern.sub(
                    lambda m: f"{kr_qty}{m.group(1)}", qoo10_title_display, count=1)
                base_for_highlight = qoo10_title_highlighted or q["title"]
                qoo10_title_highlighted = explicit_one_pattern.sub(
                    lambda m: f'<mark class="vol-fix">{kr_qty}{m.group(1)}</mark>', base_for_highlight, count=1)
            else:
                change_notes.append(f"수량 표기없음 → {kr_qty}개")
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
                change_notes.append(f"수량 {qty_removed_original} → 표기 제거(단품)")
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
            change_notes.append(f"발송지 표기 '{removed_text}' → 삭제(한국에서 발송)")
            qoo10_title_display = shipping_removal_pattern.sub("", qoo10_title_display, count=1).strip()
            base_for_highlight = qoo10_title_highlighted or q["title"]
            qoo10_title_highlighted = shipping_removal_pattern.sub(
                lambda mm: f' <del class="vol-fix" style="color:#c0392b;">{mm.group(0).strip()}</del>', base_for_highlight, count=1)
            qty_auto_corrected = True

        # [v7.27.0] 큐텐 증정 초과분 삭제. 자동수정 체인의 **맨 마지막**에
        #  둔다 — 앞의 용량·수량 자동수정이 q["title"] 원문을 기준으로
        #  다시 쓰기 때문에, 먼저 지우면 그 결과가 덮여 사라진다.
        if _dropped_gifts:
            _base = qoo10_title_display
            for _seg in _dropped_gifts:
                _base = _remove_gift_segment(_base, _seg)
            change_notes.append(
                "큐텐 증정 " + " · ".join(_dropped_gifts)
                + " → 삭제(한국 구매처에 없음)")
            _hl = qoo10_title_highlighted or qoo10_title_display
            for _seg in _dropped_gifts:
                _hl = _hl.replace(
                    _seg, f'<del class="vol-fix" style="color:#c0392b;">{_seg}</del>', 1)
            qoo10_title_highlighted = _hl
            qoo10_title_display = _base
            qty_auto_corrected = True

        kr_candidates = x.get("image_candidates") or []
        if not kr_candidates and x.get("image_url"):
            kr_candidates = [{"url": x["image_url"], "mall": x.get("mall"), "link": x.get("product_url")}]

        pairs.append({
            "goods_no": x["goods_no"], "qoo10_title": qoo10_title_display, "qoo10_title_original": q["title"],
            "vol_auto_corrected": vol_auto_corrected, "qty_auto_corrected": qty_auto_corrected, "vol_status": vol_status, "qoo10_title_highlighted": qoo10_title_highlighted, "qoo10_brand": orig_brand,
            "change_notes": change_notes,
            "qoo10_image": q.get("image_url"), "qoo10_price_jpy": q.get("price_jpy"), "qoo10_url": to_pc_url(q.get("item_url")),
            "qoo10_name_kr": x.get("translated_kr") or translations.get(x["goods_no"], ""),
            "kr_brand": x.get("brand"), "kr_name": kr_name_display,
            "kr_volume": x.get("volume") or (f"{int(kr_vol)}ml" if kr_vol else ""),
            "kr_qty": kr_qty, "is_set": is_set, "kr_name_jp": kr_to_jp.get(x["goods_no"], ""),
            "kr_candidates": kr_candidates, "kr_price": x.get("price"), "kr_url": x.get("product_url"),
            # [v7.10.0] 로컬 수집으로 얻은 정가. 판매가와 다를 때만 들어 있다.
            #  네이버 검색 API 는 최저가만 주고 정가를 안 줘서 할인율을 알 수 없었다.
            "kr_list_price": x.get("list_price"),
            "kr_mall": x.get("mall"), "kr_seller_trust": x.get("seller_trust"),
            "kr_source": x.get("winner_source"), "vol_match": vol_match, "brand_status": brand_status, "qoo10_brand": orig_brand,
            "obsolete": x.get("obsolete"),
            "naver_rematched": x.get("naver_rematched"),
            "single_source_naver": x.get("single_source_naver"),
            # [v4.4.0] 매칭 신뢰도(0~4). 검수 순서를 이 값으로 정한다.
            "confidence": match_confidence(
                translated_kr, x.get("name") or "", brand_status,
                # 양쪽 다 용량을 알 때만 '불일치'로 본다(한쪽만 있으면 판단불가).
                volume_mismatch(qoo10_vol, kr_vol),
                bool(x.get("single_source_naver"))),
            "form_status": form_status(translated_kr, x.get("name") or ""),
            "color_status": color_status(translated_kr, x.get("name") or ""),
            # [v7.4.0] 검수 화면에 제형을 직접 보여준다. 등급만으로는 무엇이
            # 어긋났는지 알 수 없어, 사람이 다시 상품명을 읽어야 했다.
            # [v7.17.0] 번역본을 한국 표기로 고친 흔적. 무엇이 바뀌었는지
            #  안 보이면 잘못 고쳐도 알 수 없다.
            "term_fixed": x.get("term_fixed") or "",
            "qoo10_forms": sorted(extract_forms(translated_kr)),
            "kr_forms": sorted(extract_forms(x.get("name") or "")),
            "tier": confidence_tier(
                match_confidence(translated_kr, x.get("name") or "", brand_status,
                                 volume_mismatch(qoo10_vol, kr_vol),
                                 bool(x.get("single_source_naver"))),
                brand_status,
                volume_mismatch(qoo10_vol, kr_vol),
                bool(_sim_token(translated_kr, x.get("name") or "") >= 0.5
                     or _sim_bigram(translated_kr, x.get("name") or "") >= 0.6),
                bool(x.get("single_source_naver")),
                form_status(translated_kr, x.get("name") or ""),
                bool(_sim_token(translated_kr, x.get("name") or "") >= 0.8
                     or _sim_bigram(translated_kr, x.get("name") or "") >= 0.85),
                color_status(translated_kr, x.get("name") or ""),
                is_set_tier,
                ingredient_conflict(translated_kr, x.get("name") or ""),
                # [v7.25.0] 총 매수·개수 불일치 -> B. 용량과 마찬가지로
                #  검수 화면에 보이는 이름(kr_name_display)으로 판정한다.
                count_mismatch=counts_mismatch(
                    translated_for_tier, kr_name_display, is_set_tier)),
            "count_mismatch": counts_mismatch(
                translated_for_tier, kr_name_display, is_set_tier),
            # [v7.27.0] 지운 큐텐 증정. 검수 화면에서 확인할 수 있어야 한다.
            "dropped_gifts": _dropped_gifts,
        })

    print(f"[통계] 구매링크없음={stats['no_link']} 품절={stats['sold_out']} 단종={stats['obsolete']} "
          f"큐텐매칭안됨={stats['no_qoo10_match']} 선택형제외={stats['select_type']} 콜라보제외={stats['collab']} "
          f"브랜드+이름불일치제외={stats['brand_name_mismatch']} 수동제외={stats['manual']} "
          f"광고글제외={stats['article']} 해외브랜드제외={stats['foreign']} 일반명제외={stats['generic']} "
          f"제외카테고리={stats['excluded_category']} "
          f"최종={stats['ok']}건")
    pairs = _drop_search_blackholes(pairs, excluded_mismatch)
    if excluded_mismatch:
        print(f"[제외목록] output/brand_name_mismatch_excluded.json — {len(excluded_mismatch)}건 "
              "(자동 판정이 틀렸는지 확인 가능)")
        (OUTPUT / "brand_name_mismatch_excluded.json").write_text(
            json.dumps(excluded_mismatch, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "comparison_pairs.json").write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return pairs


# [v4.8.0] 검색 블랙홀 정리.
#  특정 한국 상품이 서로 다른 큐텐 상품 여러 건에 반복해서 붙는다.
#  실측(2,590건): 같은 구매링크가 22건·20건·16건에 붙은 사례가 있었고,
#  3건 이상에 붙은 링크가 전체의 14.2%(369건)를 차지했다.
#      프리티스킨 'PDRN TX1 콜라겐 캡슐 크림'   11건
#      게스통 '스킨부스터 이데베논 세럼 시트마스크' 16건
#  성분어(PDRN·시카·콜라겐 등)만 겹치면 검색이 이 인기 상품들로 수렴한다.
#
#  전부 지우지는 않는다 — 그중 하나는 진짜 짝일 수 있다. 이름이 가장
#  비슷한 한 건만 남기고 나머지를 뺀다.
BLACKHOLE_MIN = 3


def _drop_search_blackholes(pairs: list[dict], excluded: list[dict]) -> list[dict]:
    from collections import defaultdict
    # [v5.4.0] 링크뿐 아니라 '매칭된 상품명'으로도 묶는다. 같은 상품이
    # 판매처마다 다른 링크로 올라오면 링크 기준으로는 안 걸린다 —
    # 실측: '인진쑥 진정 보습 세럼'이 서로 다른 큐텐 상품 12건에,
    # '칠자화 유액'이 4건에 붙었는데 링크가 달라 통과했다.
    by_url: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        key = _flat(p.get("kr_name") or "") or (p.get("kr_url") or "")
        by_url[key].append(p)

    keep_ids = set()
    dropped = 0
    for url, group in by_url.items():
        # [v5.3.0] 2건짜리도 큐텐 브랜드가 서로 다르면 블랙홀로 본다.
        # 같은 링크에 2건이 붙는 건 큐텐에 같은 상품이 여러 셀러로 올라온
        # 정상 경우일 수 있어 임계를 3으로 뒀는데, 실측에서 브랜드가 다른
        # 2건짜리가 남았다(LOWVIBE 핸드크림 / Deep;erence 핸드크림 ->
        # 둘 다 '포트레 핸드크림 누보'). 브랜드가 다르면 같은 상품일 수 없다.
        distinct_brands = len({(p.get("qoo10_brand") or "").strip() for p in group})
        # [v6.3.0] 같은 브랜드 2건도, 큐텐 상품명까지 같으면 중복 등록이다.
        #  실측: 네이처리퍼블릭 '알로에 수딩젤 미스트 155ml×3'이 서로 다른
        #  goods_no로 두 번 올라와 같은 한국 상품에 붙었다. 큐텐에 같은
        #  상품을 여러 셀러가 올리는 건 정상이지만, 검수 화면에 같은 짝이
        #  두 번 나오면 사람이 두 번 판단하게 된다.
        distinct_qoo10 = len({_flat(p.get("qoo10_name") or "") for p in group})
        is_blackhole = (len(group) >= BLACKHOLE_MIN
                        or (len(group) >= 2 and distinct_brands >= 2)
                        or (len(group) >= 2 and distinct_qoo10 == 1))
        if not url or not is_blackhole:
            keep_ids.update(id(p) for p in group)
            continue
        best = max(group, key=lambda p: (_sim_token(p.get("qoo10_name") or "", p.get("kr_name") or ""),
                                         int(p.get("confidence", 0))))
        keep_ids.add(id(best))
        for p in group:
            if p is best:
                continue
            dropped += 1
            excluded.append({
                "goods_no": p.get("goods_no"), "qoo10": p.get("qoo10_name"),
                "matched": p.get("kr_name"), "url": url,
                "reason": f"검색 블랙홀: 같은 링크가 {len(group)}건에 중복 매칭",
            })
    if dropped:
        print(f"[블랙홀제외] 같은 링크에 {BLACKHOLE_MIN}건 이상 몰린 매칭 중 {dropped}건 제외"
              " (링크당 가장 잘 맞는 1건만 유지)")
    return [p for p in pairs if id(p) in keep_ids]


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
        # [v7.17.0] 번역본이 한국 표기로 교정됐으면 그 사실을 보여준다.
        fix_note = ""
        if p.get("term_fixed"):
            fix_note = (f'<span class="badge" style="background:#eef3fb;color:#3a5a8c;'
                        f'border:1px solid #b9cbe6;">표기 교정 {esc(p["term_fixed"])}</span>')
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
      <td class="label">제형</td>
      <td>{form_row} {fix_note}</td>
    </tr>
    <tr>
      <td class="label">상품명</td>
      <td>
        {('<div class="vol-fix-preview">' + p['qoo10_title_highlighted']
    + ('<div class="vol-fix-notes">' + ' · '.join(esc(n) for n in p.get('change_notes') or []) + '</div>'
       if p.get('change_notes') else '') + '</div>') if p.get('qoo10_title_highlighted') else ''}
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
