"""
hwahae_verify_batch.py (v4 — 병렬탐색+투표 구조)

문제의식(사용자 지적): 이전 구조(클로드번역 -> Exa정교화 -> 화해 -> 네이버)는
순차 파이프라인이라 1단계(Exa)가 잘못 정교화하면 뒤(화해/네이버)까지 전부
틀어진다. 실제로 화해나 네이버가 클로드의 대충번역만으로 더 정확하게 찾는
경우도 많았다.

새 구조:
    1차. 클로드 대충번역(입력 그대로)을
    2차. Exa / 화해 / 네이버 세 곳에 각각 독립적으로(병렬 개념) 검색해서
         후보 3개를 모은다 — 한 곳이 틀려도 다른 곳이 살아있다.
    3차. known_brand/known_volume과의 일치도 + 소스간 합의(consensus)로
         점수를 매겨 가장 적합한 후보(확정 상품명+브랜드)를 선정한다.
    4차. 확정된 이름으로 화해에서 최종 단종여부를 확인한다.
    5차. 확정된 이름으로 네이버에서 실제 구매정보(사진/가격/링크/판매처)를
         가져온다(화해는 검증용일 뿐 구매처가 아니므로).

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
    """후보2: 화해 검색(원본 번역 그대로, 격리된 서브프로세스)."""
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
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [화해 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _search_naver(keyword: str, known_brand: str) -> dict | None:
    """후보3: 네이버쇼핑 검색(원본 번역 그대로)."""
    try:
        from naver_shop_search import search as naver_search

        items = naver_search(keyword, display=5, known_brand=known_brand)
        if not items:
            return None
        top = items[0]
        return {"source": "naver", "name": top["title"], "brand": top.get("brand"), "volume": None}
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
        confirmed_query = f"{winner_brand} {winner_name}".strip() or kw_cleaned

        # 4차: 확정된 이름으로 화해에서 최종 단종여부 확인
        print(f"    [4차-화해 재확인] {confirmed_query!r}")
        hwahae_final = _search_hwahae(confirmed_query, known_volume, known_brand) or {}
        # _search_hwahae는 매칭실패시 None을 반환하므로 원본 서브프로세스 결과를 다시 조회해 obsolete 등 상세를 얻는다
        try:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "hwahae_name_corrector.py"), confirmed_query, known_volume, known_brand],
                capture_output=True, text=True, timeout=30,
            )
            hwahae_raw = json.loads(proc.stdout)
        except Exception:  # noqa: BLE001
            hwahae_raw = {}

        # 5차: 확정된 이름으로 네이버에서 실구매정보 확보
        print(f"    [5차-네이버 구매정보] {confirmed_query!r}")
        naver_final = _search_naver_full(confirmed_query, known_brand)

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
            "winner_source": winner["source"],
            "candidates_summary": {c["source"]: c.get("name") for c in candidates},
            "brand": winner_brand or hwahae_raw.get("brand"),
            "name": winner_name or hwahae_raw.get("corrected"),
            "volume": winner.get("volume") or hwahae_raw.get("volume") or "",
            "source": "hwahae+naver" if naver_final else "winner_only",
            "obsolete": hwahae_raw.get("obsolete"),
            "sale": hwahae_raw.get("sale"),
            "price": (naver_final or {}).get("price"),
            "mall": (naver_final or {}).get("mall"),
            "seller_trust": (naver_final or {}).get("seller_trust"),
            "product_url": (naver_final or {}).get("product_url"),
            "image_url": (naver_final or {}).get("image_url"),
            "image_candidates": (naver_final or {}).get("image_candidates") or [],
        }
        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["name"] or "매칭실패"
        print(f"    -> [{entry['winner_source']}] {entry['brand']} {status}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


def _search_naver_full(keyword: str, known_brand: str) -> dict | None:
    """5차 전용: 네이버쇼핑에서 실구매정보(가격/링크/사진후보들)까지 전부 가져온다."""
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
        seen = set()
        candidates = []
        for it in items:
            img = it.get("image")
            if img and img not in seen:
                seen.add(img)
                candidates.append({"url": img, "mall": it.get("mallName"), "link": it.get("link")})
        return {
            "price": top.get("lprice"),
            "mall": top.get("mallName"),
            "seller_trust": top.get("seller_trust"),
            "product_url": top.get("link"),
            "image_url": top.get("image"),
            "image_candidates": candidates,
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [5차-네이버 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].strip() else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
