"""
hwahae_verify_batch.py (v3 — 파이프라인 순서 재구성)

새 순서(사용자 제안 반영):
    1차. 클로드 대충번역(이미 완료된 translated_kr을 입력으로 받음)
    2차. Exa 의미기반검색으로 정교화 — 오역이어도 의미로 이해해서 정확한
         상품명 후보를 찾아준다(실측: 오역 그대로 검색해도 정답이 1등으로
         나옴). 이 결과를 "정교화된 검색어"로 정제해서 다음 단계에 넘긴다.
    3차. 화해에서 단종여부 확인 + 실제 정식 상품명/가격 확보
         (정교화된 검색어를 쓰니 기존보다 훨씬 정확하게 매칭될 것으로 기대)
    4차. 네이버쇼핑에서 브랜드+용량+수량이 정확히 일치하는 정규품만 필터링
         (화해가 못 찾았을 때의 최종 보완책)

GitHub Actions 백그라운드 실행을 염두에 두고 매 건마다 즉시 저장한다.

사용법:
    python hwahae_verify_batch.py <input.json> <output.json> [max_new]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

VOLUME_IN_QUERY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL|ml|g|L)\b")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")
EXA_TAIL_RE = re.compile(r"\s*[-|]\s*.+$")
EXA_REVIEW_RE = re.compile(r"\s*소비자평점.*$|\s*내돈내산.*$|\s*후기.*$")

# 실제 "상품 상세페이지" URL에서 흔히 보이는 패턴(한국 이커머스 공통) —
# 이런 패턴이 있으면 상품페이지일 확률이 높다고 판단한다.
PRODUCT_URL_PATTERNS = re.compile(
    r"goodsNo=|/goods/|/products?/|goodscode=|/vp/products/|/dp/|/item/|itemId="
)
# 브랜드 홈페이지/카테고리 페이지처럼 보이는 제목(구체적 상품명이 없는 경우) —
# 이런 게 1등으로 나오면 화해/네이버 재검색이 엉뚱한 결과로 샐 수 있어서 건너뛴다.
GENERIC_TITLE_RE = re.compile(
    r"^\s*.{1,15}(공식\s*(홈페이지|스토어|사이트|쇼핑몰)?|브랜드관|메인|홈)\s*[|｜]?\s*.{0,10}$"
)


def _clean_query(text: str) -> str:
    t = VOLUME_IN_QUERY_RE.sub("", text)
    t = BRACKET_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _exa_refine(keyword: str) -> str | None:
    """2차: Exa 의미기반검색으로 대충번역을 정교한 검색어로 다듬는다.
    브랜드 홈페이지/카테고리 페이지 같은 "상품이 아닌" 결과를 걸러내고
    실제 상품 상세페이지로 보이는 것을 우선 채택한다(실측: "은율 공식
    홈페이지" 같은 게 1등으로 나오면 재검색이 엉뚱한 곳으로 새는 문제가
    있었다)."""
    print(f"    [2차-Exa] 검색: {keyword!r}", file=sys.stderr)
    try:
        from exa_search import search as exa_search

        items = exa_search(keyword, num_results=5)
        if not items:
            return None

        # 1순위: URL이 상품상세 패턴이고, 제목도 일반 홈페이지 문구가 아닌 것
        candidates = [
            it for it in items
            if PRODUCT_URL_PATTERNS.search(it.get("url") or "") and not GENERIC_TITLE_RE.match(it["title"])
        ]
        if not candidates:
            # 2순위: 최소한 제목이 일반 홈페이지 문구는 아닌 것
            candidates = [it for it in items if not GENERIC_TITLE_RE.match(it["title"])]
        if not candidates:
            candidates = items  # 전부 걸러졌으면 그냥 1등 사용(완전 실패보다 나음)

        title = candidates[0]["title"]
        cleaned = EXA_REVIEW_RE.sub("", title)
        cleaned = EXA_TAIL_RE.sub("", cleaned)
        cleaned = _clean_query(cleaned)
        print(f"    [2차-Exa] 정교화됨: {title!r} -> {cleaned!r} (url={candidates[0].get('url')})", file=sys.stderr)
        return cleaned or None
    except Exception as e:  # noqa: BLE001
        print(f"    [2차-Exa 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _hwahae_verify(keyword: str, known_volume: str, known_brand: str) -> dict:
    """3차: 화해에서 단종여부 확인 + 실제 상품명/가격 확보(격리된 서브프로세스)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "hwahae_name_corrector.py"), keyword, known_volume, known_brand],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(proc.stdout)
    except Exception as e:  # noqa: BLE001
        return {"brand": None, "corrected": None, "volume": "", "_error": str(e)}


def _naver_strict_match(keyword: str, known_brand: str) -> dict | None:
    """4차: 화해가 못 찾았을 때, 네이버쇼핑에서 브랜드가 정확히 일치하는
    정규품만 골라낸다."""
    print(f"    [4차-네이버] keyword={keyword!r} known_brand={known_brand!r}", file=sys.stderr)
    try:
        from naver_shop_search import search as naver_search

        items = naver_search(keyword, display=5, known_brand=known_brand)
        if not items:
            import time

            time.sleep(2)
            items = naver_search(keyword, display=5, known_brand=known_brand)
        if not items:
            return None
        top = items[0]
        return {
            "brand": top.get("brand") or top.get("mallName"),
            "corrected": top["title"],
            "volume": "",
            "price": top.get("lprice"),
            "mall": top.get("mallName"),
            "seller_trust": top.get("seller_trust"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [4차-네이버 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def run_batch(input_path: str, output_path: str, max_new: int | None = None):
    items = json.loads(Path(input_path).read_text(encoding="utf-8"))

    out_path = Path(output_path)
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {r["goods_no"] for r in results}
    print(f"[INFO] 전체 {len(items)}건 중 이미 처리된 {len(done)}건부터 이어서 진행")

    processed_this_call = 0
    for item in items:
        if item["goods_no"] in done:
            continue
        if max_new is not None and processed_this_call >= max_new:
            print(f"[STOP] 이번 호출分({max_new}건) 처리 완료 — 나머지는 다음 호출에서 이어서")
            break

        kw_raw = item["translated_kr"]
        known_volume = item.get("volume", "")
        known_brand = item.get("known_brand", "")
        kw_cleaned = _clean_query(kw_raw)

        print(f"[상품] {item['goods_no']}: {kw_raw}")

        refined = _exa_refine(kw_raw) or kw_cleaned

        r = _hwahae_verify(refined, known_volume, known_brand)
        source = "hwahae"

        if not r.get("corrected"):
            print("    [3차-화해 실패] -> 4차(네이버) 시도")
            naver_r = _naver_strict_match(refined, known_brand)
            if naver_r:
                r = naver_r
                source = "naver"

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
            "exa_refined": refined,
            "brand": r.get("brand"),
            "name": r.get("corrected"),
            "volume": r.get("volume", ""),
            "source": source,
            "obsolete": r.get("obsolete"),
            "sale": r.get("sale"),
            "price": r.get("price"),
            "mall": r.get("mall"),
            "seller_trust": r.get("seller_trust"),
        }
        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["name"] or "매칭실패(전부)"
        print(f"    -> [{source}] {entry['brand']} {status}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
