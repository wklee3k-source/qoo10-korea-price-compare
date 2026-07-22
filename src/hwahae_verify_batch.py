"""
hwahae_verify_batch.py (v5 — API 호출 3회로 절감)

문제의식(사용자 지적): 이전 구조는 2차(Exa/화해/네이버 초기조회) 이후에
4차(화해 재확인)와 5차(네이버 구매정보)를 또 호출해서 상품 1건당 API를
최대 5번(Exa1+화해2+네이버2) 썼다. 화해와 네이버는 처음 조회할 때 이미
필요한 정보(단종여부/가격/사진/링크)를 전부 받아올 수 있으므로, 그걸 그대로
쓰면 재호출이 필요 없다.

새 구조(3회 호출):
    1차. 클로드 대충번역(입력 그대로)을
    2차. Exa / 화해 / 네이버 세 곳에 각각 1번씩만 검색 — 화해와 네이버는
         이 1번의 호출에서 단종여부/가격/사진/구매링크까지 전부 뽑아둔다.
    3차. known_brand/known_volume과의 일치도 + 소스간 합의(consensus)로
         점수를 매겨 가장 적합한 후보(확정 상품명+브랜드)를 선정하고,
         구매정보는 2차에서 이미 받아온 화해/네이버 데이터를 그대로 쓴다
         (재호출 없음).

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
PRODUCT_URL_PATTERNS = re.compile(
    r"goodsNo=|/goods/|/products?/|goodscode=|/vp/products/|/dp/|/item/|itemId="
)
GENERIC_TITLE_RE = re.compile(
    r"^\s*.{1,15}(공식\s*(홈페이지|스토어|사이트|쇼핑몰)?|브랜드관|메인|홈)\s*[|｜]?\s*.{0,10}$"
)
NEWS_DOMAIN_RE = re.compile(
    r"news\.|\.news|/news/|blog\.|\.blog|tistory\.com|brunch\.co\.kr|post\.naver|magazine|"
    r"donga\.com|chosun\.com|joongang|hani\.co\.kr|mk\.co\.kr|hankyung|edaily|yna\.co\.kr"
)
HEADLINE_SENTENCE_RE = re.compile(r"[다요]\s*,|[다요][!?]|하면|한다면")


def _clean_query(text: str) -> str:
    t = VOLUME_IN_QUERY_RE.sub("", text)
    t = BRACKET_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize_volume_ml(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"([\d.]+)\s*(mL|ml|g|L)", text)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2).lower()
    return num * 1000 if unit == "l" else num


def _search_exa(keyword: str) -> dict | None:
    """후보1: Exa 의미기반검색(원본 번역 그대로 검색)."""
    try:
        from exa_search import search as exa_search

        items = exa_search(keyword, num_results=5)
        if not items:
            return None

        def _is_bad(it: dict) -> bool:
            url = it.get("url") or ""
            title = it["title"]
            return bool(
                GENERIC_TITLE_RE.match(title) or NEWS_DOMAIN_RE.search(url) or HEADLINE_SENTENCE_RE.search(title)
            )

        candidates = [it for it in items if PRODUCT_URL_PATTERNS.search(it.get("url") or "") and not _is_bad(it)]
        if not candidates:
            candidates = [it for it in items if not _is_bad(it)]
        if not candidates:
            candidates = items
        title = candidates[0]["title"]
        cleaned = EXA_REVIEW_RE.sub("", title)
        cleaned = EXA_TAIL_RE.sub("", cleaned)
        cleaned = _clean_query(cleaned)
        return {"source": "exa", "name": cleaned, "brand": None, "volume": None, "raw_title": title}
    except Exception as e:  # noqa: BLE001
        print(f"    [Exa 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _search_hwahae(keyword: str, known_volume: str, known_brand: str) -> dict | None:
    """후보2: 화해 검색(원본 번역 그대로, 격리된 서브프로세스). 나중에
    재확인 호출을 안 해도 되도록, 필요한 정보(단종여부/가격/사진/링크)를
    이 1번의 호출에서 전부 뽑아둔다."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "hwahae_name_corrector.py"), keyword, known_volume, known_brand],
            capture_output=True,
            text=True,
            timeout=30,
        )
        r = json.loads(proc.stdout)
        if not r.get("corrected"):
            return None
        return {
            "source": "hwahae",
            "name": r.get("corrected"),
            "brand": r.get("brand"),
            "volume": r.get("volume"),
            "obsolete": r.get("obsolete"),
            "sale": r.get("sale"),
            "price": r.get("price"),
            "image_url": r.get("image_url"),
            "product_url": r.get("product_url"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [화해 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _search_naver(keyword: str, known_brand: str) -> dict | None:
    """후보3: 네이버쇼핑 검색(원본 번역 그대로). 나중에 별도 "구매정보"
    재호출을 안 해도 되도록, 이 1번의 호출에서 가격/링크/사진후보까지
    전부 뽑아둔다."""
    try:
        from naver_shop_search import search as naver_search

        items = naver_search(keyword, display=5, known_brand=known_brand)
        if not items:
            return None
        top = items[0]
        seen = set()
        image_candidates = []
        for it in items:
            img = it.get("image")
            if img and img not in seen:
                seen.add(img)
                image_candidates.append({"url": img, "mall": it.get("mallName"), "link": it.get("link")})
        return {
            "source": "naver",
            "name": top["title"],
            "brand": top.get("brand"),
            "volume": None,
            "price": top.get("lprice"),
            "mall": top.get("mallName"),
            "seller_trust": top.get("seller_trust"),
            "product_url": top.get("link"),
            "image_url": top.get("image"),
            "image_candidates": image_candidates,
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [네이버 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _score_candidate(cand: dict, known_brand: str, known_volume: str, others: list[dict]) -> float:
    """known_brand/known_volume 일치도 + 다른 소스와의 합의(consensus)로 점수를 매긴다."""
    score = 0.0
    cand_brand = (cand.get("brand") or "").lower()
    cand_name = (cand.get("name") or "").lower()

    if known_brand:
        kb = known_brand.lower()
        if kb in cand_brand:
            score += 3.0
        elif kb in cand_name:
            score += 1.5  # 브랜드 필드는 없지만 이름에 브랜드가 포함된 경우

    if known_volume:
        known_ml = _normalize_volume_ml(known_volume)
        cand_ml = _normalize_volume_ml(cand.get("volume") or cand_name)
        if known_ml is not None and cand_ml is not None and abs(known_ml - cand_ml) < 0.1:
            score += 2.0

    # 합의 보너스: 다른 소스가 비슷한 상품명을 냈으면(단어 겹침) 신뢰도 상승
    cand_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", cand_name))
    for other in others:
        other_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", (other.get("name") or "").lower()))
        overlap = len(cand_tokens & other_tokens)
        if overlap >= 2:
            score += 1.0

    # 화해 출처는 단종여부까지 알려주는 부가정보가 있어 약간의 기본 가중치를 준다
    if cand.get("source") == "hwahae":
        score += 0.5

    return score


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

        # 2차: 3곳에 각각 독립 검색(순차 호출이지만 서로 결과에 의존하지 않음 = 병렬 개념)
        cand_exa = _search_exa(kw_raw)
        cand_hwahae = _search_hwahae(kw_cleaned, known_volume, known_brand)
        cand_naver = _search_naver(kw_cleaned, known_brand)
        candidates = [c for c in [cand_exa, cand_hwahae, cand_naver] if c]

        if not candidates:
            print("    [전체실패] 3곳 다 못 찾음")
            entry = {
                "goods_no": item["goods_no"], "translated_kr": kw_raw, "winner_source": None,
                "brand": None, "name": None, "volume": "", "source": None, "obsolete": None,
                "sale": None, "price": None, "mall": None, "seller_trust": None,
                "product_url": None, "image_url": None, "image_candidates": [],
            }
            results.append(entry)
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            processed_this_call += 1
            continue

        # 3차: 점수화해서 최적 후보 선정
        scored = []
        for c in candidates:
            others = [o for o in candidates if o is not c]
            s = _score_candidate(c, known_brand, known_volume, others)
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        best_score, winner = scored[0]
        print(f"    [투표결과] " + " / ".join(f"{c['source']}={s:.1f}" for s, c in scored) + f" -> 승자: {winner['source']}")

        winner_name = winner.get("name") or ""
        winner_brand = winner.get("brand") or ""

        # (4차/5차 재확인 호출 제거 — 2차에서 이미 화해/네이버를 각각 1번씩
        # 호출하면서 필요한 정보를 전부 뽑아뒀으므로, 그 결과를 그대로 쓴다.
        # API 호출 수: Exa(1) + 화해(1) + 네이버(1) = 3회로 절감.)
        hwahae_data = cand_hwahae or {}
        naver_data = cand_naver or {}

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
            "winner_source": winner["source"],
            "candidates_summary": {c["source"]: c.get("name") for c in candidates},
            "brand": winner_brand or hwahae_data.get("brand"),
            "name": winner_name or hwahae_data.get("name"),
            "volume": winner.get("volume") or hwahae_data.get("volume") or "",
            "source": "hwahae+naver" if (cand_hwahae and cand_naver) else (winner["source"]),
            "obsolete": hwahae_data.get("obsolete"),
            "sale": hwahae_data.get("sale"),
            "price": naver_data.get("price") or hwahae_data.get("price"),
            "mall": naver_data.get("mall"),
            "seller_trust": naver_data.get("seller_trust"),
            "product_url": naver_data.get("product_url") or hwahae_data.get("product_url"),
            "image_url": naver_data.get("image_url") or hwahae_data.get("image_url"),
            "image_candidates": naver_data.get("image_candidates") or [],
        }
        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["name"] or "매칭실패"
        print(f"    -> [{entry['winner_source']}] {entry['brand']} {status}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
