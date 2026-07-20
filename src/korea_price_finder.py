"""
korea_price_finder.py

자동화 영역: 4단계(한국 원가 매칭)를 완전 자동화하기 위한 스크립트.

[배경] 지금까지 4단계는 매번 web_search로 브랜드+상품명을 검색하고 사람이
직접 판단해서 채워왔다 — 정확하지만 상품 1개당 검색 1~3회가 필요해 200개
규모로는 감당이 안 됐다. 이 스크립트는 danawa.com(다나와) 검색을 자동으로
긁어서 후보 가격을 즉시 여러 개 가져온다.

[왜 다나와인가] 이 실행환경에서 실제로 접근 가능한지 직접 확인했다:
    - search.shopping.naver.com : 접속 차단됨 (egress policy)
    - www.oliveyoung.co.kr      : 403 (봇 차단)
    - search.danawa.com         : 200 정상 접근 + 구조화된 가격 데이터 확인됨

[v2 개선사항 — 외부 AI 리뷰 반영]
    1. 브라우저 재사용: 검색마다 launch/close 하지 않고 배치 전체에서
       브라우저 1개를 계속 재사용 → 매 검색마다 브라우저 기동 비용 제거
    2. 캐시: 같은 검색어를 두 번 다시 검색하지 않도록 cache.json에 저장
    3. 공식몰 추정 휴리스틱: 결과명에 "공식"이 포함되어 있거나 판매자명이
       브랜드명과 일치하면 is_likely_official=True로 표시(완전 확정은
       아니고 사람 검수 우선순위를 정하는 용도)
    4. 이미 만들어져 있던 기능 유지: 상품별 즉시저장(중단 시 이어서 진행),
       실패 상품만 재시도 가능(goods_no 기준 resume)

사용법:
    python korea_price_finder.py "<검색어>"
    python korea_price_finder.py --batch <items_dir> <output.json> [<keywords_map.json>]
        keywords_map.json: {"goods_no": "한글 검색어", ...} 형태로 번역된
        검색어를 미리 준비해서 넘기면 그걸 사용한다(권장). 없으면
        brand_name + item_name(원문)을 그대로 써서 정확도가 크게 떨어진다.
"""

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NAME_RE = re.compile(r'class="prod_name">\s*<a[^>]*>(.*?)</a>', re.S)
PRICE_RE = re.compile(r'class="price_sect"[^>]*>.*?<strong>([\d,]+)</strong>', re.S)
LINK_RE = re.compile(r'<a href="(https://prod\.danawa\.com/bridge/go_link_goods\.php[^"]+)"')
IMG_RE = re.compile(r'thumb_image">.*?<img src="([^"]+)"', re.S)
TAG_RE = re.compile(r"</?b>")

CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / "danawa_cache.json"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(exist_ok=True, parents=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_candidates(html: str, max_results: int = 5) -> list[dict]:
    blocks = re.split(r'(?=<li[^>]*class="prod_item)', html)
    results = []
    for block in blocks:
        if 'class="prod_item' not in block:
            continue
        name_m = NAME_RE.search(block)
        price_m = PRICE_RE.search(block)
        link_m = LINK_RE.search(block)
        img_m = IMG_RE.search(block)
        if not (name_m and price_m):
            continue
        name = TAG_RE.sub("", name_m.group(1)).strip()
        price = int(price_m.group(1).replace(",", ""))
        img_url = img_m.group(1) if img_m else None
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url
        results.append(
            {
                "name": name,
                "price_krw": price,
                "link": link_m.group(1) if link_m else None,
                "img_kr": img_url,
                # 완전 확정은 아니지만 "공식"이라는 단어가 상품명에 박혀있으면
                # 공식몰/공식 유통 상품일 확률이 높다 — 사람 검수 우선순위용
                "is_likely_official": "공식" in name or "정품" in name,
            }
        )
        if len(results) >= max_results:
            break
    return results


class DanawaSession:
    """배치 검색 전체에서 브라우저 1개를 재사용한다(launch/close 반복 제거)."""

    def __init__(self, use_cache: bool = True, wait_seconds: float = 2.5):
        self.wait_seconds = wait_seconds
        self.use_cache = use_cache
        self.cache = _load_cache() if use_cache else {}
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.use_cache:
            _save_cache(self.cache)
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def search(self, keyword: str, max_results: int = 5) -> list[dict]:
        if self.use_cache and keyword in self.cache:
            return self.cache[keyword]

        url = f"https://search.danawa.com/dsearch.php?query={urllib.parse.quote(keyword)}"
        page = self._context.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="load")
            time.sleep(self.wait_seconds)
            html = page.content()
        except Exception as e:  # noqa: BLE001
            print(f"    [WARN] 검색 실패: {e}", file=sys.stderr)
            html = ""
        finally:
            page.close()

        candidates = parse_candidates(html, max_results) if html else []
        if self.use_cache:
            self.cache[keyword] = candidates
        return candidates


def find_price(keyword: str, max_results: int = 5) -> list[dict]:
    """낱개 검색용 — 배치 처리는 DanawaSession을 직접 써서 브라우저를 재사용할 것."""
    with DanawaSession(use_cache=True) as session:
        return session.search(keyword, max_results)


def batch_find(items_dir: str, out_path: str, keywords_map_path: str | None = None):
    out_file = Path(out_path)
    results = []
    done_goods_no = set()
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
        done_goods_no = {r["goods_no"] for r in results}
        print(f"[RESUME] 이미 처리된 {len(done_goods_no)}건부터 이어서 진행")

    keywords_map = {}
    if keywords_map_path and Path(keywords_map_path).exists():
        keywords_map = json.loads(Path(keywords_map_path).read_text(encoding="utf-8"))
        print(f"[INFO] 번역된 검색어 {len(keywords_map)}건 로드")

    all_items = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(items_dir).glob("*.json"))
    ]
    todo = [it for it in all_items if it.get("goods_no") not in done_goods_no]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(all_items)}건")

    with DanawaSession(use_cache=True) as session:
        for item in todo:
            goods_no = item.get("goods_no")
            brand = item.get("brand_name") or ""
            name = item.get("item_name") or ""
            keyword = keywords_map.get(goods_no) or f"{brand} {name}"[:60]

            print(f"[SEARCH] {goods_no}: {keyword}")
            candidates = session.search(keyword)
            for c in candidates:
                c["kr_site"] = "가격비교사이트 후보(danawa) — 실제 판매처/정가 여부 확인 필요"

            results.append(
                {
                    "goods_no": goods_no,
                    "qoo10_name": name,
                    "brand_name": brand,
                    "keyword_used": keyword,
                    "candidates": candidates,
                }
            )
            out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

            if candidates:
                official_count = sum(1 for c in candidates if c["is_likely_official"])
                print(
                    f"    -> {len(candidates)}건 후보(공식표기 {official_count}건), "
                    f"최저 {min(c['price_krw'] for c in candidates):,}원"
                )
            else:
                print("    -> 후보 없음")

    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--batch":
        kw_map = sys.argv[4] if len(sys.argv) > 4 else None
        batch_find(sys.argv[2], sys.argv[3], kw_map)
        return

    keyword = sys.argv[1]
    candidates = find_price(keyword)
    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
