"""
google_translate.py

jp_kr_translator.py의 수제 사전(30개 단어) 대신, 진짜 번역엔진인
구글번역 웹UI를 스크래핑해서 일본어→한글 번역을 자동화한다.

[실측 검증] "シークレットポアセラミドバブルオイルエッセンスミスト" 번역 결과
"시크릿 포아 세라미드 버블 오일 에센스 미스트"가
화해(hwahae)에서 확인된 정답 "시크릿 모공 세라마이드 버블 오일 에센스 미스트"와
거의 완벽하게 일치했다 — 사전 치환 방식보다 훨씬 정확하다.

사용법:
    python google_translate.py "<일본어 텍스트>"
"""

import re
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

RESULT_RE = re.compile(r'class="eDXd3b">([^<]+)</div>')


def translate_ja_to_ko(text: str, wait_seconds: float = 2.5) -> str | None:
    if not text.strip():
        return ""
    url = f"https://translate.google.com/?sl=ja&tl=ko&text={urllib.parse.quote(text)}&op=translate"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=20000, wait_until="load")
            time.sleep(wait_seconds)
            content = page.content()
        except Exception:  # noqa: BLE001
            content = ""
        browser.close()

    m = RESULT_RE.search(content)
    return m.group(1) if m else None


class GoogleTranslateSession:
    """배치 번역 시 브라우저를 재사용하기 위한 세션(korea_price_finder.py의
    DanawaSession과 같은 패턴)."""

    def __init__(self, wait_seconds: float = 2.0):
        self.wait_seconds = wait_seconds
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

    def translate(self, text: str) -> str | None:
        if not text.strip():
            return ""
        url = f"https://translate.google.com/?sl=ja&tl=ko&text={urllib.parse.quote(text)}&op=translate"
        page = self._context.new_page()
        try:
            page.goto(url, timeout=20000, wait_until="load")
            time.sleep(self.wait_seconds)
            content = page.content()
        except Exception:  # noqa: BLE001
            content = ""
        finally:
            page.close()
        m = RESULT_RE.search(content)
        return m.group(1) if m else None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print(translate_ja_to_ko(sys.argv[1]))
