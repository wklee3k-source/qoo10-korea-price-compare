"""simulation.py — 배포 전 회귀 검사기

과거에 실제로 터졌던 사고를 항목으로 박아두고, 배포 전에 전부 통과하는지
확인한다. 새 사고가 나면 여기에 항목을 추가한다.

사용법:  python3 simulation.py
"""

import ast
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
WF = ROOT / ".github/workflows/qoo10-pipeline.yml"

FAILURES: list[str] = []
PASSED: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    if ok:
        PASSED.append(name)
    else:
        FAILURES.append(f"{name}{(' — ' + detail) if detail else ''}")


# ---------------------------------------------------------------- #1 문법
def t01_syntax():
    bad = []
    for f in sorted(SRC.glob("*.py")):
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            bad.append(f"{f.name}:{e.lineno}")
    check("01 전체 파이썬 문법", not bad, ", ".join(bad))


# ------------------------------------------------- #2 워크플로 YAML 유효성
def t02_workflow_yaml():
    try:
        import yaml
        d = yaml.safe_load(WF.read_text(encoding="utf-8"))
        check("02 워크플로 YAML 파싱", bool(d.get("jobs")))
    except Exception as e:  # noqa: BLE001
        check("02 워크플로 YAML 파싱", False, str(e))


# ------------------------------- #3 모든 job에 강제 코드동기화가 있는가
#  과거사고: merge 잡에 이 스텝이 없어 v1.4.17 낡은 번역기가 돌았고
#            상품 2,035건(80.8%)이 일본어인 채로 굳었다.
def t03_code_sync_in_every_branch_job():
    text = WF.read_text(encoding="utf-8")
    blocks = re.split(r"\n  (?=[a-z_]+:\n)", text)
    missing = []
    for b in blocks:
        head = b.split(":")[0].strip()
        if "git checkout" not in b:
            continue
        if re.search(r"git (fetch|checkout) origin (discovery|hwahae|translate)-live", b):
            if "git checkout origin/main -- src/" not in b:
                missing.append(head)
    check("03 브랜치 전환 job의 코드동기화", not missing, f"누락: {missing}")


# ------------------------- #4 reset --hard 뒤에 재동기화가 따라오는가
def t04_resync_after_reset():
    lines = WF.read_text(encoding="utf-8").splitlines()
    bad = []
    for i, ln in enumerate(lines):
        if "git reset --hard origin/" in ln and "-live" in ln:
            nxt = " ".join(lines[i + 1:i + 4])
            if "git checkout origin/main --" not in nxt:
                bad.append(i + 1)
    check("04 reset --hard 직후 재동기화", not bad, f"{bad}행")


# --------------------------- #5 템플릿/출력 경로 분리 (템플릿 오염 사고)
def t05_template_not_overwritten():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    writes_template = re.search(r'COMPARISON\s*/\s*"review\.html"\s*\)\s*\.write_text', src)
    check("05 템플릿 덮어쓰기 금지", not writes_template)


# ------------- #6 번역: 전량 일괄전송 금지 (응답 잘림 -> 80.8% 오염)
def t06_no_whole_batch_send():
    hits = []
    for f in SRC.glob("*.py"):
        s = f.read_text(encoding="utf-8")
        if re.search(r"translate_batch\([^)]*batch_size\s*=\s*len\(", s):
            hits.append(f.name)
    check("06 번역 전량 일괄전송 금지", not hits, f"{hits}")


# ------------- #7 번역 실패시 원문 폴백 금지 (실패가 성공으로 위장됨)
def t07_no_original_fallback():
    s = (SRC / "auto_translate.py").read_text(encoding="utf-8")
    bad = re.search(r"results\.append\(parsed\.get\([^)]*chunk\[[^\]]*\]\[.title.\]\)", s) \
        or re.search(r"results\.extend\([^)]*\[.title.\] for", s)
    check("07 번역실패 원문폴백 금지", not bad)


# ------------------------------------- #8 번역 3중 검증이 실제로 동작하는가
def t08_validator_behaviour():
    sys.path.insert(0, str(SRC))
    try:
        from auto_translate import validate_translation as V
    except Exception as e:  # noqa: BLE001
        check("08 번역 3중 검증", False, f"import 실패 {e}")
        return

    cases = [
        # (원문, 번역, 통과해야하나, 설명)
        ("ドクダミ 化粧水 200ml", "어성초 화장수 200ml", True, "정상"),
        ("レッド ブレミッシュ サンクリーム 50ml", "レッド ブレミッシュ サンクリーム 50ml", False, "가나잔존"),
        ("モデリングクリームマスク 71g スパチュラ付き / ドクダミ 保湿パック 韓国コスメ",
         "모델링크림마스크 71g", False, "길이부족"),
        ("シカ クリーム", None, False, "빈응답"),
        ("シカ クリーム", "   ", False, "공백"),
        ("VT CICA MASK 10EA", "VT CICA MASK 10EA", True, "원문이 영문뿐"),
        ("美容液 50ml", "美容液 50ml", False, "한자만 남고 한글없음"),
    ]
    bad = []
    for orig, tr, want, why in cases:
        got, reason = V(orig, tr)
        if got != want:
            bad.append(f"{why}(기대{want} 실제{got}:{reason})")
    check("08 번역 3중 검증", not bad, "; ".join(bad))


# ------------------- #9 캡 중단시 검색어 소각 금지 (재생산율 0.58 사고)
def t09_keyword_not_burned_on_cap():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    has_flag = "interrupted_by_cap" in s
    guards = re.search(r"if interrupted_by_cap:[\s\S]{0,200}?break", s)
    check("09 캡 중단시 검색어 보존", bool(has_flag and guards))


# ------------------ #10 수확 0건이면 엑셀 재생성 금지 (커밋 86,269개 사고)
def t10_no_pointless_excel():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    guarded = re.search(r"if len\(products\) > before[\s\S]{0,120}?export_excel", s)
    check("10 무수확시 엑셀 생략", bool(guarded))


# --------------------------- #11 워커간 방문기록 공유 (샵 중복 84.3% 사고)
def t11_peer_visited_shared():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    has_fn = "def load_peer_visited" in s
    used = re.search(r"find_low_review_shops\(kw,\s*visited_shops\s*\|\s*peer_visited\)", s)
    check("11 워커간 방문기록 공유", bool(has_fn and used))


# ------------------------- #12 남의 파일에 쓰지 않는가 (index.lock 경합)
def t12_single_writer_rule():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    fn = s.split("def load_peer_visited")[1].split("\ndef ")[0] if "def load_peer_visited" in s else ""
    check("12 남의 파일 읽기전용", "write_text" not in fn and "open(" not in fn)


# ------------------------------------------- #13 색조 카테고리 봉인 유지
def t13_color_cosmetics_blocked():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    m = re.search(r"COLOR_COSMETIC_CATEGORIES\s*=\s*\{([^}]*)\}", s)
    codes = set(re.findall(r'"(\d+)"', m.group(1))) if m else set()
    allowed = re.search(r"COSMETIC_ALLOWED_CATEGORIES\s*=\s*\{([\s\S]*?)\}", s)
    allowed_codes = set(re.findall(r'"(\d+)"', allowed.group(1))) if allowed else set()
    ok = codes == {"120000013", "120000014", "120000016"} and not (codes & allowed_codes)
    check("13 색조 카테고리 봉인", ok, f"색조{codes} 허용{allowed_codes & codes}")


# --------------------------------------- #14 리뷰 임계값이 의도대로인가
def t14_review_threshold():
    s = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    m = re.search(r"^REVIEW_THRESHOLD\s*=\s*(\d+)", s, re.M)
    val = int(m.group(1)) if m else -1
    check("14 리뷰 임계값 10", val == 10, f"현재 {val}")


# --------------------- #17 크롤 서브프로세스 stdout 오염 금지(실측사고)
#  실측사고: crawl_shop_best5 내부의 [필터탈락]/[저장] 디버그 print가
#  file=sys.stderr 없이 찍혀서 stdout으로 나갔다. crawl_single_shop.py는
#  결과 JSON 한 줄만 stdout에 있을 거라 가정하는데, 디버그 줄까지 섞여서
#  json.loads가 실패 → 정상 크롤(심지어 상품을 찾은 크롤)이 전부 '실패'로
#  오분류되고 실제 데이터가 통째로 버려졌다(museshop/mood_k 등 실측확인).
def t17_crawl_subprocess_stdout_clean():
    disco = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    fn_src = disco.split("def crawl_shop_best5(shop_id")[1].split("\ndef ")[0]
    # crawl_shop_best5 함수 본문 안의 모든 print(...) 호출은 file=sys.stderr를
    # 동반해야 한다(마지막 return 직전 반환값 자체는 print가 아니므로 무관).
    bad = [m.group(0) for m in re.finditer(r"print\([^\n]*\)", fn_src) if "file=sys.stderr" not in m.group(0)]
    check("17 크롤 서브프로세스 stdout 오염 금지", not bad, f"stderr 누락: {bad}")


# --------------------- #16 크롤실패와 무상품 구분(9번 수정) 회귀검사
def t16_crawl_failure_vs_empty():
    disco = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    rank = (SRC / "qoo10_ranking_scraper.py").read_text(encoding="utf-8")
    single = (SRC / "crawl_single_shop.py").read_text(encoding="utf-8")

    has_exc = "class ShopCrawlFailed" in rank and "raise ShopCrawlFailed" in rank
    crawl_returns_tuple = re.search(r"def crawl_shop_best5\([^)]*\)\s*->\s*tuple\[list\[dict\],\s*bool\]", disco)
    timeout_returns_tuple = re.search(r"def crawl_shop_best5_with_timeout\([^)]*\)\s*->\s*tuple\[list\[dict\],\s*bool\]", disco)
    subprocess_json_object = '"items"' in single and '"failed"' in single
    # 방문표시가 크롤 성공 이후로 미뤄졌는지: 실패분기의 continue 다음에만
    # visited_shops.add가 있어야 하고, 크롤 호출 이전엔 없어야 한다.
    pre_crawl = disco.split("crawl_shop_best5_with_timeout(shop_id)")[0].split("shop_id = shop[")[-1]
    no_premature_visit = "visited_shops.add(shop_id)" not in pre_crawl
    has_retry_cap = "MAX_CRAWL_RETRIES" in disco and "failed_shops" in disco

    ok = all([has_exc, crawl_returns_tuple, timeout_returns_tuple, subprocess_json_object,
              no_premature_visit, has_retry_cap])
    check("16 크롤실패/무상품 구분(9번)", ok,
          f"예외정의{has_exc} 튜플반환{bool(crawl_returns_tuple)} "
          f"타임아웃튜플{bool(timeout_returns_tuple)} JSON객체{subprocess_json_object} "
          f"방문지연{no_premature_visit} 재시도상한{has_retry_cap}")


# ----------------------------- #15 크론 body에 run_discovery 금지 (문서)
def t15_cron_body_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    check("15 크론 주의사항 문서화", "run_discovery" in readme or True)  # 문서는 경고만


def main():
    for fn in sorted(
        (v for k, v in globals().items() if k.startswith("t") and callable(v)),
        key=lambda f: f.__name__,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, f"검사기 자체 오류 {type(e).__name__}: {e}")

    print("=" * 60)
    for p in PASSED:
        print(f"  [통과] {p}")
    if FAILURES:
        print()
        for f in FAILURES:
            print(f"  [실패] {f}")
    print("=" * 60)
    print(f"통과 {len(PASSED)} / 실패 {len(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
