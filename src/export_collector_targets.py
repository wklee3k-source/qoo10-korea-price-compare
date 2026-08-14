"""
export_collector_targets.py — 로컬 수집기(상품정보수집기.pyw)에 넘길
검색대상.json / 수집대상.json / 작업대상_통합.json 을 검증본 기준으로
자동 생성한다.

[왜 필요한가] 이전엔 검증본(hwahae_verified_*.json)을 보고 사람이(또는
클로드가 그때그때) 수동으로 검색어를 골랐다. candidates_summary에
블로그 글 제목·사이트 이름이 섞여 있는 걸 "가장 긴 후보"로 잘못 고르는
사고가 있었다(2026-08-13 실측: "추천하는 인기 콜라겐원료 10가지 필수
구매 가이드", "kiranavi" 같은 게 검색어로 들어감). 매번 사람이 다시
고치는 게 아니라 이 스크립트 하나로 고정해서 재발을 막는다.

분류 규칙
    product_url 있음                        -> 수집대상 (링크로 바로 열기)
    product_url 없음 + name 있음(2곳 합의)   -> 검색대상, query=name
    product_url 없음 + name 없음(합의부족)   -> 검색대상, query=아래 우선순위로 고름
        1) candidates_summary 를 소스 신뢰도 순으로 보되, 블로그성
           텍스트(따옴표·말줄임표·"가이드"·"추천"·"순위" 등)는 건너뜀
        2) 그래도 없으면 translated_kr 원문을 _clean_query(용량·괄호
           제거)로 다듬어 사용
    discovery_blocklist 에 있는 goods_no    -> 전부 제외

사용법:
    python export_collector_targets.py \
        <discovery_state.json> <hwahae_verified_dir> <discovery_blocklist.json> \
        <출력 디렉터리>

    hwahae_verified_dir 안의 hwahae_verified_*.json (샤드) 전부를 읽는다.
    출력: <출력 디렉터리>/검색대상.json, 수집대상.json, 작업대상_통합.json
"""
import glob
import json
import re
import sys
from pathlib import Path

VOLUME_IN_QUERY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL|ml|g|L)\b")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")

# candidates_summary 값이 실제 상품명이 아니라 블로그 글 제목·사이트
# 이름일 때 걸러내는 패턴. 완벽하지 않다 — 새 오탐 패턴이 나오면 여기에
# 추가할 것.
BLOGGY_RE = re.compile(
    r'[“”"…]|가이드|추천하는|상식|방법|후기 모음|랭킹|순위|top\s*\d|베스트\s*\d',
    re.IGNORECASE,
)

# 화해가 가장 신뢰도 높은 카탈로그 상품명(캐치프레이즈 없는 정식 제품명),
# 다음·네이버웹문서는 검색결과 페이지 제목을 그대로 주는 경우가 많아
# 마지막 순위로 둔다.
SOURCE_PRIORITY = ["hwahae", "musinsa", "naver_rematch", "naver_web", "daum"]


def _clean_query(text: str) -> str:
    t = VOLUME_IN_QUERY_RE.sub("", text)
    t = BRACKET_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _looks_bloggy(s: str) -> bool:
    if not s or len(s) < 3:
        return True
    return bool(BLOGGY_RE.search(s))


def _pick_candidate(cs: dict) -> str | None:
    for src in SOURCE_PRIORITY:
        val = cs.get(src)
        if val and not _looks_bloggy(val):
            return val
    for val in cs.values():
        if val and not _looks_bloggy(val):
            return val
    return None


def load_verified(verified_dir: str) -> dict:
    verified = {}
    for f in sorted(glob.glob(str(Path(verified_dir) / "hwahae_verified_*.json"))):
        try:
            rows = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows:
            g = r.get("goods_no")
            if g:
                verified[g] = r
    return verified


def build(state_path: str, verified_dir: str, blocklist_path: str, out_dir: str):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    products = {p["goods_no"]: p for p in state.get("all_products", [])}

    blocked_ids = set()
    bp = Path(blocklist_path)
    if bp.exists():
        bl = json.loads(bp.read_text(encoding="utf-8"))
        blocked_ids = {x["goods_no"] for x in bl.get("blocked", [])}

    verified = load_verified(verified_dir)

    collect_targets = []
    search_targets = []
    fallback_count = 0

    for gno, p in products.items():
        if gno in blocked_ids:
            continue
        if not p.get("translated_kr"):
            continue  # 아직 번역 안 된 건 대상 아님(export_untranslated.py 담당)
        v = verified.get(gno, {})

        if v.get("product_url"):
            collect_targets.append({"goods_no": gno, "url": v["product_url"]})
            continue

        if v.get("name"):
            search_targets.append({"goods_no": gno, "query": v["name"],
                                    "brand": v.get("brand") or ""})
            continue

        cs = v.get("candidates_summary", {}) or {}
        picked = _pick_candidate(cs)
        if picked:
            search_targets.append({"goods_no": gno, "query": picked,
                                    "brand": v.get("brand") or ""})
        else:
            cleaned = _clean_query(p["translated_kr"]) or p["translated_kr"]
            search_targets.append({"goods_no": gno, "query": cleaned, "brand": ""})
            fallback_count += 1

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "검색대상.json").write_text(
        json.dumps(search_targets, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "수집대상.json").write_text(
        json.dumps(collect_targets, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "작업대상_통합.json").write_text(
        json.dumps({"검색대상": search_targets, "수집대상": collect_targets},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    print(f"[완료] 수집대상 {len(collect_targets)}건 / 검색대상 {len(search_targets)}건 "
          f"(원문정제 대체 {fallback_count}건) -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("사용법: python export_collector_targets.py "
              "<discovery_state.json> <hwahae_verified_dir> "
              "<discovery_blocklist.json> <출력 디렉터리>")
        sys.exit(1)
    build(*sys.argv[1:5])
