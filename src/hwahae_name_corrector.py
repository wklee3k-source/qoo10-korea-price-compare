"""
hwahae_name_corrector.py

핵심문구(브랜드+상품명 추측 번역)를 화해(hwahae.co.kr)에서 검색해서
정확한 한글 정식 상품명으로 교정한다.

[배경] 일본어 원문을 사람이나 규칙으로 한글로 옮기면 발음/표기가 살짝
틀리는 경우가 많다(예: "톤업 퐁퐁 크림" ← 실제로는 "톤업 뽀용 크림").
화해는 실제 판매되는 한국 화장품의 정식 등록명을 갖고 있어서, 추측
번역이 조금 틀려도 검색만 되면 화면의 meta description에 정확한 상품명
목록이 노출된다 — 이걸 파싱해서 가장 근접한 항목을 정답으로 채택한다.

사용법:
    python hwahae_name_corrector.py "<추측 번역 검색어>"
"""

import json
import re
import sys
import time
import urllib.parse
from difflib import SequenceMatcher

from playwright.sync_api import sync_playwright

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# meta description은 "상품명1 가격1/상품명2 가격2/..." 형태다.
# 슬래시로 먼저 나누고, 각 조각 끝의 "숫자" 또는 "null"(가격)만 떼어낸다
# — 상품명 안의 대괄호에 숫자가 섞여 있어도(예: "[01 화이트]") 안전하다.
META_DESC_RE = re.compile(r'name="description" content="([^"]+)"')
TRAILING_PRICE_RE = re.compile(r'\s+(\d+|null)\s*$')


def _split_hwahae_names(desc: str) -> list[str]:
    names = []
    for piece in desc.split("/"):
        piece = piece.strip()
        piece = TRAILING_PRICE_RE.sub("", piece).strip()
        if piece:
            names.append(piece)
    return names


def search_hwahae_names(keyword: str, wait_seconds: float = 3.0) -> list[str]:
    url = f"https://www.hwahae.co.kr/search?q={urllib.parse.quote(keyword)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DESKTOP_UA, ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, timeout=15000, wait_until="load")
            time.sleep(wait_seconds)
            content = page.content()
        except Exception:  # noqa: BLE001
            content = ""
        browser.close()

    m = META_DESC_RE.search(content)
    if not m:
        return []
    desc = m.group(1)
    return _split_hwahae_names(desc)


def correct_name(guessed_keyword: str) -> dict:
    """추측 키워드를 검색해서 화해가 준 첫 번째 결과를 정답으로 채택한다.

    [실측으로 확인된 규칙] 처음엔 SequenceMatcher로 후보들을 재정렬해서
    가장 비슷한 걸 골랐는데, 오히려 정답을 밀어내는 경우가 더 많았다
    (6건 중 5건에서 화해가 준 0번째 후보가 이미 정답이었는데, 재정렬 후
    다른 후보가 뽑힘 — 브랜드명이 후보 텍스트에 없으면 문자열 유사도
    계산이 엉뚱하게 흔들리기 때문). 화해 자체의 검색순위가 이미 관련도
    기준으로 정렬되어 있어서, 그걸 그대로 믿는 게 더 정확했다."""
    candidates = search_hwahae_names(guessed_keyword)
    if not candidates:
        return {"guessed": guessed_keyword, "corrected": None, "confidence": 0.0, "all_candidates": []}

    best = candidates[0]  # 화해 자체 순위 1번째를 그대로 채택(재정렬 안 함)
    confidence = SequenceMatcher(None, guessed_keyword, best).ratio()  # 참고용 점수만 계산
    return {
        "guessed": guessed_keyword,
        "corrected": best,
        "confidence": round(confidence, 2),
        "all_candidates": candidates,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    result = correct_name(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
