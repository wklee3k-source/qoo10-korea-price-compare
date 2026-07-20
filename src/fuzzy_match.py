"""
fuzzy_match.py

권고사항 #12: 다단계 점수 기반 퍼지매칭.

[배경] 지금까지는 검색 결과 후보 리스트의 0번째(candidates[0])를 그냥
"최유력 후보"로 취급했다. 하지만 다나와/무신사 검색결과 순서는 상품
일치도가 아니라 클릭/구매 데이터 기반일 때가 많아서, 0번째가 실제로는
다른 용량이나 세트구성인 경우가 꽤 있었다(예: 큐텐엔 단품인데 0번째
후보는 "2개세트"인 경우).

[점수 배점 — 외부 AI 리뷰 제안 그대로 적용]
    브랜드 일치     35%
    용량(ml/g) 일치  25%
    핵심 키워드 겹침  20%
    세트/개수 일치    10%  (원래 "모델명 일치"였는데 화장품 특성상
                         세트구성 여부가 더 중요해서 이걸로 대체)
    문자열 퍼지유사도 10%  (difflib.SequenceMatcher)

[전처리] 브랜드명 정규화, 용량(ml/g/L) 추출, 색상/프로모션 문구/괄호
제거를 먼저 수행한다 — 이걸 안 하면 점수 계산 자체가 부정확해진다.

사용법:
    python fuzzy_match.py
        (자체 테스트 케이스 실행)
"""

import re
from difflib import SequenceMatcher

# 큐텐 brand_name(영문/일본어)과 무신사 등 한국 사이트에 표시되는 한글
# 브랜드명이 문자열 자체가 달라서("COSRX" vs "코스알엑스") 단순 포함비교로는
# 매칭이 안 된다 — 지금까지 이 프로젝트에서 실제로 확인한 것만 우선 채워둠.
# (완전한 해결책은 아니고, brand_db.json이 커질수록 같이 넓혀야 하는 부분)
BRAND_KOREAN_NAME = {
    "cosrx": "코스알엑스",
    "growus": "그로우어스",
    "kahi": "가히",
    "tirtir": "티르티르",
    "innisfree": "이니스프리",
    "laneige": "라네즈",
    "banilaco": "바닐라코",
    "vt-cosmetics": "브이티코스메틱",
    "physiogel": "피지오겔",
    "dr20project": "닥터트웬티프로젝트",
    "somebymi": "썸바이미",
    "manyo": "마녀공장",
    "makeprem": "메이크프렘",
    "sister-ann": "씨스터앤",
    "hince": "힌스",
    "biodance": "바이오던스",
    "cellfusionc": "셀퓨전씨",
    "pibumi": "피부미",
    "frankly": "프랭클리",
    "aprilskin": "에이프릴스킨",
    "medicube": "메디큐브",
}

VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|g|G|L|개입|매|매입)")
BRACKET_RE = re.compile(r"[\[【][^\]】]*[\]】]")
SET_COUNT_RE = re.compile(r"(\d+)\s*(개|개입|세트|SET|set)")


def normalize_name(name: str) -> str:
    """비교 전에 잡음을 제거한다: 대괄호/【】 프로모션 문구, 여러 공백."""
    if not name:
        return ""
    name = BRACKET_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_volumes(name: str) -> set[str]:
    """'50ml', '150g' 같은 용량 토큰을 정규화해서 집합으로 뽑는다."""
    if not name:
        return set()
    return {f"{num}{unit.lower()}" for num, unit in VOLUME_RE.findall(name)}


def extract_set_count(name: str) -> int:
    """'2개', '2SET' 같은 세트 수량. 없으면 1(단품)로 취급."""
    if not name:
        return 1
    m = SET_COUNT_RE.search(name)
    return int(m.group(1)) if m else 1


def keyword_overlap_score(a: str, b: str) -> float:
    """공백 기준 토큰 겹침 비율(자카드 유사도 비슷하게)."""
    tokens_a = set(re.findall(r"[가-힣a-zA-Z0-9]+", a.lower()))
    tokens_b = set(re.findall(r"[가-힣a-zA-Z0-9]+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    inter = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(inter) / len(union) if union else 0.0


def score_candidate(qoo10_name: str, qoo10_brand: str, candidate_name: str, candidate_brand: str = "") -> dict:
    """외부 AI가 제안한 배점(브랜드35+용량25+키워드20+세트10+퍼지10)을 그대로 적용.
    candidate_brand: musinsa_finder.py가 카드 텍스트에서 별도로 뽑아낸 브랜드명
    (예: '코스알엑스'). 상품명 자체에는 브랜드가 안 들어있는 경우가 많아서
    이 필드가 있으면 훨씬 정확하다."""
    q_norm = normalize_name(qoo10_name)
    c_norm = normalize_name(candidate_name)

    # 브랜드 일치 (35%) — 후보의 별도 브랜드 필드 우선, 없으면 상품명 텍스트에서 탐색
    brand_score = 0.0
    if qoo10_brand:
        try:
            import brand_db
            canonical_key = brand_db.BRAND_NAME_ALIASES.get(qoo10_brand.strip())
        except Exception:  # noqa: BLE001
            canonical_key = None
        korean_name = BRAND_KOREAN_NAME.get(canonical_key, "") if canonical_key else ""

        brand_tokens = [t for t in re.findall(r"[가-힣a-zA-Z]+", qoo10_brand.lower()) if len(t) >= 2]
        if korean_name:
            brand_tokens.append(korean_name.lower())
        check_text = (candidate_brand or "").lower() + " " + c_norm.lower()
        if brand_tokens and any(t in check_text for t in brand_tokens):
            brand_score = 35.0

    # 용량 일치 (25%)
    q_vols = extract_volumes(q_norm)
    c_vols = extract_volumes(c_norm)
    volume_score = 0.0
    if q_vols and c_vols:
        volume_score = 25.0 if (q_vols & c_vols) else 0.0
    elif not q_vols and not c_vols:
        volume_score = 12.5  # 둘 다 용량 정보가 없으면 판단보류로 절반만

    # 핵심 키워드 겹침 (20%)
    keyword_score = keyword_overlap_score(q_norm, c_norm) * 20.0

    # 세트/개수 일치 (10%) — 큐텐이 단품인데 후보가 세트면 감점
    q_set = extract_set_count(q_norm)
    c_set = extract_set_count(c_norm)
    set_score = 10.0 if q_set == c_set else 0.0

    # 문자열 퍼지유사도 (10%)
    fuzzy_score = SequenceMatcher(None, q_norm, c_norm).ratio() * 10.0

    total = brand_score + volume_score + keyword_score + set_score + fuzzy_score
    return {
        "score": round(total, 1),
        "brand": round(brand_score, 1),
        "volume": round(volume_score, 1),
        "keyword": round(keyword_score, 1),
        "set": round(set_score, 1),
        "fuzzy": round(fuzzy_score, 1),
    }


def rank_candidates(qoo10_name: str, qoo10_brand: str, candidates: list[dict]) -> list[dict]:
    """candidates 리스트(각 dict에 'name' 키가 있어야 함)에 점수를 매겨서
    높은 순으로 정렬하고, 각 후보에 '_match' 필드로 점수 상세를 남긴다.
    이게 바로 외부 AI가 제안한 '검색 결과 품질 로그'다."""
    scored = []
    for c in candidates:
        detail = score_candidate(qoo10_name, qoo10_brand, c.get("name", ""), c.get("brand_from_container", ""))
        c = dict(c)
        c["_match"] = detail
        scored.append(c)
    scored.sort(key=lambda c: c["_match"]["score"], reverse=True)
    return scored


if __name__ == "__main__":
    # 자체 테스트: 큐텐 원본이 "단품 50ml"인데 후보에 "2개세트"와 "단품"이
    # 섞여있을 때, 단품이 더 높은 점수를 받아야 한다.
    qoo10_name = "COSRX 더 6 펩타이드 스킨 부스터 세럼 150mL"
    qoo10_brand = "COSRX"
    candidates = [
        {"name": "[SET] 더 6 펩타이드 스킨 부스터 세럼 150ml x 2개 + 펩타이드 겔 마스크 1매", "brand_from_container": "코스알엑스"},
        {"name": "더 6 펩타이드 스킨 부스터 세럼 150ml", "brand_from_container": "코스알엑스"},
        {"name": "이니스프리 그린티 미스트 150ml", "brand_from_container": "이니스프리"},  # 브랜드도 다르고 상품도 다름 — 최하위여야 함
    ]
    ranked = rank_candidates(qoo10_name, qoo10_brand, candidates)
    for r in ranked:
        print(f"{r['_match']['score']:5.1f}점 | {r['name'][:50]}")
        print(f"       세부: {r['_match']}")
