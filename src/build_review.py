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
    r"베스트\s*\d|TOP\s*\d|\d+\s*종\s*(인기|추천)|후기\s*모음|비교\s*정리|"
    r"이것만|알아보기|총정리|모집)"
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
    "A": ("완전 신뢰", "브랜드·이름 모두 확인됨"),
    "B": ("확인 필요", "브랜드나 이름 중 하나가 불확실함"),
    "C": ("불일치 의심", "다른 제품일 가능성이 큼 — 사진을 꼭 대조"),
}


def confidence_tier(confidence: int) -> str:
    if confidence >= 4:
        return "A"
    return "B" if confidence >= 2 else "C"


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
    # [v5.0.0] 한국 화장품이 아닌 브랜드는 애초에 검수 대상이 아니다.
    #  이 사업은 한국에서 사서 큐텐재팬에 파는 구조라, 일본·유럽 브랜드
    #  상품은 한국 매입가가 더 비싸거나 아예 유통되지 않는다. 그런데도
    #  발굴에 섞여 들어와 검증을 소모하고, 억지로 매칭되면 오매칭이 된다
    #  (실측: 花王 비오레 -> 지에프코스 선크림, ブルガリ 향수 -> 노에비아 크림).
    #  브랜드 목록으로 관리한다 — 자동 판별이 어렵다. 가타카나라고 해외가
    #  아니다(アヌア=아누아, メディキューブ=메디큐브는 한국 브랜드다).
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
             "select_type": 0, "collab": 0, "brand_name_mismatch": 0, "manual": 0, "article": 0, "foreign": 0, "generic": 0, "ok": 0}
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
        brand_status = check_brand(orig_brand, x.get("brand", ""), brand_dict, x.get("name") or "")
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
            "kr_source": x.get("winner_source"), "vol_match": vol_match, "brand_status": brand_status, "qoo10_brand": orig_brand,
            "obsolete": x.get("obsolete"),
            "naver_rematched": x.get("naver_rematched"),
            "single_source_naver": x.get("single_source_naver"),
            # [v4.4.0] 매칭 신뢰도(0~4). 검수 순서를 이 값으로 정한다.
            "confidence": match_confidence(
                translated_kr, x.get("name") or "", brand_status,
                # 양쪽 다 용량을 알 때만 '불일치'로 본다(한쪽만 있으면 판단불가).
                bool(qoo10_vol is not None and kr_vol is not None and not vol_match),
                bool(x.get("single_source_naver"))),
            "tier": confidence_tier(match_confidence(
                translated_kr, x.get("name") or "", brand_status,
                bool(qoo10_vol is not None and kr_vol is not None and not vol_match),
                bool(x.get("single_source_naver")))),
        })

    print(f"[통계] 구매링크없음={stats['no_link']} 품절={stats['sold_out']} 단종={stats['obsolete']} "
          f"큐텐매칭안됨={stats['no_qoo10_match']} 선택형제외={stats['select_type']} 콜라보제외={stats['collab']} "
          f"브랜드+이름불일치제외={stats['brand_name_mismatch']} 수동제외={stats['manual']} "
          f"광고글제외={stats['article']} 해외브랜드제외={stats['foreign']} 일반명제외={stats['generic']} "
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
        is_blackhole = len(group) >= BLACKHOLE_MIN or (len(group) >= 2 and distinct_brands >= 2)
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
