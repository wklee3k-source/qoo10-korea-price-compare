# -*- coding: utf-8 -*-
"""
큐텐 파이프라인 — 한국 판매페이지 정보 수집기 v2.1.0

구매링크 페이지를 실제 크롬으로 열어 상품 정보를 긁어 '수집결과.json' 으로
저장합니다.

[왜 이 프로그램이 필요한가]
파이프라인 본체는 GitHub Actions 에서 돌지만, 네이버는 데이터센터 IP 를
HTTP 429 로 막습니다. 스크립트 요청은 가정용 IP 에서도 490 으로 거부되고,
번들 크로미움으로 열어도 429 가 뜹니다. **실제 설치된 크롬**을 띄우면
통과합니다(실측 10/10). 그래서 이 단계만 사장님 PC 에서 돌립니다.

[수집 경로 — 위에서부터 시도]
 1) 상품 상세 API 가로채기
      브랜드스토어   /n/v2/channels/{채널ID}/products/{상품ID}
      스마트스토어   /i/v2/channels/{채널ID}/products/{상품ID}
      쇼핑윈도      /product-detail/v2/channel-products?channelNo=...
    상품명·정가·판매가·재고·카테고리·리뷰수·평점·이미지·판매처·브랜드
 2) ld+json 구조화 데이터 (지그재그·아모레몰·메디큐브·무신사 등)
 3) og:title 메타태그 (최후 폴백, 상품명·가격만)

실측 2,572건: API 2,145 · ld+json 300 · og:title 127 (올리브영 92건 실패)

[필요 패키지]
    pip install playwright
    (크롬이 설치돼 있으면 playwright install 은 불필요)

[사용법]
 1) 수집대상.json 을 이 파일과 같은 폴더에 둡니다.
 2) 이 파일을 더블클릭하거나  python 상품정보수집기_v2.1.0.pyw
 3) [브라우저 열기] 를 눌러 창을 확인한 뒤 [시작] 을 누릅니다.
 4) 중간에 닫아도 진행분은 저장돼 있어 다음에 이어서 합니다.
 5) 끝나면 수집결과.json 을 Claude 창에 올리시면 됩니다.
"""
import json
import os
import queue
import re
import sys
import threading
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

VERSION = "2.1.0"
APP_TITLE = f"한국 판매페이지 수집기 v{VERSION}"
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
INPUT_PATH = os.path.join(BASE_DIR, "수집대상.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "수집결과.json")


# [v1.2.0] 브라우저 프로필(로그인·쿠키) 저장 위치.
#  스크립트가 있는 폴더를 쓰면 파일을 옮기거나 다른 폴더에서 실행할 때마다
#  프로필이 새로 만들어져 로그인이 날아간다. 실제로 시험 스크립트마다
#  폴더 이름이 달라(네이버세션 / 브라우저프로필) 로그인이 유지되지 않았다.
#  다운로드 폴더 아래 한 곳으로 고정한다. 파일을 어디 두든 같은 것을 쓴다.
def _profile_dir() -> str:
    home = os.path.expanduser("~")
    for name in ("Downloads", "다운로드"):
        cand = os.path.join(home, name)
        if os.path.isdir(cand):
            base = os.path.join(cand, "큐텐수집기")
            break
    else:
        base = os.path.join(home, "큐텐수집기")
    target = os.path.join(base, "브라우저프로필")
    os.makedirs(target, exist_ok=True)
    return target


PROFILE_DIR = _profile_dir()

NAV_TIMEOUT = 45000        # 페이지 이동 제한(ms)
SETTLE_MS = 2200           # 페이지 안정화 대기(ms)
SAVE_EVERY = 10            # 몇 건마다 저장할지
CHANNELS = ["chrome", "msedge", None]   # None = 번들 크로미움(최후 수단)


# ═══════════════════════════ 파싱 (순수 함수) ═══════════════════════════
# 이 상품의 상세 API만 골라내는 정규식.
#  상품번호를 박아 넣어야 추천 영역 응답이 섞이지 않는다. 실측에서
#  '엘라스틴 트리트먼트'를 열었는데 추천 응답의 '온더바디 클렌징폼'이
#  잡혔다. /n/ 은 브랜드스토어, /i/ 는 일반 스마트스토어.
def product_api_re(product_id: str):
    return re.compile(rf"/[ni]/v2/channels/[^/]+/products/{product_id}(\?|$)")


# 쇼핑윈도(shopping.naver.com)는 주소 형태가 다르지만 응답 구조는
#  스마트스토어와 같다. 단 상품번호가 주소에 없어 채널번호로만 구분되므로,
#  응답 안의 상품번호를 대조해 추천 영역이 섞이지 않게 한다.
WINDOW_API_RE = re.compile(r"/product-detail/v\d+/channel-products\?")

# 그 밖의 쇼핑몰(지그재그·아모레몰·메디큐브·무신사)은 페이지에
#  application/ld+json 구조화 데이터가 박혀 있다. 표준 형식이라 도메인마다
#  파서를 만들 필요가 없다.
LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def parse_api(obj: dict) -> dict:
    """상품 상세 API 응답 → 필요한 값만."""
    out = {"via": "API"}
    out["name"] = (obj.get("name") or "").strip()

    org = obj.get("salePrice")
    disc = obj.get("discountedSalePrice")
    if not isinstance(disc, (int, float)):
        disc = (obj.get("benefitsView") or {}).get("discountedSalePrice")
    out["list_price"] = int(org) if isinstance(org, (int, float)) else None
    out["sale_price"] = int(disc) if isinstance(disc, (int, float)) else out["list_price"]

    cat = obj.get("category") or {}
    out["category"] = cat.get("wholeCategoryName") or cat.get("categoryName") or ""

    # [주의] 평점은 최상위가 아니라 reviewAmount 안에 있다. 최상위에서
    #  찾다가 전 건 null 이 나왔다.
    rv = obj.get("reviewAmount") or {}
    out["review_count"] = rv.get("totalReviewCount")
    score = rv.get("averageReviewScore")
    if not isinstance(score, (int, float)):
        score = obj.get("averageReviewScore")
    out["rating"] = float(score) if isinstance(score, (int, float)) else None

    out["stock"] = obj.get("stockQuantity")
    status = obj.get("productStatusType") or obj.get("statusType") or ""
    out["status"] = status
    out["sold_out"] = (status != "SALE") if status else None

    img = ""
    imgs = obj.get("productImages")
    if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
        img = imgs[0].get("url") or ""
    out["image"] = img

    out["seller"] = (obj.get("channel") or {}).get("channelName") or ""
    brand = (obj.get("naverShoppingSearchInfo") or {}).get("brandName") or ""
    # '상세페이지 참조'는 브랜드명이 아니다.
    out["brand"] = "" if brand in ("상세페이지 참조", "기타", "") else brand
    return out


def _walk_json(node, depth=0):
    if depth > 8:
        return
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_json(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_json(v, depth + 1)


def parse_ld_json(html: str) -> dict:
    """구조화 데이터(schema.org Product)에서 상품 정보를 꺼낸다."""
    for m in LD_JSON_RE.finditer(html):
        try:
            obj = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001
            continue
        for node in _walk_json(obj):
            if node.get("@type") not in ("Product", "IndividualProduct"):
                continue
            name = (node.get("name") or "").strip()
            if not name:
                continue
            out = {"via": "ld+json", "name": name, "list_price": None,
                   "sale_price": None, "category": "", "review_count": None,
                   "rating": None, "stock": None, "status": "", "sold_out": None,
                   "image": "", "seller": "", "brand": ""}
            offers = node.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                try:
                    out["sale_price"] = int(float(str(price).replace(",", "")))
                except Exception:  # noqa: BLE001
                    pass
                avail = str(offers.get("availability") or "")
                if avail:
                    out["sold_out"] = "OutOfStock" in avail or "SoldOut" in avail
            img = node.get("image")
            if isinstance(img, list) and img:
                img = img[0]
            if isinstance(img, str):
                out["image"] = img
            brand = node.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            if isinstance(brand, str):
                out["brand"] = brand.strip()
            rating = node.get("aggregateRating")
            if isinstance(rating, dict):
                try:
                    out["rating"] = float(rating.get("ratingValue"))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    out["review_count"] = int(rating.get("reviewCount")
                                              or rating.get("ratingCount"))
                except Exception:  # noqa: BLE001
                    pass
            cat = node.get("category")
            if isinstance(cat, str):
                out["category"] = cat
            return out
    return {}


# og:title 뒤에 붙는 꼬리표. API 도 ld+json 도 없을 때만 쓰는 폴백이다.
#   "케라시스 ... 220ml, 2개 : 수수플렉스"
#   "바닐라코 클린잇제로 말차 클렌징밤 100ml - 후기 | 무신사"
TITLE_TAIL_RES = [
    re.compile(r"\s*[-–]\s*(후기|리뷰|구매평|가격|최저가)\s*[|｜].*$"),
    re.compile(r"\s*[|｜]\s*[^|｜]{1,20}$"),
    re.compile(r"\s+:\s+[^:]{1,20}$"),
    re.compile(r"\s*[-–]\s*(네이버|스마트스토어|쇼핑).*$"),
    # 쇼핑윈도 페이지 제목에 붙는 접두어
    re.compile(r"^이런\s*상품\s*어때요\?\s*"),
]


def _clean_title(title: str) -> str:
    """떼고 나서 너무 짧아지면 원본을 쓴다 — 상품명 자체가 짧은 경우
    (예: '수분크림')를 통째로 날리면 안 된다."""
    t = (title or "").strip()
    for rx in TITLE_TAIL_RES:
        stripped = rx.sub("", t).strip()
        if len(stripped) >= 8:
            t = stripped
    return t


def parse_html_fallback(html: str) -> dict:
    """API·ld+json 을 못 얻었을 때 메타태그에서 최소한이라도 건진다."""
    def meta(prop):
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']',
            html, re.I)
        return m.group(1).strip() if m else ""

    out = {"via": "og:title", "name": _clean_title(meta("og:title")),
           "image": meta("og:image"), "sale_price": None, "list_price": None,
           "category": "", "review_count": None, "rating": None,
           "stock": None, "status": "", "sold_out": None,
           "seller": "", "brand": meta("product:brand")}
    m = re.search(r'"(?:price|salePrice|discountedSalePrice)"\s*:\s*"?([0-9]{2,})', html)
    if m:
        out["sale_price"] = int(m.group(1))
    return out


# ═══════════════════════════ 브라우저 작업자 ═══════════════════════════
class BrowserWorker(threading.Thread):
    """Playwright 는 스레드 간 공유가 불가하다.

    전용 스레드 하나가 브라우저를 소유하고, 화면 스레드는 큐로만 요청한다.
    여러 스레드에서 같은 page 를 만지면 죽는다.
    """

    def __init__(self, log_cb, progress_cb, done_cb, open_cb=None):
        super().__init__(daemon=True)
        self.done_open = open_cb or (lambda: None)
        self.q = queue.Queue()
        self.log = log_cb
        self.progress = progress_cb
        self.done = done_cb
        self._pw = None
        self._ctx = None
        self._page = None
        self._stop = threading.Event()
        self.channel_used = None

    def open_browser(self):
        self.q.put(("open", None, None))

    def start_job(self, targets, results):
        self.q.put(("run", targets, results))

    def stop_job(self):
        self._stop.set()

    def shutdown(self):
        self._stop.set()
        self.q.put(("quit", None, None))

    # ── 내부 ──
    def run(self):
        while True:
            cmd, targets, results = self.q.get()
            if cmd == "quit":
                self._teardown()
                return
            if cmd == "open":
                err = self._ensure_browser()
                if err:
                    self.log(err)
                else:
                    self.log(f"브라우저: {self.channel_used}")
                    ok_page = False
                    try:
                        self._page.goto(
                            "https://smartstore.naver.com/main/products/10962405298",
                            wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                        self._page.wait_for_timeout(1500)
                        body = (self._page.inner_text("body") or "").strip()
                        ok_page = len(body) > 200 and "nidlogin" not in self._page.url
                    except Exception:  # noqa: BLE001
                        pass

                    # 상품 페이지가 제대로 안 열리면(빈 화면·오류·로그인
                    #  리다이렉트) 로그인 화면을 직접 띄워 준다. 빈 화면만
                    #  보여주고 "로그인하세요"라고 하면 어디서 할지 알 수 없다.
                    if ok_page:
                        self.log("상품 페이지가 열렸습니다. 로그인 없이 진행할 수 있습니다.")
                        self.log("  그대로 [시작]을 누르세요.")
                    else:
                        try:
                            self._page.goto("https://nid.naver.com/nidlogin.login",
                                            wait_until="domcontentloaded",
                                            timeout=NAV_TIMEOUT)
                        except Exception:  # noqa: BLE001
                            pass
                        self.log("상품 페이지가 열리지 않아 로그인 화면을 띄웠습니다.")
                        self.log("  열린 창에서 네이버에 로그인한 뒤 [시작]을 누르세요.")
                    self.log("  (이 프로그램은 [시작] 전까지 창을 건드리지 않습니다)")
                self.done_open()
                continue
            if cmd == "run":
                try:
                    self._run_job(targets, results)
                except Exception:  # noqa: BLE001
                    self.log("오류:\n" + traceback.format_exc())
                    self.done(False)

    def _ensure_browser(self) -> str:
        if self._ctx is not None:
            return ""
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        last = ""
        for ch in CHANNELS:
            kwargs = dict(
                user_data_dir=PROFILE_DIR,
                headless=False,          # 창을 실제로 띄워야 통과율이 높다
                locale="ko-KR",
                viewport={"width": 1280, "height": 860},
                args=["--disable-blink-features=AutomationControlled",
                      "--no-first-run", "--no-default-browser-check"],
            )
            if ch:
                kwargs["channel"] = ch   # 실제 설치된 크롬 — 이게 핵심이다
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
                self.channel_used = ch or "chromium(번들)"
                break
            except Exception as e:  # noqa: BLE001
                last = type(e).__name__
                continue
        if self._ctx is None:
            return f"브라우저 실행 실패({last}). 크롬 설치를 확인해 주세요."
        self._ctx.set_default_timeout(NAV_TIMEOUT)
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        return ""

    def _teardown(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = self._pw = self._page = None

    def _run_job(self, targets, results):
        err = self._ensure_browser()
        if err:
            self.log(err)
            self.done(False)
            return
        self.log(f"브라우저: {self.channel_used}")

        total = len(targets)
        done_cnt = 0
        fail_streak = 0
        for i, t in enumerate(targets, 1):
            if self._stop.is_set():
                self.log("사용자가 중지했습니다.")
                break
            gno, url = t["goods_no"], t["url"]
            # 올리브영은 partner.do 중간 주소로 들어가면 429가 뜬다.
            #  주소에 상품번호(sndVal)가 들어 있으니 최종 상세 주소로 바꿔
            #  직접 연다.
            m_oy = re.search(r"oliveyoung\.co\.kr.*[?&]sndVal=([A-Z0-9]+)", url)
            if m_oy:
                url = ("https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do"
                       f"?goodsNo={m_oy.group(1)}")

            pid_m = re.search(r"/products/(\d+)", url)
            rx = product_api_re(pid_m.group(1)) if pid_m else None
            grabbed = {}

            def on_response(res):
                # 이 안의 예외는 여기서 끝낸다. 밖으로 새면 페이지 이동
                # 실패로 오인돼 기록이 통째로 날아간다.
                try:
                    if rx is not None and rx.search(res.url):
                        obj = res.json()
                        if isinstance(obj, dict) and obj.get("name"):
                            grabbed.update(obj)
                        return
                    # 쇼핑윈도. 주소에 상품번호가 없어 응답 안의 번호를
                    #  대조한다 — 안 그러면 추천 영역이 섞인다.
                    if WINDOW_API_RE.search(res.url):
                        obj = res.json()
                        if not isinstance(obj, dict) or not obj.get("name"):
                            return
                        wid = pid_m.group(1) if pid_m else ""
                        got = str(obj.get("productNo") or obj.get("id") or "")
                        if wid and got and wid != got:
                            return
                        grabbed.update(obj)
                except Exception:  # noqa: BLE001
                    return

            self._page.on("response", on_response)
            status, nav_error = 0, ""
            try:
                res = self._page.goto(url, wait_until="domcontentloaded",
                                      timeout=NAV_TIMEOUT)
                status = res.status if res else 0
                self._page.wait_for_timeout(SETTLE_MS)
            except Exception as e:  # noqa: BLE001
                nav_error = f"{type(e).__name__}"
            try:
                self._page.remove_listener("response", on_response)
            except Exception:  # noqa: BLE001
                pass

            if grabbed:
                info = parse_api(grabbed)
            else:
                # 폴백 순서: 구조화 데이터(ld+json) -> og:title.
                #  지그재그·아모레몰·메디큐브·무신사는 ld+json 에 이름·가격·
                #  평점·리뷰수가 다 있어 og:title 보다 훨씬 낫다.
                try:
                    html = self._page.content()
                except Exception:  # noqa: BLE001
                    html = ""
                info = parse_ld_json(html) if html else {}
                if not info.get("name"):
                    info = parse_html_fallback(html) if html else {"name": "", "via": ""}
            info["http_status"] = status
            if nav_error:
                info["error"] = nav_error
            try:
                info["final_url"] = self._page.url
            except Exception:  # noqa: BLE001
                info["final_url"] = ""
            info["goods_no"] = gno
            info["url"] = url
            info["collected_at"] = datetime.now().isoformat(timespec="seconds")
            results[gno] = info

            done_cnt += 1
            # 연속 실패만 본다. 차단이 걸리면 계속 돌려봐야 헛수고이고,
            #  실패로 기록되면 나중에 다시 해야 한다.
            if info.get("name"):
                fail_streak = 0
            else:
                fail_streak += 1
                if fail_streak >= 10:
                    self.log("\n연속 10건 실패 — 차단됐을 수 있습니다. 중단합니다.")
                    self.log("잠시 뒤 다시 시작하면 남은 것부터 이어서 합니다.")
                    break
            mark = {"API": "API ", "ld+json": "LD  ", "og:title": "og  "}.get(
                info.get("via"), "실패")
            self.log(f"[{i}/{total}] {mark} {(info.get('name') or '')[:44]}")
            self.progress(i, total)

            if done_cnt % SAVE_EVERY == 0:
                save_results(results)

        save_results(results)
        self.done(True)


def save_results(results: dict):
    """중간에 닫아도 진행분이 남도록 자주 저장한다."""
    tmp = OUTPUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(results.values()), f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUTPUT_PATH)   # 원자적 교체 — 저장 중 꺼져도 안 깨진다


def load_results() -> dict:
    if not os.path.exists(OUTPUT_PATH):
        return {}
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            rows = json.load(f)
        return {r["goods_no"]: r for r in rows if r.get("goods_no")}
    except Exception:  # noqa: BLE001
        return {}


# ═══════════════════════════ 화면 ═══════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("760x520")

        self.targets = []
        self.results = load_results()
        self.running = False

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        self.info_var = tk.StringVar(value="수집대상.json 을 읽는 중…")
        ttk.Label(top, textvariable=self.info_var).pack(side="left")

        self.btn_start = ttk.Button(top, text="시작", command=self.on_start)
        self.btn_start.pack(side="right", padx=4)
        # 브라우저를 먼저 띄우고, 필요하면 사람이 로그인한 뒤 [시작] 을
        #  누르게 한다. 프로그램이 로그인 여부를 확인하려고 페이지를 새로
        #  열면 입력하던 것이 날아간다 — 그래서 신호는 사람이 준다.
        self.btn_open = ttk.Button(top, text="브라우저 열기", command=self.on_open)
        self.btn_open.pack(side="right", padx=4)
        self.btn_stop = ttk.Button(top, text="중지", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="right")

        bar = ttk.Frame(root, padding=(10, 0))
        bar.pack(fill="x")
        self.prog = ttk.Progressbar(bar, mode="determinate")
        self.prog.pack(fill="x", side="left", expand=True)
        self.prog_var = tk.StringVar(value="0 / 0")
        ttk.Label(bar, textvariable=self.prog_var, width=14).pack(side="right")

        self.text = tk.Text(root, height=24, wrap="none")
        self.text.pack(fill="both", expand=True, padx=10, pady=8)

        self.worker = BrowserWorker(self.log, self.on_progress, self.on_done,
                                    self.on_open_done)
        self.worker.start()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.load_targets()

    # ── 화면 갱신은 반드시 메인 스레드에서 ──
    def log(self, msg):
        self.root.after(0, self._log, msg)

    def _log(self, msg):
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def on_progress(self, i, total):
        self.root.after(0, self._progress, i, total)

    def _progress(self, i, total):
        self.prog["maximum"] = total
        self.prog["value"] = i
        self.prog_var.set(f"{i} / {total}")

    def on_done(self, ok):
        self.root.after(0, self._done, ok)

    def _done(self, ok):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_open.config(state="normal")
        self._log(f"\n저장 완료: {OUTPUT_PATH}")
        self._log(f"총 {len(self.results)}건이 파일에 있습니다.")

    def load_targets(self):
        if not os.path.exists(INPUT_PATH):
            self.info_var.set("수집대상.json 이 없습니다. 같은 폴더에 넣어 주세요.")
            self.btn_start.config(state="disabled")
            return
        try:
            with open(INPUT_PATH, encoding="utf-8") as f:
                self.targets = json.load(f)
        except Exception as e:  # noqa: BLE001
            self.info_var.set(f"수집대상.json 읽기 실패: {e}")
            self.btn_start.config(state="disabled")
            return
        remain = [t for t in self.targets if t["goods_no"] not in self.results]
        self.info_var.set(
            f"전체 {len(self.targets)}건 · 완료 {len(self.results)}건 · 남음 {len(remain)}건")

    def on_open(self):
        self.btn_open.config(state="disabled")
        self._log("브라우저를 엽니다…")
        self.worker.open_browser()

    def on_open_done(self):
        self.root.after(0, lambda: self.btn_open.config(state="normal"))

    def on_start(self):
        remain = [t for t in self.targets if t["goods_no"] not in self.results]
        if not remain:
            messagebox.showinfo(APP_TITLE, "남은 항목이 없습니다.")
            return
        self.running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_open.config(state="disabled")
        self._log(f"시작합니다. 남은 {len(remain)}건\n")
        self.worker._stop.clear()
        self.worker.start_job(remain, self.results)

    def on_stop(self):
        self.worker.stop_job()
        self._log("중지 요청… 현재 건이 끝나면 멈춥니다.")

    def on_close(self):
        if self.running and not messagebox.askyesno(
                APP_TITLE, "수집 중입니다. 닫을까요?\n(진행분은 저장돼 있어 다음에 이어서 합니다)"):
            return
        self.worker.shutdown()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
