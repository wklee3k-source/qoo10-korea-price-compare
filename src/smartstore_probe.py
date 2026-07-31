"""smartstore_probe.py — 스마트스토어 상품명을 어떤 방법으로 가져올 수 있는지 측정.

[배경] 검수페이지는 '판매페이지에서 직접 가져온 상품명'을 최우선으로 쓴다.
네이버 API의 title은 요약형이라 실제 판매페이지와 다를 수 있어서다.
그런데 확보율이 10.1%(2,572건 중 260건)뿐이고, 못 가져온 대부분이
스마트스토어다. 구매링크의 절반 가까이가 거기라 영향이 크다.

원인이 무엇인지가 갈린다.
    차단이면        -> 브라우저를 붙여도 소용없다
    JS 렌더링이면   -> 브라우저로 해결된다
로컬(이 대화 환경)에서는 403이 떴지만 'Blocked by egress policy'였다.
즉 환경 문제였고 스마트스토어 자체 차단인지는 확인되지 않았다.
GitHub Actions는 화해·무신사를 정상 크롤하는 곳이라 결과가 다를 수 있다.

세 가지를 같은 URL로 나란히 시도해 응답 코드와 제목을 찍는다.
    ① 데스크톱 주소 + urllib
    ② 모바일 주소(m.smartstore) + urllib
    ③ Playwright 브라우저

아무것도 바꾸지 않는 측정 전용 스크립트다.

사용법:
    python smartstore_probe.py <검증본.json> [건수]
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

OG_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.I)
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)


def _pick_title(html: str) -> str:
    m = OG_RE.search(html) or TITLE_RE.search(html)
    return m.group(1).strip() if m else ""


def try_urllib(url: str, ua: str) -> tuple[str, str]:
    """(상태, 제목)을 돌려준다. 상태는 'ok' 또는 오류 요약."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            html = res.read(300_000).decode("utf-8", errors="ignore")
        title = _pick_title(html)
        return ("ok" if title else "제목없음", title)
    except urllib.error.HTTPError as e:
        return (f"HTTP {e.code}", "")
    except Exception as e:  # noqa: BLE001
        return (f"{type(e).__name__}", "")


def try_browser(urls: list[str]) -> dict:
    """Playwright로 한 번에 처리한다(브라우저 기동 비용이 커서 재사용)."""
    out = {}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print(f"[브라우저] playwright 없음: {e}")
        return {u: ("playwright없음", "") for u in urls}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=UA_DESKTOP, locale="ko-KR")
            for url in urls:
                try:
                    page = ctx.new_page()
                    res = page.goto(url, timeout=25000, wait_until="domcontentloaded")
                    status = res.status if res else 0
                    title = (page.title() or "").strip()
                    if not title:
                        # 제목이 비어 있으면 og:title을 직접 읽어본다.
                        try:
                            title = page.get_attribute('meta[property="og:title"]',
                                                       "content", timeout=3000) or ""
                        except Exception:  # noqa: BLE001
                            title = ""
                    out[url] = (f"HTTP {status}" if not title else "ok", title.strip())
                    page.close()
                except Exception as e:  # noqa: BLE001
                    out[url] = (type(e).__name__, "")
            browser.close()
    except Exception as e:  # noqa: BLE001
        print(f"[브라우저] 기동 실패: {e}")
        for u in urls:
            out.setdefault(u, ("기동실패", ""))
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    rows = json.loads(path.read_text(encoding="utf-8"))
    # [v7.8.0] 스마트스토어만 보던 것을 도메인별로 넓혔다. 실측 결과
    #  스마트스토어는 429(IP 대역 차단)라 방법이 없는데, 올리브영 94건·
    #  지그재그 46건·메디큐브 21건도 0%였다. 이쪽은 원인이 다를 수 있어
    #  같이 잰다. 브랜드스토어(brand.naver.com)는 데이터에 링크가 없어
    #  네이버 도메인 전체가 막히는지 확인용으로 직접 넣는다.
    targets = ["smartstore.naver.com", "shopping.naver.com", "www.oliveyoung.co.kr",
               "zigzag.kr", "themedicube.co.kr"]
    per_domain = max(1, limit // len(targets))
    urls, seen = [], {d: 0 for d in targets}
    for r in rows:
        u = r.get("product_url") or ""
        for d in targets:
            if d in u and seen[d] < per_domain and u not in urls:
                urls.append(u)
                seen[d] += 1
    urls += ["https://brand.naver.com/anua/products/8175823456",
             "https://brand.naver.com/medicube"]
    if not urls:
        print("[중단] 스마트스토어 링크가 없다")
        return 0
    print(f"[표본] 스마트스토어 {len(urls)}건\n")

    browser_result = try_browser(urls)

    stat = {"데스크톱": 0, "모바일": 0, "브라우저": 0}
    for i, url in enumerate(urls, 1):
        s1, t1 = try_urllib(url, UA_DESKTOP)
        time.sleep(1)
        s2, t2 = try_urllib(url.replace("smartstore.naver.com", "m.smartstore.naver.com"), UA_MOBILE)
        time.sleep(1)
        s3, t3 = browser_result.get(url, ("?", ""))
        for key, s in (("데스크톱", s1), ("모바일", s2), ("브라우저", s3)):
            if s == "ok":
                stat[key] += 1
        print(f"{i:2d}. {re.sub(r'^https?://', '', url).split('/')[0]}  {url[-40:]}")
        print(f"    데스크톱 {s1:12s} {t1[:44]}")
        print(f"    모바일   {s2:12s} {t2[:44]}")
        print(f"    브라우저 {s3:12s} {t3[:44]}")

    print("\n" + "=" * 52)
    for key, n in stat.items():
        print(f"  {key}: {n}/{len(urls)} 성공")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
