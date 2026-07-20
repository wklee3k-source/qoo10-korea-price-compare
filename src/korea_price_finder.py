"""
korea_price_finder.py

자동화 영역: 4단계(한국 원가 매칭)를 완전 자동화하기 위한 스크립트.

[v3 — 외부 AI 코드리뷰 반영, 실서비스 안정성 개선]
    1. 정규식 HTML 파싱 제거 → BeautifulSoup CSS selector로 교체
       (다나와가 class 이름을 조금만 바꿔도 정규식은 0건이 되지만
       selector는 훨씬 덜 깨지고, 부수효과로 HTML 엔티티(&amp;)도
       bs4가 알아서 풀어줘서 이전에 있었던 링크 깨짐 버그가 같이 해결됨)
    2. 원자적 저장(atomic write): tmp 파일에 먼저 쓰고 rename → 중간에
       프로세스가 죽어도(Ctrl+C, 타임아웃) 결과 파일이 반쯤 써진 상태로
       깨지지 않는다
    3. 재시도(retry) + timeout: page.goto 실패 시 1s/2s/4s 지수 백오프로
       최대 3회 재시도, timeout도 명시적으로 지정
    4. SQLite 캐시: 여러 스레드가 동시에 JSON 파일에 쓰다가 내용이
       깨지던(lost update) 문제를 SQLite 트랜잭션으로 해결

[왜 다나와인가] 이 실행환경에서 접근 가능한 사이트를 조사했다:
    막힘: search.shopping.naver.com, oliveyoung.co.kr, brand.naver.com,
          coupang.com, gmarket.co.kr
    가능: search.danawa.com, musinsa.com, zigzag.kr, 11st.co.kr, ssg.com
다나와는 가격비교사이트라 원래 소싱 규칙에는 안 맞지만, 검색 커버리지가
넓어서 "후보 발굴"용으로 쓴다. 무신사/지그재그는 원래 허용 소싱처
목록에 있던 곳이라 향후 "검증"용으로 추가하는 것을 권장(아직 파서 미구현).

사용법:
    python korea_price_finder.py "<검색어>"
    python korea_price_finder.py --batch <items_dir> <output.json> [<keywords_map.json>]
    python korea_price_finder.py --batch-parallel <items_dir> <output.json> [<keywords_map.json>] [workers]
"""

import json
import os
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CACHE_DB_PATH = Path(__file__).resolve().parent.parent / "output" / "danawa_cache.sqlite3"

# 브랜드별 공식 도메인 화이트리스트 — 지금까지 이 프로젝트에서 실제로 확인한 것들.
OFFICIAL_DOMAINS = {
    "이니스프리": ["innisfree.com", "amoremall.com"],
    "라네즈": ["laneige.com", "amoremall.com"],
    "COSRX": ["cosrx.co.kr"],
    "바닐라코": ["banila.com", "banilaco.com"],
    "VT코스메틱": ["vt-cosmetics.com"],
    "피지오겔": ["physiogel.co.kr"],
    "닥터트웬티프로젝트": ["dr20project.com"],
    "Dr.twentyproject": ["dr20project.com"],
    "썸바이미": ["somebymi.co.kr", "somebymi.com", "somebyme.net"],
    "마녀공장": ["manyo.co.kr"],
    "티르티르": ["tirtir.co.kr"],
    "TIRTIR": ["tirtir.co.kr"],
    "메이크프렘": ["makeprem.com"],
    "씨스터앤": ["sister-ann.com"],
    "SISTER ANN": ["sister-ann.com"],
    "힌스": ["hince.co.kr"],
    "hince": ["hince.co.kr"],
    "GROWUS": ["growus.kr"],
    "KAHI": ["kahicosmetics.co.kr", "kahi.shop"],
    "가히": ["kahicosmetics.co.kr", "kahi.shop"],
    "프랭클리": ["frankly.co.kr"],
    "frankly": ["frankly.co.kr"],
    "바이오던스": ["biodance.co.kr"],
    "Biodance": ["biodance.co.kr"],
    "셀퓨전씨": ["cellfusionc.co.kr"],
    "피부미": ["pibumi.com", "pibumi.co.kr"],
    "PIBUMI": ["pibumi.com", "pibumi.co.kr"],
    "리쥬란": ["pdrnmall.co.kr"],
    "메디큐브": ["medicube.kr"],
    "에이프릴스킨": ["aprilskin.com"],
}


def domain_matches_brand(domain: str, brand: str) -> bool:
    if not domain:
        return False
    # brand.naver.com/<브랜드명> 처럼 path에 브랜드가 들어가는 네이버
    # 브랜드스토어 형태도 고려(도메인만으로는 구분이 안 되므로 별도 처리 필요 —
    # 지금은 domain 인자에 path까지 포함해서 넘겨주는 걸 전제로 한다)
    known = OFFICIAL_DOMAINS.get(brand.strip())
    if not known:
        return False
    return any(d in domain for d in known)


class SqliteCache:
    """여러 스레드가 동시에 접근해도 안전한 캐시. JSON 파일 하나를 여러
    스레드가 동시에 load→수정→save 하면 lost update가 생기는데, SQLite는
    트랜잭션이 있어서 이 문제가 없다."""

    def __init__(self, path: Path = CACHE_DB_PATH, ttl_days: int = 30):
        self.path = path
        self.ttl_seconds = ttl_days * 86400
        path.parent.mkdir(exist_ok=True, parents=True)
        self._init_schema()

    def _connect(self):
        # check_same_thread=False: 여러 스레드에서 같은 인스턴스를 쓰되
        # 매 호출마다 새 커넥션을 열어서 실제 동시쓰기는 SQLite 자체 락으로 처리
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # 동시 읽기/쓰기 성능 향상
        return conn

    def _init_schema(self):
        conn = self._connect()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                keyword TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        conn.commit()
        conn.close()

    def get(self, keyword: str):
        conn = self._connect()
        row = conn.execute(
            "SELECT result_json, updated_at FROM cache WHERE keyword = ?", (keyword,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        result_json, updated_at = row
        if time.time() - updated_at > self.ttl_seconds:
            return None  # 만료됨(정가가 바뀌었을 수 있으니 재검색)
        return json.loads(result_json)

    def set(self, keyword: str, value: list[dict]):
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO cache (keyword, result_json, updated_at) VALUES (?, ?, ?)",
            (keyword, json.dumps(value, ensure_ascii=False), time.time()),
        )
        conn.commit()
        conn.close()


def atomic_write_json(path: Path, data):
    """중간에 죽어도 결과 파일이 반쯤 써진 상태로 깨지지 않도록 tmp에 먼저
    쓰고 rename한다(rename은 원자적 연산)."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)  # 같은 파일시스템 내에서는 원자적


def parse_candidates(html: str, max_results: int = 5) -> list[dict]:
    """BeautifulSoup CSS selector 기반 파싱. 정규식보다 다나와의 사소한
    마크업 변경에 덜 깨진다."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for item in soup.select("li.prod_item"):
        name_el = item.select_one("p.prod_name a")
        price_el = item.select_one("p.price_sect strong")
        if not (name_el and price_el):
            continue

        name = name_el.get_text(strip=True)
        price_text = price_el.get_text(strip=True).replace(",", "")
        if not price_text.isdigit():
            continue
        price = int(price_text)

        link_el = item.select_one('a[href*="go_link_goods.php"]')
        link = link_el["href"] if link_el else None  # bs4가 &amp; 자동으로 풀어줌

        img_el = item.select_one(".thumb_image img")
        img_url = img_el.get("src") if img_el else None
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

        results.append(
            {
                "name": name,
                "price_krw": price,
                "link": link,
                "img_kr": img_url,
                "is_likely_official": "공식" in name or "정품" in name,
            }
        )
        if len(results) >= max_results:
            break
    return results


class DanawaSession:
    """배치 검색 전체에서 브라우저 1개를 재사용한다(launch/close 반복 제거)."""

    def __init__(self, use_cache: bool = True, wait_seconds: float = 2.5, max_retries: int = 3):
        self.wait_seconds = wait_seconds
        self.max_retries = max_retries
        self.use_cache = use_cache
        self.cache = SqliteCache() if use_cache else None
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _goto_with_retry(self, page, url: str):
        delay = 1.0
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                page.goto(url, timeout=15000, wait_until="load")
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < self.max_retries:
                    print(f"    [RETRY {attempt}/{self.max_retries}] {delay}s 대기 후 재시도: {e}", file=sys.stderr)
                    time.sleep(delay)
                    delay *= 2  # 지수 백오프: 1s -> 2s -> 4s
        print(f"    [FAIL] {self.max_retries}회 재시도 후 포기: {last_err}", file=sys.stderr)
        return False

    def resolve_final_domain(self, bridge_link: str) -> str | None:
        if not bridge_link:
            return None
        page = self._context.new_page()
        try:
            ok = self._goto_with_retry(page, bridge_link)
            if not ok:
                return None
            time.sleep(1.5)
            return urllib.parse.urlparse(page.url).netloc
        finally:
            page.close()

    def search(self, keyword: str, max_results: int = 5) -> list[dict]:
        if self.use_cache:
            cached = self.cache.get(keyword)
            if cached is not None:
                return cached

        url = f"https://search.danawa.com/dsearch.php?query={urllib.parse.quote(keyword)}"
        page = self._context.new_page()
        try:
            ok = self._goto_with_retry(page, url)
            html = page.content() if ok else ""
            if ok:
                time.sleep(self.wait_seconds)
                html = page.content()
        finally:
            page.close()

        candidates = parse_candidates(html, max_results) if html else []
        if self.use_cache:
            self.cache.set(keyword, candidates)
        return candidates


def find_price(keyword: str, max_results: int = 5) -> list[dict]:
    with DanawaSession(use_cache=True) as session:
        return session.search(keyword, max_results)


def _run_batch(todo: list[dict], keywords_map: dict, out_file: Path, results: list, lock=None, verify_official: bool = True):
    with DanawaSession(use_cache=True) as session:
        for item in todo:
            goods_no = item.get("goods_no")
            brand = item.get("brand_name") or ""
            name = item.get("item_name") or ""
            keyword = keywords_map.get(goods_no) or f"{brand} {name}"[:60]

            candidates = session.search(keyword)
            for c in candidates:
                c["kr_site"] = "가격비교사이트 후보(danawa) — 실제 판매처/정가 여부 확인 필요"

            if verify_official and candidates:
                top = candidates[0]
                domain = session.resolve_final_domain(top.get("link"))
                if domain:
                    top["resolved_domain"] = domain
                    top["is_official_confirmed"] = domain_matches_brand(domain, brand)
                    if top["is_official_confirmed"]:
                        top["kr_site"] = f"공식몰 확인됨({domain}) — 자동판별"

            entry = {
                "goods_no": goods_no,
                "qoo10_name": name,
                "brand_name": brand,
                "keyword_used": keyword,
                "candidates": candidates,
            }

            if lock:
                with lock:
                    results.append(entry)
                    atomic_write_json(out_file, results)
            else:
                results.append(entry)
                atomic_write_json(out_file, results)

            status = f"{len(candidates)}건" if candidates else "후보없음"
            print(f"[SEARCH] {goods_no}: {keyword} -> {status}")


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

    all_items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(items_dir).glob("*.json"))]
    todo = [it for it in all_items if it.get("goods_no") not in done_goods_no]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(all_items)}건")

    _run_batch(todo, keywords_map, out_file, results)
    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")


def batch_find_parallel(items_dir: str, out_path: str, keywords_map_path: str | None = None, workers: int = 4):
    import threading

    out_file = Path(out_path)
    lock = threading.Lock()
    results = []
    done_goods_no = set()
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
        done_goods_no = {r["goods_no"] for r in results}
        print(f"[RESUME] 이미 처리된 {len(done_goods_no)}건부터 이어서 진행")

    keywords_map = {}
    if keywords_map_path and Path(keywords_map_path).exists():
        keywords_map = json.loads(Path(keywords_map_path).read_text(encoding="utf-8"))

    all_items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(items_dir).glob("*.json"))]
    todo = [it for it in all_items if it.get("goods_no") not in done_goods_no]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(all_items)}건 — {workers}개 워커로 병렬 처리")
    print("[INFO] 캐시는 이제 SQLite라 스레드 간 lost update 없이 안전하게 공유됨")

    chunks = [todo[i::workers] for i in range(workers)]
    threads = [
        threading.Thread(target=_run_batch, args=(chunk, keywords_map, out_file, results, lock), name=f"W{i}")
        for i, chunk in enumerate(chunks)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--batch":
        kw_map = sys.argv[4] if len(sys.argv) > 4 else None
        batch_find(sys.argv[2], sys.argv[3], kw_map)
        return

    if sys.argv[1] == "--batch-parallel":
        kw_map = sys.argv[4] if len(sys.argv) > 4 else None
        workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4
        batch_find_parallel(sys.argv[2], sys.argv[3], kw_map, workers)
        return

    keyword = sys.argv[1]
    candidates = find_price(keyword)
    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
