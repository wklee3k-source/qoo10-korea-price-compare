"""브랜드가 정해지면 그 브랜드를 파는 몰을 골라 구매링크를 찾는다.

[왜 필요한가 — 실측 2026-08-15]
검증이 확보한 구매링크의 도메인을 브랜드별로 세어보면 규칙이 뚜렷하다.

    에스트라·이니스프리 -> amoremall.com     (아모레퍼시픽 계열)
    라네즈             -> aritaum.com        (아모레 계열 오프라인몰)
    디오디너리          -> chicor.com         (시코르 단독 취급)
    아누아·메디큐브·닥터지 -> oliveyoung.co.kr
    스킨1004·바닐라코    -> musinsa.com

그런데 지금은 "검색 결과에 우연히 그 몰이 나왔을 때"만 링크가 잡힌다.
브랜드를 이미 알아냈으면서도 그 브랜드의 몰에 직접 물어보지 않았다.

[학습 — 규칙을 손으로 적지 않는다]
브랜드→몰 대응은 검증 결과에서 자동으로 배운다. 손으로 적으면 새
브랜드가 들어올 때마다 사람이 손대야 하고, 오래된 규칙이 남는다.
같은 브랜드에서 여러 번 나온 몰일수록 먼저 시도한다.

[조회 순서]
1. 그 브랜드에서 실제로 링크가 나온 적 있는 몰 (많이 나온 순)
2. 그래도 없으면 올리브영 (전체에서 가장 많이 잡히는 몰)

[안 하는 것]
오픈마켓(쿠팡·11번가·G마켓·다나와·에누리)은 조회하지 않는다.
운영 방침상 공식 채널만 쓴다.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from oliveyoung_link_finder import pick as _oy_pick  # noqa: E402
from oliveyoung_link_finder import search as _oy_search  # noqa: E402

# 오픈마켓 — 절대 채택하지 않는다(운영 방침).
_EXCLUDED = re.compile(
    r"(coupang|11st|gmarket|auction|danawa|enuri|interpark|tmon|wemakeprice)",
    re.IGNORECASE,
)

AMOREMALL_SEARCH = "https://www.amoremall.com/kr/ko/display/search?query={}"
AMOREMALL_DETAIL = "https://www.amoremall.com/kr/ko/product/detail?onlineProdSn={}"

_AMORE_ID_RE = re.compile(r"/product/detail\?onlineProdSn=(\d+)")
_AMORE_NAME_RE = re.compile(r'class="prd_name"[^>]*>\s*([^<]+?)\s*<')


def learn_brand_stores(verified_rows) -> dict:
    """검증 결과에서 '브랜드 → 몰(많이 나온 순)'을 배운다."""
    votes = defaultdict(Counter)
    for row in verified_rows:
        url = row.get("product_url")
        brand = (row.get("brand") or "").split(" (")[0].strip()
        if not url or not brand:
            continue
        host = urlparse(url).netloc
        if not host or _EXCLUDED.search(host):
            continue
        votes[brand][host] += 1
    return {b: [h for h, _ in c.most_common()] for b, c in votes.items()}


def _fetch(url: str, timeout_ms: int = 40000) -> str:
    from playwright.sync_api import sync_playwright

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
            page.wait_for_timeout(3500)
            return page.content()
        finally:
            browser.close()


def search_amoremall(brand: str, name: str, min_overlap: float = 0.7) -> dict | None:
    """아모레몰에서 찾는다. 판정 기준은 올리브영과 같은 것을 쓴다."""
    query = f"{brand} {name}".strip()
    if not query:
        return None
    try:
        html = _fetch(AMOREMALL_SEARCH.format(urllib.parse.quote(query)))
    except Exception as exc:  # noqa: BLE001
        print(f"    [아모레몰 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    ids = _AMORE_ID_RE.findall(html)
    names = _AMORE_NAME_RE.findall(html)
    results, seen = [], set()
    for pid, nm in zip(ids, names):
        if pid in seen:
            continue
        seen.add(pid)
        results.append({"goods_no": pid, "name": nm.strip()})
    hit = _oy_pick(results, brand, name, min_overlap)
    if not hit:
        return None
    return {
        "source": "amoremall",
        "name": hit["name"],
        "product_url": AMOREMALL_DETAIL.format(hit["product_url"].rsplit("=", 1)[-1]),
        "match_score": hit["match_score"],
    }


_FINDERS = {
    "www.oliveyoung.co.kr": lambda b, n: _oy_search(b, n),
    "m.oliveyoung.co.kr": lambda b, n: _oy_search(b, n),
    "www.amoremall.com": search_amoremall,
}


def find_link(brand: str, name: str, brand_stores: dict | None = None) -> dict | None:
    """브랜드에 맞는 몰부터 순서대로 조회한다. 못 찾으면 None."""
    brand = (brand or "").split(" (")[0].strip()
    if not brand or not name:
        return None
    order = []
    for host in (brand_stores or {}).get(brand, []):
        if host in _FINDERS and host not in order:
            order.append(host)
    if "www.oliveyoung.co.kr" not in order:
        order.append("www.oliveyoung.co.kr")
    for host in order:
        try:
            hit = _FINDERS[host](brand, name)
        except Exception as exc:  # noqa: BLE001
            print(f"    [{host} 오류] {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if hit and not _EXCLUDED.search(hit.get("product_url", "")):
            return hit
    return None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--map", help="브랜드→몰 맵 json")
    a = ap.parse_args()
    bs = json.loads(Path(a.map).read_text(encoding="utf-8")) if a.map else {}
    print(json.dumps(find_link(a.brand, a.name, bs) or {}, ensure_ascii=False))
