"""큐텐 브랜드(일본어/영문)의 한글 표기를 화해에서 알아낸다.

[기존 도구와 방향이 반대다]
`hwahae_brand_lookup.py`는 **한글 브랜드를 이미 알 때** 그 영문표기를
확인하는 도구다. 그런데 실제 막히는 지점은 그 반대다 — 큐텐 원본은
일본어나 영문 브랜드만 주고, 우리는 한글을 모른다.

    큐텐 원본 brand: エルジューダ / lily eve / BLANC DUBU
    필요한 것       : 엘쥬다 / 릴리이브 / 블랑두부

한글 브랜드를 모르면 상품명 앞에 브랜드를 붙일 수 없고(v7.50.0),
브랜드 없는 검색어는 소스마다 다른 제품을 물어와 합의부족으로
버려진다(실측 2026-08-15: 이름확정 통과율 39.6%).

[경로]
    일본어 브랜드 → (큐텐 브랜드 마스터 41,186개) → 영문
    영문 브랜드   → (화해 검색)                  → "한글 (English)"

화해는 브랜드를 `아누아 (ANUA)` 형태로 준다. 괄호 안 영문이 우리가
넣은 것과 같으면 괄호 앞 한글을 채택한다.

[채택 기준]
영문이 일치할 때만 받는다. 화해는 검색어와 무관해도 뭐라도 보여주기
때문에, 1등 결과의 브랜드를 그냥 믿으면 엉뚱한 한글이 사전에 박힌다.
사전은 한 번 오염되면 이후 모든 상품명에 잘못된 브랜드가 붙는다.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from hwahae_name_corrector import _parse_products  # noqa: E402

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


class HwahaeSession:
    """브라우저를 한 번만 띄우고 계속 쓴다.

    [왜 필요한가] 원래 쓰던 조회 함수는 검색 한 번마다 크로미움을
    새로 띄우고 닫는다. 상품 몇 건을 확인할 땐 문제가 없지만, 브랜드
    1,373개를 훑을 땐 브랜드당 5~6초가 되어 두 시간이 걸린다.
    그중 대부분이 브라우저 기동 시간이다. 세션을 유지하면 브랜드당
    1~2초로 줄어든다.
    """

    def __init__(self, wait: float = 0.7):
        self.wait = wait
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        context = self._browser.new_context(
            user_agent=DESKTOP_UA, ignore_https_errors=True)
        self._page = context.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def fetch(self, keyword: str) -> str:
        url = "https://www.hwahae.co.kr/search?q=" + urllib.parse.quote(keyword)
        try:
            self._page.goto(url, timeout=15000, wait_until="domcontentloaded")
            self._page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(self.wait)
        try:
            return self._page.content()
        except Exception:  # noqa: BLE001
            return ""

BRAND_PAREN_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")
_ASCII_RE = re.compile(r"^[\x20-\x7E]+$")


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", (s or "")).lower()


def load_jp_to_en(csv_path: str) -> dict:
    """큐텐 공식 브랜드 마스터에서 일본어 → 영문 표기를 읽는다."""
    mapping = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            jp = (row.get("Japanese") or "").strip()
            en = (row.get("English") or "").strip()
            if jp and en:
                mapping.setdefault(jp, en)
    return mapping


def to_english(brand: str, jp_to_en: dict) -> str:
    """이 브랜드를 화해에 물어볼 영문 검색어로 바꾼다. 못 바꾸면 빈 문자열."""
    brand = (brand or "").strip()
    if not brand:
        return ""
    if _ASCII_RE.match(brand):
        return brand
    return jp_to_en.get(brand, "")


def ask_hwahae(english: str, session) -> str:
    """영문 브랜드로 화해에 물어 한글 브랜드를 얻는다. 확신 없으면 빈 문자열."""
    html = session.fetch(english)
    products = _parse_products(html)
    want = _norm(english)
    for product in products[:5]:
        m = BRAND_PAREN_RE.match(product.get("brand") or "")
        if not m:
            continue
        korean, eng = m.group(1).strip(), m.group(2).strip()
        if _norm(eng) == want and korean:
            return korean
    return ""


def run(brands, jp_to_en, existing, limit, delay, done_path=None,
        dict_path=None, session=None, foreign_path=None) -> dict:
    """한 번에 다 돌기엔 오래 걸려서(브랜드당 3~4초) 나눠 돌린다.

    이미 처리한 브랜드는 done 파일에 남겨 다음 실행에서 건너뛴다.
    사전(dict)만으로 판단하면 '화해가 못 찾은 브랜드'를 매번 다시
    물어보게 돼 시간이 그쪽으로 다 샌다.
    """
    done = set()
    if done_path and Path(done_path).exists():
        try:
            done = set(json.loads(Path(done_path).read_text(encoding="utf-8")))
        except ValueError:
            done = set()
    learned = {}
    not_in_korea = []
    skipped_no_en = 0
    processed = 0
    for i, brand in enumerate(brands, 1):
        if processed >= limit:
            break
        if brand in existing or brand in done:
            continue
        english = to_english(brand, jp_to_en)
        if not english:
            skipped_no_en += 1
            done.add(brand)
            continue
        processed += 1
        try:
            korean = ask_hwahae(english, session)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] {brand}: 오류 {type(exc).__name__}")
            time.sleep(delay)
            continue
        done.add(brand)
        if not korean:
            # [v7.67.0] 화해에서 못 찾았다 = 한국에서 안 판다.
            #
            # 화해는 한국 화장품 사이트다. 영문 표기까지 만들어서 물어봤는데
            # 없다면 브랜드를 모르는 게 아니라 한국 유통이 없다는 신호다.
            #
            # [실측 2026-08-16] 이렇게 못 찾은 브랜드의 상품 143건을
            # 검증해 보니 이름확정이 23건(16.1%)이었다. 전체 평균 47.2%의
            # 3분의 1이다. 어느 소스에서도 안 잡히는 게 당연하다.
            # 그동안은 이걸 사람이 눈으로 골라 해외브랜드에 넣었는데,
            # 미확인이 2,000건씩 쌓일 때마다 되풀이할 일이 아니다.
            not_in_korea.append(brand)
        if korean:
            learned[brand] = korean
            print(f"[{i}] {brand} ({english}) -> {korean}", flush=True)
        # 한 건 끝날 때마다 저장한다. 브랜드당 5~6초라 한 번에 다 못 돌고
        # 중간에 끊기는데, 끝에서만 저장하면 그때까지 한 게 전부 날아간다.
        if done_path:
            Path(done_path).write_text(
                json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
        if learned and dict_path:
            full = json.loads(Path(dict_path).read_text(encoding="utf-8"))
            full.update(learned)
            Path(dict_path).write_text(
                json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(delay)
    if skipped_no_en:
        print(f"[건너뜀] 영문 표기를 못 구한 브랜드 {skipped_no_en}개")
    if done_path:
        Path(done_path).write_text(
            json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    if not_in_korea and foreign_path:
        try:
            fp = Path(foreign_path)
            cur = set(json.loads(fp.read_text(encoding="utf-8"))) if fp.exists() else set()
            merged = sorted(cur | set(not_in_korea))
            if len(merged) > len(cur):
                fp.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                              encoding="utf-8")
                print(f"[해외브랜드 등록] {len(merged) - len(cur)}개 추가 "
                      f"(화해에 없음 = 한국 미판매)")
        except (OSError, ValueError) as exc:
            print(f"[경고] 해외브랜드 목록 갱신 실패: {exc}")
    return learned


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", required=True, help="미확인 브랜드 목록 json")
    ap.add_argument("--master", required=True, help="큐텐 브랜드 마스터 csv")
    ap.add_argument("--dict", required=True, help="브랜드 사전 json (갱신 대상)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--done", help="처리 완료 브랜드 기록 json (이어서 돌리기용)")
    ap.add_argument("--foreign", help="해외브랜드 목록 json (화해에 없으면 여기 추가)")
    a = ap.parse_args()

    brands = json.loads(Path(a.brands).read_text(encoding="utf-8"))
    jp_to_en = load_jp_to_en(a.master)
    full = json.loads(Path(a.dict).read_text(encoding="utf-8"))
    existing = {k for k in full if not k.startswith("_")}

    with HwahaeSession(wait=a.delay) as session:
        learned = run(brands, jp_to_en, existing, a.limit, a.delay, a.done,
                      a.dict if a.apply else None, session,
                      a.foreign if a.apply else None)
    print(f"\n새로 알아낸 브랜드 {len(learned)}개")

    if a.apply and learned:
        full.update(learned)
        Path(a.dict).write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"사전에 반영 — 총 {len([k for k in full if not k.startswith('_')])}개")
    elif learned:
        print("(시험 실행 — --apply 를 붙이면 사전에 반영)")
