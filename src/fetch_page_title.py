"""
fetch_page_title.py

실제 구매링크 페이지에서 정확한 상품명을 가져온다. 사이트마다 og:title
메타태그 또는 <title> 태그를 우선 시도하는 범용 방식이라, 특정 사이트
전용 파싱코드 없이도 대부분의 쇼핑몰에서 동작한다.

[안전설계] 모든 사이트가 스크래핑 가능한 건 아니다(차단, 봇방지, JS
렌더링 필요 등). 이 스크립트는 실패해도(타임아웃/차단/파싱실패 등)
예외 없이 빈 결과("")만 출력한다 — 호출하는 쪽(hwahae_verify_batch.py)이
이 빈 결과를 보고 자동으로 기존 방식(네이버 API의 title 등)으로
폴백하도록 설계되어 있다. 즉 "가능하면 더 정확하게, 안 되면 원래대로"다.

사용법:
    python fetch_page_title.py <URL>
        -> stdout에 상품명 1줄 출력(실패시 빈 줄)
"""

import re
import sys
import urllib.request


def fetch_title(url: str, timeout: int = 10) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        html = res.read(300_000).decode("utf-8", errors="ignore")  # 앞부분만(head 태그는 대부분 여기 있음)

    # 1순위: og:title (실제 상품명이 정확히 들어있는 경우가 많음, 사이트명 등 잡음 없음)
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()

    # 2순위: <title> 태그(사이트명이 붙어있는 경우가 많아 뒤쪽 " - 몰이름" 등을 잘라냄)
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        title = m.group(1).strip()
        title = re.sub(r"\s*[-|:]\s*[^-|:]{1,20}$", "", title)  # 끝에 붙은 " - 사이트명" 류 제거(짧은 것만)
        return title.strip()

    return ""


if __name__ == "__main__":
    url = sys.argv[1]
    try:
        print(fetch_title(url))
    except Exception as e:  # noqa: BLE001
        print("", file=sys.stdout)
        print(f"[fetch_page_title 실패] {type(e).__name__}: {e}", file=sys.stderr)
