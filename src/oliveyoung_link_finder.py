"""올리브영에서 확정된 상품명으로 구매 링크를 찾는다.

[왜 필요한가 — 실측 2026-08-15]
재검증 절반 시점에 이름은 확정됐는데 구매링크가 없는 건이 652건 나왔다.
그중 470건은 화해가 "안 팔린다"고 알려준 것이라 제외하고, 나머지
182건은 지금도 팔리는데 링크만 못 구한 것이다.

확보된 링크의 도메인을 보면 올리브영이 127건으로 가장 많은데, 이건
"검색 결과에 우연히 올리브영이 나왔을 때"만 잡힌 것이다. 화해가
브랜드와 정확한 상품명을 알려준 뒤 **올리브영에 직접 물어보는 단계가
없었다.**

    화해: 토리든 / 밸런스풀 시카 진정 크림  ← 이름은 정확히 알아냄
    → 그런데 여기서 멈춤. 올리브영에 물어보면 바로 나오는 상품이다.

[검색어 구성]
브랜드 + 상품명으로 친다. 브랜드를 빼면 다른 브랜드의 비슷한 제품이
1등으로 올라온다(화해·네이버에서 이미 겪은 문제와 같다).

[채택 기준 — 아무거나 1등을 쓰지 않는다]
올리브영은 검색어와 무관해도 뭐라도 보여준다. 그래서:
  1. 결과 상품명에 브랜드가 들어 있어야 한다
  2. 상품명 핵심 토큰이 일정 비율 이상 겹쳐야 한다
둘 다 만족하지 못하면 None을 돌려준다. 틀린 링크를 붙이는 것보다
링크가 없는 게 낫다 — 잘못된 링크는 검수 단계에서 걸러지지 않는다.
"""

from __future__ import annotations

import re
import sys
import urllib.parse

SEARCH_URL = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query={}"
GOODS_URL = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={}"

_GOODS_RE = re.compile(r"goodsNo=([A-Z0-9]{10,})")
_NAME_RE = re.compile(r'class="tx_name"[^>]*>([^<]+)<')
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# 상품명에 흔히 붙는 수식어 — 겹침 계산에서 뺀다.
_STOPWORDS = {
    "기획", "단독기획", "본품", "증정", "세트", "리필", "대용량", "신상",
    "NEW", "new", "정품", "무료배송", "특가", "할인", "한정",
    "ml", "g", "mL", "매", "개", "EA", "ea", "호",
}

# 같은 라인의 다른 제품을 가르는 말. 한쪽에만 있으면 다른 상품으로 본다.
#
# [왜 따로 두는가 — 실측 2026-08-15]
# "에어핏 선크림 플러스"를 찾는데 "에어핏 선크림 라이트"가 겹침 0.571로
# 통과했다. 토큰 겹침만 보면 이 둘은 거의 같아 보이지만 실제로는 다른
# 상품이고, 잘못된 링크는 검수 단계에서 걸러지지 않는다.
_VARIANT_WORDS = {
    "플러스", "라이트", "딥", "마일드", "인텐시브", "프로", "맥스",
    "미니", "쿠션", "스틱", "밤", "젤", "크림", "로션", "세럼", "앰플",
    "토너", "미스트", "패드", "마스크", "오일", "폼", "워터", "에센스",
    "선크림", "선세럼", "선스틱", "쿨링", "포맨", "맨", "키즈", "베이비",
}

# 대괄호 프로모션 문구, 자외선 지수 표기는 겹침 계산에서 제외한다.
_NOISE_RE = re.compile(r"\[[^\]]*\]|SPF\s*\d+\+?|PA\++")


def _tokens(text: str) -> set[str]:
    text = _NOISE_RE.sub(" ", text or "")
    return {
        t for t in _TOKEN_RE.findall(text)
        if t not in _STOPWORDS and len(t) >= 2 and not t.isdigit()
    }


def _fetch(keyword: str, timeout_ms: int = 40000) -> str:
    from playwright.sync_api import sync_playwright

    url = SEARCH_URL.format(urllib.parse.quote(keyword))
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
                )
            )
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            return page.content()
        finally:
            browser.close()


def parse_results(html: str) -> list[dict]:
    """검색 결과 페이지에서 (상품번호, 상품명) 목록을 뽑는다."""
    ids = _GOODS_RE.findall(html or "")
    names = _NAME_RE.findall(html or "")
    out = []
    seen = set()
    for goods_no, name in zip(ids, names):
        if goods_no in seen:
            continue
        seen.add(goods_no)
        out.append({"goods_no": goods_no, "name": name.strip()})
    return out


def _variant_conflict(want: set[str], got: set[str]) -> bool:
    """제품 라인을 가르는 말이 서로 어긋나면 True(=다른 상품)."""
    a = want & _VARIANT_WORDS
    b = got & _VARIANT_WORDS
    if not a or not b:
        return False
    return bool(a - b) or bool(b - a)


def pick(results: list[dict], brand: str, name: str, min_overlap: float = 0.7) -> dict | None:
    """브랜드가 맞고 이름이 충분히 겹치는 결과 하나를 고른다. 없으면 None."""
    want = _tokens(name)
    if not want:
        return None
    brand_key = re.sub(r"\s+", "", brand or "").lower()
    best = None
    best_score = 0.0
    for item in results:
        got_raw = item.get("name") or ""
        if brand_key and brand_key not in re.sub(r"\s+", "", got_raw).lower():
            continue
        got = _tokens(got_raw)
        if not got:
            continue
        if _variant_conflict(want, got):
            continue
        score = len(want & got) / len(want)
        if score > best_score:
            best, best_score = item, score
    if best is None or best_score < min_overlap:
        return None
    return {
        "source": "oliveyoung",
        "name": best["name"],
        "product_url": GOODS_URL.format(best["goods_no"]),
        "match_score": round(best_score, 3),
    }


def search(brand: str, name: str, min_overlap: float = 0.7) -> dict | None:
    """브랜드+상품명으로 올리브영 구매링크를 찾는다. 못 찾으면 None."""
    query = f"{brand} {name}".strip()
    if not query:
        return None
    try:
        html = _fetch(query)
    except Exception as exc:  # noqa: BLE001
        print(f"    [올리브영 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if "403 ERROR" in html:
        print("    [올리브영 차단] 403", file=sys.stderr)
        return None
    return pick(parse_results(html), brand, name, min_overlap)


if __name__ == "__main__":
    import json

    b = sys.argv[1] if len(sys.argv) > 1 else ""
    n = sys.argv[2] if len(sys.argv) > 2 else ""
    print(json.dumps(search(b, n) or {}, ensure_ascii=False))
