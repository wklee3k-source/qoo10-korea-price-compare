"""
hwahae_verify_batch.py

사전 준비된 (goods_no, 클로드가 번역한 한글 핵심어) 목록을 받아서, 각각을
화해(hwahae.co.kr)에 먼저 검색해 정식 브랜드+상품명+용량으로 검증한다
(1차). 화해가 매칭실패했거나 단종으로 나오면, 네이버쇼핑 검색 API로
보완 검색한다(2차) — 실측으로 화해가 놓친 케이스(매칭실패/단종/오매칭)를
네이버쇼핑이 대신 정확히 찾아내는 경우가 확인됐다.
GitHub Actions 백그라운드 실행을 염두에 두고 매 건마다 즉시 저장한다
(타임아웃 걸려도 이어서 진행 가능).

사용법:
    python hwahae_verify_batch.py <input.json> <output.json>
        input.json: [{"goods_no": "...", "translated_kr": "..."}, ...]
        output.json: [{"goods_no":..., "translated_kr":..., "brand":...,
                        "name":..., "source":"hwahae"|"naver", ...}, ...]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# 검색어에서 용량 표기("110ml", "1L" 등)를 제거하는 정규식 — 실측으로 확인된
# 근본원인: 화해 검색엔진은 "숫자+단위"가 섞인 검색어를 받으면 결과가 불안정해진다
# (예: "BERGAMO 24K 럭셔리 골드 앰플 110ml" 검색 → 완전 무관한 상품이 나옴,
#  같은 검색어에서 "110ml"만 뺀 "BERGAMO 24K 럭셔리 골드 앰플"은 항상 정답).
# 용량은 이미 known_volume 파라미터로 따로 전달하고 있으니 검색어엔 필요없다.
VOLUME_IN_QUERY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL|ml|g|L)\b")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")


def _correct_name_isolated(keyword: str, known_volume: str, known_brand: str = "") -> dict:
    """완전히 새 파이썬 서브프로세스에서 실행한다."""
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


def _naver_fallback(keyword: str) -> dict | None:
    """1차(화해)가 실패했거나 단종일 때 2차로 네이버쇼핑에서 찾는다.
    NAVER_CLIENT_ID/SECRET 환경변수가 없으면(로컬 샌드박스 등) 조용히
    건너뛴다 — openapi.naver.com은 GitHub Actions에서만 접근 가능함.

    [실측 이슈] 같은 검색어로 별도 스크립트를 직접 돌리면 결과가 나오는데
    이 배치 안에서 호출하면 이따금 total=0(빈 결과)이 오는 재현이 안 되는
    현상이 있었다 — 원인을 못 밝혀서, 우선 0건이면 짧게 대기 후 한 번 더
    시도하는 안전장치로 완화한다."""
    print(f"    [디버그] naver_fallback 호출됨, keyword={keyword!r} (len={len(keyword)})", file=sys.stderr)
    try:
        from naver_shop_search import search as naver_search

        items = naver_search(keyword, display=5)
        if not items:
            import time

            print("    [디버그] 0건 — 2초 대기 후 재시도", file=sys.stderr)
            time.sleep(2)
            items = naver_search(keyword, display=5)
        if not items:
            return None
        top = items[0]
        return {
            "brand": top.get("brand") or top.get("mallName"),
            "corrected": top["title"],
            "volume": "",
            "price": top.get("lprice"),
            "mall": top.get("mallName"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [네이버폴백 실패] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _exa_fallback(keyword: str) -> dict | None:
    """1차(화해)+2차(네이버) 둘 다 실패했을 때 3차로 Exa(의미기반 검색)를
    시도한다. 실측으로 확인됨: 오역이어도(예: "디스인탱글"→실제 "디스플린")
    의미로 이해해서 정답을 찾아낸다 — 순수 텍스트매칭인 화해/네이버가
    놓치는 케이스를 커버한다."""
    print(f"    [디버그] exa_fallback 호출됨, keyword={keyword!r}", file=sys.stderr)
    try:
        from exa_search import search as exa_search

        items = exa_search(keyword, num_results=3)
        if not items:
            return None
        top = items[0]
        return {
            "brand": None,
            "corrected": top["title"],
            "volume": "",
            "url": top.get("url"),
        }
    except Exception as e:  # noqa: BLE001
        print(f"    [Exa폴백 실패] {type(e).__name__}: {e}", file=sys.stderr)
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
        kw = VOLUME_IN_QUERY_RE.sub("", kw_raw).strip()  # 검색어에서 용량 제거(근본원인 수정)
        kw = BRACKET_RE.sub("", kw).strip()  # 괄호 부가정보("(총20매입)" 등)도 제거
        kw = re.sub(r"\s+", " ", kw)
        print(f"[1차-화해] {item['goods_no']}: {kw}" + (f" (용량:{known_volume})" if known_volume else "") + (f" (브랜드:{known_brand})" if known_brand else ""))
        r = _correct_name_isolated(kw, known_volume, known_brand)

        source = "hwahae"
        # 화해가 뭔가 찾았으면(단종이더라도) 그대로 채택하고 더 안 찾는다 —
        # "단종"이라는 것 자체가 화해가 정확히 그 상품을 인식했다는 뜻이니
        # 신뢰할 만한 정보다. 2차/3차는 화해가 아예 못 찾았을 때만 쓴다.
        needs_fallback = not r.get("corrected")
        if needs_fallback:
            reason = "매칭실패"
            print(f"    [1차 {reason}] -> 2차(네이버쇼핑)로 보완 검색")
            naver_r = _naver_fallback(kw)  # 정제된 검색어 사용(원본 전체는 너무 길어서 결과가 안 나옴)
            if naver_r:
                r = naver_r
                source = "naver"
            else:
                print("    [2차도 실패] -> 3차(Exa 의미기반검색)로 보완 검색")
                exa_r = _exa_fallback(kw_raw)  # Exa는 의미기반이라 원본 그대로 써도 됨
                if exa_r:
                    r = exa_r
                    source = "exa"
            # 셋 다 실패하면 원래 화해 결과(실패/단종 상태)를 그대로 유지

        entry = {
            "goods_no": item["goods_no"],
            "translated_kr": kw_raw,
            "brand": r.get("brand"),
            "name": r.get("corrected"),
            "volume": r.get("volume", ""),
            "source": source,
            "obsolete": r.get("obsolete"),
            "sale": r.get("sale"),
            "price": r.get("price"),
            "mall": r.get("mall"),
        }
        results.append(entry)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        processed_this_call += 1

        status = entry["name"] or "매칭실패(둘다)"
        print(f"    -> [{source}] {entry['brand']} {status}")

    print(f"\n[DONE] 이번 호출에서 {processed_this_call}건 처리, 누적 {len(results)}/{len(items)}건 -> {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    max_new = int(sys.argv[3]) if len(sys.argv) > 3 else None
    run_batch(sys.argv[1], sys.argv[2], max_new)
