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


# [v7.6.0] 상품명이 아닌 제목들. 실측 260건 중 93건이 이런 값이었고,
#  검수페이지가 real_page_title을 최우선으로 쓰는 탓에 상품명 자리에
#  '에러 페이지'(92건)나 '지그재그 스토어'(46건)가 그대로 표시됐다.
#  길이 5자 이상이면 통과시키는 조건뿐이라 걸러지지 않았다.
JUNK_TITLE_PATTERNS = [
    "에러", "오류", "error", "not found", "찾을 수 없", "존재하지 않", "삭제된",
    "로그인", "login", "접근", "권한", "차단", "점검", "준비 중", "준비중",
    "페이지를", "잘못된", "만료", "쇼핑몰 제목", "상품 상세", "네이버쇼핑",
]
# '○○ 스토어', '○○ 쇼핑몰'처럼 상품이 아니라 판매처 이름만 들어온 경우.
STORE_ONLY_RE = re.compile(r"^[^\s]{0,20}\s*(스토어|쇼핑몰|공식몰|store|mall|샵|shop)\s*$", re.I)


def looks_like_junk_title(title: str) -> bool:
    low = (title or "").strip().lower()
    if len(low) < 5:
        return True
    if any(pat in low for pat in JUNK_TITLE_PATTERNS):
        return True
    return bool(STORE_ONLY_RE.match(title.strip()))


def fetch_title(url: str, timeout: int = 10) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # [v7.7.0] 모바일 주소 우회를 뺐다. "스마트스토어는 데스크톱이 JS라
    #  모바일이면 된다"는 근거 없는 추측이었고, 실측에서 모바일도 똑같이
    #  막혔다. 남겨두면 실패할 요청을 한 번 더 보내 검증만 느려진다.
    #  실제로 어떤 방법이 되는지는 smartstore_probe.py로 측정한다.
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        html = res.read(300_000).decode("utf-8", errors="ignore")

    # 1순위: og:title (실제 상품명이 정확히 들어있는 경우가 많음, 사이트명 등 잡음 없음)
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.I)
    if m and m.group(1).strip():
        title = _strip_site_suffix(m.group(1).strip())
        return "" if looks_like_junk_title(title) else title

    # 2순위: <title> 태그(사이트명이 붙어있는 경우가 많아 뒤쪽 " - 몰이름" 등을 잘라냄)
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        title = _strip_site_suffix(m.group(1).strip())
        return "" if looks_like_junk_title(title) else title

    return ""


def _strip_site_suffix(title: str) -> str:
    """제목 끝에 붙은 사이트/몰 이름 부분을 제거한다. " | 몰이름", " - 몰이름",
    "- 후기 | 몰이름"처럼 구분자가 여러 개 겹쳐도, 마지막 구분자(| 우선,
    없으면 -) 뒤가 15자 이내로 짧으면 사이트명일 가능성이 높다고 보고 잘라낸다."""
    for sep in ("|", "-", ":"):
        if sep in title:
            *rest, last = title.rsplit(sep, 1)
            if last.strip() and len(last.strip()) <= 15:
                title = sep.join(rest).strip()
    return title.strip()


if __name__ == "__main__":
    url = sys.argv[1]
    try:
        print(fetch_title(url))
    except Exception as e:  # noqa: BLE001
        print("", file=sys.stdout)
        print(f"[fetch_page_title 실패] {type(e).__name__}: {e}", file=sys.stderr)
