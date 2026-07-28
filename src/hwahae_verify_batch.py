"""
hwahae_verify_batch.py (v5 — API 호출 3회로 절감)

문제의식(사용자 지적): 이전 구조는 2차(Exa/화해/네이버 초기조회) 이후에
4차(화해 재확인)와 5차(네이버 구매정보)를 또 호출해서 상품 1건당 API를
최대 5번(Exa1+화해2+네이버2) 썼다. 화해와 네이버는 처음 조회할 때 이미
필요한 정보(단종여부/가격/사진/링크)를 전부 받아올 수 있으므로, 그걸 그대로
쓰면 재호출이 필요 없다.

새 구조(3회 호출):
    1차. 클로드 대충번역(입력 그대로)을
    2차. Exa / 화해 / 네이버 세 곳에 각각 1번씩만 검색 — 화해와 네이버는
         이 1번의 호출에서 단종여부/가격/사진/구매링크까지 전부 뽑아둔다.
    3차. known_brand/known_volume과의 일치도 + 소스간 합의(consensus)로
         점수를 매겨 가장 적합한 후보(확정 상품명+브랜드)를 선정하고,
         구매정보는 2차에서 이미 받아온 화해/네이버 데이터를 그대로 쓴다
         (재호출 없음).

GitHub Actions 백그라운드 실행을 염두에 두고 매 건마다 즉시 저장한다.

사용법:
    python hwahae_verify_batch.py <input.json> <output.json> [max_new]
"""

import os
import time
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

VOLUME_IN_QUERY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL|ml|g|L)\b")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")
EXA_TAIL_RE = re.compile(r"\s*[-|]\s*.+$")
EXA_REVIEW_RE = re.compile(r"\s*소비자평점.*$|\s*내돈내산.*$|\s*후기.*$")
PRODUCT_URL_PATTERNS = re.compile(
    r"goodsNo=|/goods/|/products?/|goodscode=|/vp/products/|/dp/|/item/|itemId="
)
GENERIC_TITLE_RE = re.compile(
    r"^\s*.{1,15}(공식\s*(홈페이지|스토어|사이트|쇼핑몰)?|브랜드관|메인|홈)\s*[|｜]?\s*.{0,10}$"
)
NEWS_DOMAIN_RE = re.compile(
    r"news\.|\.news|/news/|blog\.|\.blog|tistory\.com|brunch\.co\.kr|post\.naver|magazine|"
    r"donga\.com|chosun\.com|joongang|hani\.co\.kr|mk\.co\.kr|hankyung|edaily|yna\.co\.kr"
)
HEADLINE_SENTENCE_RE = re.compile(r"[다요]\s*,|[다요][!?]|하면|한다면")


# [v3.1.1] 소스가 "일시적으로 실패"한 게 아니라 "아예 못 쓰는 상태"인 경우가
# 있다. 실측 2026-07-28: Exa 크레딧이 소진돼 모든 호출이 HTTP 402(Payment
# Required)로 떨어졌는데, 이게 기술적실패로 분류돼 상품마다 3회씩 재시도된
# 뒤 '보류'로 쌓였다 — 검증이 통째로 멈춘 것과 같았다. 화해/네이버/무신사가
# 멀쩡하고 채택 기준도 2곳 합의라 Exa 없이도 검증은 정상 진행 가능하므로,
# 이런 오류는 그 소스만 꺼버리고 나머지로 계속 간다.
PERMANENT_FAILURE_PATTERNS = (
    "402",              # Payment Required — 크레딧 소진
    "Payment Required",
    "401",              # Unauthorized — 키 만료/오타
    "Unauthorized",
    "403",              # Forbidden — 권한 없음
)
DISABLED_SOURCES: set[str] = set()


def _is_permanent_failure(message: str) -> bool:
    return any(pat in message for pat in PERMANENT_FAILURE_PATTERNS)


class SearchTechnicalFailure(Exception):
    """[9번 수정과 동일 원칙] 검색 자체가 기술적으로 실패한 경우(타임아웃,
    네트워크 오류, 서브프로세스 비정상종료, JSON 파싱실패 등)에만
    발생시킨다. '정상적으로 조회했는데 결과가 없음'(진짜 무매칭)과는
    반드시 구분해야 한다 — 예전엔 둘 다 그냥 None을 반환해서, 화해 서버가
    30초 안에 안 열리거나 네트워크가 잠깐 끊겨도 '이 상품은 한국에
    없다'고 영구 확정해버렸다. 실제로 찾을 수 있었던 상품이 일시적
    오류 때문에 영영 실패로 묻히는 사고였다."""


def _clean_query(text: str) -> str:
    t = VOLUME_IN_QUERY_RE.sub("", text)
    t = BRACKET_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize_volume_ml(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"([\d.]+)\s*(mL|ml|g|L)", text)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2).lower()
    return num * 1000 if unit == "l" else num


def _search_exa(keyword: str) -> dict | None:
    """후보1: Exa 의미기반검색(원본 번역 그대로 검색).

    [실패구분] import/네트워크/파싱 오류는 SearchTechnicalFailure로
    올리고, '검색은 됐는데 결과가 0건'만 None(진짜 무결과)으로 본다."""
    try:
        from exa_search import search as exa_search
    except Exception as e:  # noqa: BLE001
        raise SearchTechnicalFailure(f"exa_search 임포트 실패: {e}") from e

    try:
        items = exa_search(keyword, num_results=5)
    except Exception as e:  # noqa: BLE001
        raise SearchTechnicalFailure(f"Exa 호출 실패: {type(e).__name__}: {e}") from e

    if not items:
        return None  # 진짜 무결과 — 기술적 실패 아님

    def _is_bad(it: dict) -> bool:
        url = it.get("url") or ""
        title = it["title"]
        return bool(
            GENERIC_TITLE_RE.match(title) or NEWS_DOMAIN_RE.search(url) or HEADLINE_SENTENCE_RE.search(title)
        )

    candidates = [it for it in items if PRODUCT_URL_PATTERNS.search(it.get("url") or "") and not _is_bad(it)]
    if not candidates:
        candidates = [it for it in items if not _is_bad(it)]
    if not candidates:
        candidates = items
    title = candidates[0]["title"]
    cleaned = EXA_REVIEW_RE.sub("", title)
    cleaned = EXA_TAIL_RE.sub("", cleaned)
    cleaned = _clean_query(cleaned)
    return {"source": "exa", "name": cleaned, "brand": None, "volume": None, "raw_title": title}


def _search_hwahae(keyword: str, known_volume: str, known_brand: str) -> dict | None:
    """후보2: 화해 검색(원본 번역 그대로, 격리된 서브프로세스). 나중에
    재확인 호출을 안 해도 되도록, 필요한 정보(단종여부/가격/사진/링크)를
    이 1번의 호출에서 전부 뽑아둔다.

    [실패구분] 서브프로세스 타임아웃/비정상종료/JSON파싱실패는
    SearchTechnicalFailure로 올린다. 정상 실행됐는데 화해가 못 찾은
    경우("corrected" 없음)만 None(진짜 무결과)으로 본다."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "hwahae_name_corrector.py"), keyword, known_volume, known_brand],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise SearchTechnicalFailure(f"화해 서브프로세스 타임아웃(30초)") from e

    if proc.returncode != 0:
        raise SearchTechnicalFailure(f"화해 서브프로세스 비정상종료(code={proc.returncode}): {proc.stderr[-300:]}")

    try:
        r = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise SearchTechnicalFailure(f"화해 결과 파싱 실패: {proc.stdout[-300:]}") from e

    if not r.get("corrected"):
        return None  # 정상 실행됐지만 화해가 못 찾음 — 진짜 무결과

    return {
        "source": "hwahae",
        "name": r.get("corrected"),
        "brand": r.get("brand"),
        "volume": r.get("volume"),
        "obsolete": r.get("obsolete"),
        "sale": r.get("sale"),
        "price": r.get("price"),
        "image_url": r.get("image_url"),
        "product_url": r.get("product_url"),
    }


def _search_musinsa(keyword: str, known_volume: str, known_brand: str) -> dict | None:
    """후보4: 무신사 검색(격리된 서브프로세스) — 화해와 같은 역할(브랜드/
    상품명 확인)을 하면서, 자체적으로 구매 가능한 쇼핑몰이라 실제 구매링크도
    바로 제공한다(goods_no로 상품페이지 URL 구성).

    [실패구분] 화해와 동일 원칙 — 서브프로세스 기술적 실패는
    SearchTechnicalFailure, 정상실행+무매칭만 None."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "musinsa_name_corrector.py"), keyword, known_volume, known_brand],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise SearchTechnicalFailure("무신사 서브프로세스 타임아웃(30초)") from e

    if proc.returncode != 0:
        raise SearchTechnicalFailure(f"무신사 서브프로세스 비정상종료(code={proc.returncode}): {proc.stderr[-300:]}")

    try:
        r = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise SearchTechnicalFailure(f"무신사 결과 파싱 실패: {proc.stdout[-300:]}") from e

    if not r.get("corrected"):
        return None  # 정상 실행됐지만 무신사가 못 찾음 — 진짜 무결과

    top = (r.get("all_candidates") or [{}])[0]
    goods_no = top.get("goods_no")
    return {
        "source": "musinsa",
        "name": r.get("corrected"),
        "brand": r.get("brand"),
        "volume": None,
        "price": top.get("price"),
        "product_url": f"https://www.musinsa.com/products/{goods_no}" if goods_no else None,
        "image": None,
        "mallName": "무신사",
    }


def _extract_quantity(text: str) -> int:
    """제목/상품명에서 실제 구매수량(묶음개수)을 추출한다.
    - "1+1", "2+1" 같은 증정/묶음 표기 → 앞뒤 숫자 합
    - "2個", "2개", "2입", "2병", "SET", "세트" → 배수로 판단
    - "2種から1つ選択"(2종류 중 1개 선택) → 실제로는 1개이므로 수량에 안 잡히게 예외처리
    - [중요] "매/枚"(마스크팩/패치/시트 등)는 일부러 제외한다 — 이건 대부분
      "그 상품 1세트 안에 몇 장이 들었는지"(상품 구성정보)를 나타내지
      "몇 개를 살지"(구매수량)가 아니다. 예: "PDRN 마스크 10매"는 1개
      상품(마스크팩 1박스)인데 안에 10장이 든 것 — 이걸 수량10으로 잘못
      해석하면 정상 매칭도 전부 "수량불일치"로 오판하게 된다(실측으로
      확인된 버그: 이 버그 하나로 실패건의 상당수가 잘못 걸러지고 있었음).
    - 아무 표기도 없으면 1개로 간주"""
    if not text:
        return 1
    # "N種類から1つ選択" 류는 실제 수량이 1개이므로 먼저 제거하고 판단
    text_wo_choice = re.sub(r"\d+種(類)?から\d+つ選択", "", text)
    m = re.search(r"(\d+)\s*\+\s*(\d+)", text_wo_choice)  # "1+1" 등
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"(\d+)\s*(個|개|입|병|本)\b", text_wo_choice)
    if m:
        return int(m.group(1))
    if re.search(r"세트|SET|Set", text_wo_choice):
        return 2  # 세트는 최소 2개 이상으로 간주(정확한 숫자 불명이면 보수적으로)
    return 1


def _search_naver(keyword: str, known_brand: str) -> dict | None:
    """후보3: 네이버쇼핑 검색(원본 번역 그대로). 나중에 별도 "구매정보"
    재호출을 안 해도 되도록, 이 1번의 호출에서 가격/링크/사진후보까지
    전부 뽑아둔다.

    [실패구분] import/네트워크 오류는 SearchTechnicalFailure, 정상
    조회+결과0건만 None(진짜 무결과)."""
    try:
        from naver_shop_search import search as naver_search
    except Exception as e:  # noqa: BLE001
        raise SearchTechnicalFailure(f"naver_shop_search 임포트 실패: {e}") from e

    try:
        items = naver_search(keyword, display=5, known_brand=known_brand)
    except Exception as e:  # noqa: BLE001
        raise SearchTechnicalFailure(f"네이버 호출 실패: {type(e).__name__}: {e}") from e

    if not items:
        return None  # 진짜 무결과

    top = items[0]
    seen = set()
    image_candidates = []
    for it in items:
        img = it.get("image")
        if img and img not in seen:
            seen.add(img)
            image_candidates.append({"url": img, "mall": it.get("mallName"), "link": it.get("link")})
    return {
        "source": "naver",
        "name": top["title"],
        "brand": top.get("brand"),
        "volume": None,
        "price": top.get("lprice"),
        "mall": top.get("mallName"),
        "seller_trust": top.get("seller_trust"),
        "product_url": top.get("link"),
        "image_url": top.get("image"),
        "image_candidates": image_candidates,
    }


# 브랜드/카테고리성 흔한 화장품 용어 — 이런 단어들은 원본과 후보 둘 다에
# 당연히 나타나므로, "겹치는지"로 진짜 제품 식별에 못 쓴다. 이 목록에
# 없는 토큰이 원본에는 있는데 후보엔 전혀 없으면, 그건 다른 제품라인일
# 가능성이 높다(실측 사례: "레티젝션"(원본에만 있음) vs "슈퍼바운스"로
# 매칭됨 — 둘 다 "아이오페 레티놀 세럼"이라 브랜드체크로는 못 걸러짐).
_COMMON_COSMETICS_WORDS = {
    "레티놀", "세럼", "크림", "로션", "토너", "앰플", "마스크", "클렌징", "선크림",
    "에센스", "미스트", "오일", "젤", "패치", "패드", "폼", "밤", "스킨", "썬크림",
    "아이크림", "립밤", "선스틱", "샴푸", "트리트먼트", "정품", "공식", "단독",
    "기획", "세트", "리필", "본품", "증정", "사은품",
}

# [카테고리체크] 서로 명백히 다른 제품유형(예: 로션 vs 마스크팩)이면, 같은
# 제품라인명을 공유해도 다른 상품이다(실측 사례: "블루빈 B5-PDRN 마일드
# 로션"(원본) vs 후보명에 "마스크"가 섞여있어 혼란을 준 경우). 그룹 안의
# 단어는 서로 호환(같은 카테고리)으로 보고, 그룹이 다르면 별개 제품으로
# 취급한다.
_PRODUCT_CATEGORY_GROUPS = [
    {"로션", "에멀전", "유액"},
    {"마스크", "마스크팩", "시트마스크"},
    {"크림"},
    {"세럼", "앰플", "에센스"},
    {"토너", "스킨"},
    {"클렌징", "클렌저", "클렌징폼", "폼클렌징"},
    {"선크림", "썬크림", "선쿠션", "선스틱", "선세럼"},
    {"패치", "패드"},
    {"샴푸"},
    {"트리트먼트", "헤어팩"},
]


def _detect_categories(text: str) -> set[str]:
    found = set()
    for group in _PRODUCT_CATEGORY_GROUPS:
        if any(word in text for word in group):
            found.add(frozenset(group))
    return found


def _score_candidate(cand: dict, known_brand: str, known_volume: str, others: list[dict], original_query: str = "") -> float:
    """known_brand/known_volume 일치도 + 다른 소스와의 합의(consensus)로 점수를 매긴다."""
    score = 0.0
    cand_brand = (cand.get("brand") or "").lower()
    cand_name = (cand.get("name") or "").lower()

    if known_brand:
        kb = known_brand.lower()
        if kb in cand_brand or kb in cand_name:
            score += 3.0
        elif cand_brand:
            # [중요] 예전엔 known_brand가 있어도 불일치시 그냥 가산점만
            # 못 받았지 페널티가 없었다 — 그래서 후보가 이거 하나뿐이면
            # (다른 소스가 다 실패) 브랜드가 완전히 달라도 무조건 채택되는
            # 구조적 결함이 있었다(실측: "디오프러스" 원본이 "아이스트"라는
            # 완전히 다른 브랜드의 대형세트상품과 매칭된 사고). 후보 자체의
            # brand가 확인됐는데 known_brand와 다르면 강한 페널티를 준다.
            score -= 5.0

    if known_volume:
        known_ml = _normalize_volume_ml(known_volume)
        cand_ml = _normalize_volume_ml(cand.get("volume") or cand_name)
        if known_ml is not None and cand_ml is not None and abs(known_ml - cand_ml) < 0.1:
            score += 2.0

    # 합의 보너스: 다른 소스가 비슷한 상품명을 냈으면(단어 겹침) 신뢰도 상승
    cand_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", cand_name))
    for other in others:
        other_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", (other.get("name") or "").lower()))
        overlap = len(cand_tokens & other_tokens)
        if overlap >= 2:
            score += 1.0

    # [중요] 브랜드는 맞아도 구체적 제품라인이 다른 경우를 걸러낸다. 원본
    # 검색어에서 흔한 화장품 용어(레티놀/세럼/크림 등)를 뺀 "특이 토큰"이
    # 후보 이름에 전혀 없으면, 같은 브랜드의 다른 제품일 가능성이 높다
    # (실측 사례: 원본 "레티놀 레티젝션 세럼"인데 후보가 "레티놀 슈퍼
    # 바운스 세럼"으로 매칭됨 — 둘 다 아이오페 레티놀세럼이라 브랜드체크
    # 만으로는 못 걸러졌었다).
    if original_query:
        orig_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]{2,}", original_query.lower()))
        distinctive_orig = orig_tokens - _COMMON_COSMETICS_WORDS - {known_brand.lower()} if known_brand else orig_tokens - _COMMON_COSMETICS_WORDS
        # 숫자+단위(30ml, 1개 등)도 특이토큰 판정에서 제외
        distinctive_orig = {t for t in distinctive_orig if not re.match(r"^\d+", t)}
        # [주의] 완전히 똑같은 문자열만 "겹침"으로 치면, 번역표기 차이
        # 수준의 미세한 오차(예: "레티젝션" vs "레티제션", 한 글자만 다름)
        # 도 서로 다른 제품으로 오판해서, 정상적으로 맞는 매칭에까지 잘못
        # 페널티를 줄 위험이 있다(실측으로 확인됨). 편집거리 기반 유사도로
        # 완화해서, 꽤 비슷한 단어면 "겹침"으로 인정한다.
        def _similar_to_any(token, candidates):
            for c in candidates:
                if token in c or c in token:
                    return True
                if difflib.SequenceMatcher(None, token, c).ratio() >= 0.75:
                    return True
            return False

        truly_missing = {t for t in distinctive_orig if not _similar_to_any(t, cand_tokens)}
        if distinctive_orig and truly_missing == distinctive_orig:
            score -= 6.0

        # [카테고리체크] 원본과 후보 둘 다 카테고리가 명확히 판별되는데
        # 서로 다르면(예: 원본=로션, 후보=마스크) 강한 페널티. 카테고리가
        # 판별 안 되는 쪽이 있으면(애매하면) 그냥 넘어간다 — 확실할 때만
        # 걸러야 오탐이 없다.
        orig_categories = _detect_categories(original_query.lower())
        cand_categories = _detect_categories(cand_name)
        if orig_categories and cand_categories and not (orig_categories & cand_categories):
            score -= 6.0

    # 화해 출처는 단종여부까지 알려주는 부가정보가 있어 약간의 기본 가중치를 준다
    if cand.get("source") == "hwahae":
        score += 0.5

    return score


REJECT_SCORE_THRESHOLD = -2.0  # 이 밑으로 떨어지면 "틀린 매칭을 억지로 채택"보다 아예 실패 처리가 낫다
# [품질 강화] 서로 독립된 소스 몇 곳 이상이 찾아내야 채택할지. 1이면
# 예전처럼 한 곳만 찾아도 통과(오매칭 위험), 2면 두 곳 이상이 같은
# 상품을 찾았을 때만 채택한다. 환경변수로 조절 가능.
MIN_CONSENSUS_SOURCES = int(os.environ.get("MIN_CONSENSUS_SOURCES", "2"))


REQUEST_DELAY = float(os.environ.get("VERIFY_REQUEST_DELAY", "1.0"))


def _safe_search(fn, *args, failures: list, label: str, **kwargs):
    """4개 검색함수를 감싸서, SearchTechnicalFailure가 나면 failures
    리스트에 기록하고 None을 돌려준다 — 호출부의 'if not cand_X: ...'
    로직은 그대로 두면서, 이게 '진짜 무결과'인지 '기술적 실패'인지를
    별도로 추적할 수 있게 한다.

    [지연 추가] 예전엔 상품 하나당 4곳(Exa/화해/무신사/네이버)을 지연
    없이 연달아 때렸다. 워커 1개일 땐 티가 안 났지만, 병렬 워커를 여러
    개 띄우면 그 패턴이 워커 수만큼 겹쳐서 대상 사이트에 부담이 된다.
    특히 화해/무신사는 공식 API가 아니라 브라우저 스크래핑이라 더
    조심해야 한다. 매 요청 뒤 REQUEST_DELAY초 쉰다(기본 1초, 환경변수로
    조절 가능)."""
    # [v3.1.1] 이미 꺼진 소스는 호출조차 하지 않는다(지연시간도 아낀다).
    if label in DISABLED_SOURCES:
        return None
    try:
        return fn(*args, **kwargs)
    except SearchTechnicalFailure as e:
        msg = str(e)
        if _is_permanent_failure(msg):
            # 결제/인증 문제는 몇 번을 재시도해도 그대로다. 이 소스만 끄고
            # 나머지 소스로 계속 간다 — failures에 넣지 않으므로 상품이
            # '보류'로 쌓이지 않는다.
            DISABLED_SOURCES.add(label)
            print(f"    [{label}-영구장애] {msg} — 이번 실행에서 {label}를 끄고 나머지 소스로 진행",
                  file=sys.stderr)
            return None
        print(f"    [{label}-기술적실패-재시도대상] {msg}", file=sys.stderr)
        failures.append(label)
        return None
    finally:
        if REQUEST_DELAY > 0 and label not in DISABLED_SOURCES:
            time.sleep(REQUEST_DELAY)


def run_batch(input_path: str, output_path: str, max_new: int | None = None):
    items = json.loads(Path(input_path).read_text(encoding="utf-8"))

    out_path = Path(output_path)
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {r["goods_no"] for r in results}

    # [재시도 추적] 기술적 실패로 확정을 보류한 상품의 시도횟수를 별도
    # 파일에 저장한다(results는 '완료'만 담는 리스트라 재시도 대기건을
    # 넣을 자리가 없다). MAX_VERIFY_RETRIES에 도달하면 그때 포기하고
    # results에 실패로 기록한다(과거 실패 패턴과 동일한 상한 원칙).
    retry_state_path = out_path.with_name(out_path.stem + ".retry_state.json")
    retry_counts = json.loads(retry_state_path.read_text(encoding="utf-8")) if retry_state_path.exists() else {}
    MAX_VERIFY_RETRIES = 3

    print(f"[INFO] 전체 {len(items)}건 중 이미 처리된 {len(done)}건부터 이어서 진행 (재시도대기 {len(retry_counts)}건)")

    processed_this_call = 0
    for item in items:
        if item["goods_no"] in done:
            continue
        if max_new is not None and processed_this_call >= max_new:
            print(f"[STOP] 이번 호출分({max_new}건) 처리 완료 — 나머지는 다음 호출에서 이어서")
            break

        kw_raw = item["translated_kr"]
        known_volume = item.get("volume", "")
        known_brand = item.get("known_brand", "")
        kw_cleaned = _clean_query(kw_raw)

        print(f"[상품] {item['goods_no']}: {kw_raw}")
        tech_failures: list[str] = []  # 이번 상품 처리중 기술적으로 실패한 소스 이름들

        # 2차: 각 소스에 독립 검색(순차 호출이지만 서로 결과에 의존하지 않음 = 병렬 개념)
        #
        # [v3.2.0 — Exa를 '보조 호출'로 전환] Exa는 무료 월 크레딧($10 =
        # 약 1,428건)이 정해져 있어서, 상품마다 무조건 부르면 한 달 물량을
        # 며칠 만에 소진한다(실측 2026-07-28: 1,507건 검증하고 402로 정지).
        # 무료 3곳(화해/무신사/네이버)을 먼저 돌리고, 이미 채택 조건을
        # 만족했으면 Exa는 부르지 않는다.
        cand_hwahae = _safe_search(_search_hwahae, kw_cleaned, known_volume, known_brand, failures=tech_failures, label="화해")
        cand_musinsa = _safe_search(_search_musinsa, kw_cleaned, known_volume, known_brand, failures=tech_failures, label="무신사")
        cand_naver = _safe_search(_search_naver, kw_cleaned, known_brand, failures=tech_failures, label="네이버")

        # [Exa를 부르는 조건]
        #  ① 무료 3곳이 합의 정족수(MIN_CONSENSUS_SOURCES)를 못 채웠거나,
        #  ② 화해를 못 찾았을 때. 화해가 없으면 브랜드정보가 통째로 빠지는데,
        #     바로 아래 '[근본수정]' 블록이 Exa가 찾아준 정확한 이름으로 화해를
        #     재검색해서 그걸 되살리는 유일한 경로다.
        # 실측 1,507건 기준 21.6%에서 Exa 호출이 생략된다.
        _free_sources = {c["source"] for c in (cand_hwahae, cand_musinsa, cand_naver) if c}
        if len(_free_sources) >= MIN_CONSENSUS_SOURCES and cand_hwahae:
            cand_exa = None
            print(f"    [Exa생략] 무료 {len(_free_sources)}곳이 이미 합의 — Exa 크레딧 절약")
        else:
            cand_exa = _safe_search(_search_exa, kw_raw, failures=tech_failures, label="Exa")

        # [근본수정] Exa는 상품명은 정확히 찾아줘도 브랜드정보를 절대 안 준다
        # (구조적 한계). 화해 초벌검색(kw_cleaned)이 실패해서 cand_hwahae가
        # 없는데 Exa는 성공했다면, Exa가 찾은 정확한 이름으로 화해를 한 번 더
        # 검색한다 — 그래야 Exa가 이겨도 브랜드정보를 확보할 기회가 생긴다.
        # 실측: 같은 상품인데 검색어가 조금만 달라도 화해 1차검색이 실패하는
        # 경우가 있었고, 그때 브랜드정보가 통째로 빠지면서 정상 매칭도
        # "브랜드판단불가/불일치"로 잘못 보이는 문제가 있었다.
        if not cand_hwahae and cand_exa and cand_exa.get("name"):
            print(f"    [Exa이름으로 화해 재검색] '{kw_cleaned}' 화해검색 실패 -> Exa확인명 '{cand_exa['name']}'로 재검색")
            cand_hwahae_retry = _safe_search(_search_hwahae, cand_exa["name"], known_volume, known_brand, failures=tech_failures, label="화해재검색")
            if cand_hwahae_retry:
                cand_hwahae = cand_hwahae_retry

        # [개선] 초벌번역어(kw_cleaned)로 네이버검색이 실패했는데, 화해 또는
        # 무신사가 정확한 브랜드+상품명을 확인해줬다면, 그 정확한 이름으로
        # 네이버를 한 번 더 검색한다(구매링크는 네이버쪽이 더 신뢰판매처
        # 등급판정을 정교하게 하므로 우선한다). 초벌번역이 부정확해서
        # 네이버에서 못 찾는 케이스가 상당수 있었다(실측: 화해만 찾고
        # 네이버 구매링크 없는 실패가 528건).
        if not cand_naver:
            for helper in (cand_hwahae, cand_musinsa):
                if helper and helper.get("name"):
                    retry_query = f"{helper.get('brand') or ''} {helper['name']}".strip()
                    print(f"    [{helper['source']}이름 재검색] '{kw_cleaned}' 실패 -> 확인명 '{retry_query}'로 재검색")
                    cand_naver_retry = _safe_search(_search_naver, retry_query, known_brand, failures=tech_failures, label="네이버재검색")
                    if cand_naver_retry:
                        cand_naver = cand_naver_retry
                        break

        # 수량(묶음개수) 일치 확인: 큐텐 원본과 네이버 결과의 수량이 다르면
        # "1개" 기준으로 다시 찾는다(추가 검색 1회, 수량 불일치일 때만 발생).
        # 재검색해도 여전히 안 맞으면(검색어에 "1개"를 붙인다고 결과가 항상
        # 바뀌는 건 아님) 차라리 그 네이버 후보를 버린다 — 틀린 수량으로
        # 잘못 매칭하는 것보다 안전하다.
        if cand_naver:
            qoo10_qty = _extract_quantity(kw_raw)
            naver_qty = _extract_quantity(cand_naver.get("name") or "")
            if qoo10_qty != naver_qty:
                print(f"    [수량불일치] 큐텐={qoo10_qty}개 vs 네이버={naver_qty}개 -> 1개 기준으로 재검색")
                requery = f"{known_brand or cand_hwahae and cand_hwahae.get('brand') or ''} {kw_cleaned} 1개".strip()
                cand_naver_retry = _safe_search(_search_naver, requery, known_brand, failures=tech_failures, label="네이버수량재검색")
                if cand_naver_retry and _extract_quantity(cand_naver_retry.get("name") or "") == qoo10_qty:
                    cand_naver = cand_naver_retry
                else:
                    print(f"    [수량불일치] 재검색해도 안 맞음 -> 네이버 후보 폐기(잘못된 수량 매칭 방지)")
                    cand_naver = None

        candidates = [c for c in [cand_exa, cand_hwahae, cand_musinsa, cand_naver] if c]

        if not candidates:
            if tech_failures:
                # [9번 수정과 동일 원칙] 4곳 다 못 찾았어도, 그중 일부가
                # 기술적으로 실패한 거라면 아직 '진짜 무결과'라고 확정할
                # 수 없다. results/done에 안 넣고 보류해서 다음 실행에
                # 다시 시도한다. MAX_VERIFY_RETRIES에 도달하면 그때 포기.
                n = retry_counts.get(item["goods_no"], 0) + 1
                if n < MAX_VERIFY_RETRIES:
                    retry_counts[item["goods_no"]] = n
                    retry_state_path.write_text(json.dumps(retry_counts, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"    [보류-재시도대상] 기술적실패({','.join(tech_failures)})로 인해 확정 보류 ({n}/{MAX_VERIFY_RETRIES}회)")
                    # [설계허점 수정 - 재확인중 발견] 이 continue가 processed_
                    # this_call을 안 늘리면, CHUNK(max_new) 상한이 무력화된다
                    # — 기술적실패가 대량으로 겹치는 상황(예: Exa/네이버가
                    # 동시에 다운)에서는 이 for문이 max_new를 넘어 items
                    # 전체를 한 호출 안에서 다 훑어버릴 수 있다(각 상품마다
                    # 실제 API 호출 4번씩 하면서). '완료'는 아니어도 '이번
                    # 호출에서 실제로 API를 썼다'는 사실은 똑같으므로,
                    # processed_this_call을 여기서도 늘려서 CHUNK 상한이
                    # 실제 API 소비량을 제대로 제한하게 한다.
                    processed_this_call += 1
                    continue
                print(f"    [포기] {MAX_VERIFY_RETRIES}회 연속 기술적실패 — 실패로 확정 처리")
                retry_counts.pop(item["goods_no"], None)
            else:
                print("    [전체실패] 4곳 다 정상조회했지만 못 찾음(진짜 무결과)")
                retry_counts.pop(item["goods_no"], None)

            entry = {
                "goods_no": item["goods_no"], "translated_kr": kw_raw, "winner_source": None,
                "brand": None, "name": None, "volume": "", "source": None, "obsolete": None,
                "sale": None, "price": None, "mall": None, "seller_trust": None,
                "product_url": None, "image_url": None, "image_candidates": [],
            }
            results.append(entry)
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            retry_state_path.write_text(json.dumps(retry_counts, ensure_ascii=False, indent=2), encoding="utf-8")
            processed_this_call += 1
            continue

        # 3차: 점수화해서 최적 후보 선정
        scored = []
        for c in candidates:
            others = [o for o in candidates if o is not c]
            s = _score_candidate(c, known_brand, known_volume, others, kw_cleaned)
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        best_score, winner = scored[0]
        print(f"    [투표결과] " + " / ".join(f"{c['source']}={s:.1f}" for s, c in scored) + f" -> 승자: {winner['source']}")

        # [품질 강화 - 2곳 이상 합의 요건] 예전엔 4곳 중 한 곳만 찾아도
        # 통과시켰다. 그러면 그 한 곳이 엉뚱한 상품을 물어와도 검증할
        # 방법이 없다(실측: 화해가 'ph6.9 위치하젤 클렌저'를 찾았는데
        # 네이버는 전혀 다른 '뉴트로지나 리무버'를 가져온 사례).
        # 서로 독립된 소스 2곳 이상이 같은 상품을 찾아냈을 때만 채택하면
        # 오매칭이 크게 준다 — 물량은 줄지만 '양보다 질' 방침에 맞다.
        # (실측: 실제 검증분 442건 중 2곳 이상 합의는 310건 = 70.1%)
        n_sources = len({c["source"] for c in candidates})
        if n_sources < MIN_CONSENSUS_SOURCES:
            print(f"    [거부-합의부족] {n_sources}곳만 찾음(최소 {MIN_CONSENSUS_SOURCES}곳 필요) — 오매칭 방지를 위해 채택하지 않음")
            entry = {
                "goods_no": item["goods_no"], "translated_kr": kw_raw, "winner_source": None,
                "candidates_summary": {c["source"]: c.get("name") for c in candidates},
                "reject_reason": f"합의부족({n_sources}곳)",
                "brand": None, "name": None, "volume": "", "source": None,
                "obsolete": None, "sale": None, "price": None, "mall": None, "seller_trust": None,
                "product_url": None, "image_url": None, "image_candidates": [],
            }
            results.append(entry)
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            if retry_counts.pop(item["goods_no"], None) is not None:
                retry_state_path.write_text(json.dumps(retry_counts, ensure_ascii=False, indent=2), encoding="utf-8")
            processed_this_call += 1
            continue

        if best_score < REJECT_SCORE_THRESHOLD:
            print(f"    [거부] 최고점수({best_score:.1f})가 임계값({REJECT_SCORE_THRESHOLD}) 미만 — 틀린 매칭을 억지로 채택하지 않고 실패 처리")
            entry = {
                "goods_no": item["goods_no"], "translated_kr": kw_raw, "winner_source": None,
                "candidates_summary": {c["source"]: c.get("name") for c in candidates},
                "brand": None, "name": None, "volume": "", "source": None,
                "obsolete": None, "sale": None, "price": None, "mall": None, "seller_trust": None,
                "product_url": None, "image_url": None, "image_candidates": [],
            }
            results.append(entry)
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            processed_this_call += 1
            continue

        winner_name = winner.get("name") or ""
        winner_brand = winner.get("brand") or ""

        # (4차/5차 재확인 호출 제거 — 2차에서 이미 화해/네이버를 각각 1번씩
        # 호출하면서 필요한 정보를 전부 뽑아뒀으므로, 그 결과를 그대로 쓴다.
        # API 호출 수: Exa(1) + 화해(1) + 네이버(1) = 3회로 절감.)
        hwahae_data = cand_hwahae or {}
        naver_data = cand_naver or {}

        musinsa_data = cand_musinsa or {}

        entry_brand = winner_brand or hwahae_data.get("brand") or naver_data.get("brand") or musinsa_data.get("brand")

        # [일반화] 승자가 누구든(exa, naver, musinsa 등) 최종 브랜드정보가
        # 여전히 비어있으면, 승자가 확인해준 정확한 이름으로 화해를 마지막
        # 으로 한 번 더 검색해본다. 화해가 정말 그 상품을 모르면 그래도
        # 실패하지만, 초벌검색(kw_cleaned)만으로는 화해가 못 찾았어도
        # 승자의 정확한 이름으로는 찾아지는 경우가 실측으로 다수 확인됐다
        # (winner=exa 15건 + winner=naver 12건, 전체 662건 성공 중 27건이
        # 이 문제로 브랜드정보 없이 나가고 있었다).
        if not entry_brand and winner_name and winner["source"] != "hwahae":
            print(f"    [승자이름으로 화해 최종재검색] 브랜드정보 없음 -> '{winner_name}'로 화해 재검색")
            hwahae_final_retry = _safe_search(_search_hwahae, winner_name, known_volume, known_brand, failures=tech_failures, label="화해최종재검색")
            if hwahae_final_retry and hwahae_final_retry.get("brand"):
                entry_brand = hwahae_final_retry["brand"]
                hwahae_data = hwahae_final_retry

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
            "winner_source": winner["source"],
            "candidates_summary": {c["source"]: c.get("name") for c in candidates},
            "brand": entry_brand,
            "name": winner_name or hwahae_data.get("name"),
            "volume": winner.get("volume") or (hwahae_data.get("volume") if winner["source"] == "hwahae" else "") or "",
            "source": "hwahae+naver" if (cand_hwahae and cand_naver) else (winner["source"]),
            "obsolete": hwahae_data.get("obsolete"),
            "sale": hwahae_data.get("sale"),
            "price": naver_data.get("price") or hwahae_data.get("price") or musinsa_data.get("price"),
            "mall": naver_data.get("mall") or ("무신사" if winner["source"] == "musinsa" else None),
            "seller_trust": naver_data.get("seller_trust") or ("신뢰채널" if winner["source"] == "musinsa" else None),
            # 화해는 정보앱이지 판매처가 아니라 폴백 안 하지만, 무신사는 실제
            # 구매 가능한 쇼핑몰이므로 winner가 무신사면 그 구매링크를 쓴다.
            "product_url": naver_data.get("product_url") or (musinsa_data.get("product_url") if winner["source"] == "musinsa" else None),
            "image_url": naver_data.get("image_url"),  # 사진도 마찬가지로 네이버 것만 사용
            "image_candidates": naver_data.get("image_candidates") or [],
        }

        # [정확도개선] "한글 상품명"은 네이버 검색API가 준 title(요약형이라
        # 실제 판매페이지와 다를 수 있음)이 아니라, 진짜 구매링크 페이지의
        # 정확한 상품명을 보여주는 게 최선이다. 실제 페이지를 열어서
        # og:title/title을 가져와본다 — subprocess로 격리해서 특정
        # 사이트가 막혀있거나(차단/JS필요) 응답이 느려도 전체 배치가
        # 멈추지 않고, 실패하면 조용히 기존 방식(네이버 title)으로
        # 돌아간다("가능하면 정확하게, 안 되면 원래대로").
        if entry.get("product_url"):
            try:
                page_title_proc = subprocess.run(
                    [sys.executable, "fetch_page_title.py", entry["product_url"]],
                    capture_output=True, text=True, timeout=12,
                )
                real_title = page_title_proc.stdout.strip()
                if real_title and len(real_title) >= 5:
                    entry["real_page_title"] = real_title
            except Exception as e:  # noqa: BLE001
                print(f"    [페이지제목가져오기 실패, 기존방식 유지] {type(e).__name__}: {e}")

        # 4차: 확정된 구매링크가 실제로 품절인지 확인한다(재사용 목적:
        # 큐텐 등록 이후에도 주기적으로 이 링크가 여전히 살아있는지 재확인하는
        # 용도로 stock_checker.py를 계속 쓸 수 있다). "숨겨진 품절배지"로 인한
        # 오탐을 피하려고 실제로 화면에 보이는 요소만 판정에 쓴다.
        if entry["product_url"]:
            try:
                from stock_checker import check_stock

                stock_result = check_stock(entry["product_url"])
                entry["in_stock"] = stock_result.get("in_stock")
                entry["stock_evidence"] = stock_result.get("evidence")
                if stock_result.get("in_stock") is False:
                    print(f"    [품절감지] {entry['product_url']} — {stock_result.get('evidence')}")
            except Exception as e:  # noqa: BLE001
                print(f"    [품절체크 실패] {type(e).__name__}: {e}")
                entry["in_stock"] = None
                entry["stock_evidence"] = []
        else:
            entry["in_stock"] = None
            entry["stock_evidence"] = []

        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if retry_counts.pop(item["goods_no"], None) is not None:
            retry_state_path.write_text(json.dumps(retry_counts, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["name"] or "매칭실패"
        print(f"    -> [{entry['winner_source']}] {entry['brand']} {status}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
