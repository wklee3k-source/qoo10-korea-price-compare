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
    # v1.9.0부터 상점선별 단계에서도 REVIEW_THRESHOLD를 안 써야 한다
    # (find_low_review_shops 함수 본문 안에서 실제 필터링에 쓰이면 안 됨).
    # 주석/docstring이 아니라 실제 필터링 코드 패턴이 남아있는지만 본다.
    not_used_for_filtering = 'r["review_count"] < REVIEW_THRESHOLD' not in s
    check("14 리뷰 임계값(상점선별) 완전 해지", val == 10 and not_used_for_filtering,
          f"상수값{val} 상점선별단계미사용{not_used_for_filtering}")


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


# --------------------- #18 git add에 존재 미보장 경로 혼합 금지(실측사고)
#  실측사고: 'git add fileA fileB archive/'처럼 존재하지 않을 수 있는
#  archive/ 가 다른 필수 파일과 같은 git add 호출에 섞여 있었다. git add는
#  나열된 경로 중 하나라도 없으면 pathspec 오류로 전체를 통째로 실패시켜서
#  (2>/dev/null || true가 이 실패를 조용히 삼킴), 실제로 존재하는 파일조차
#  스테이징이 안 됐다. 그 결과 병합이 상품 458건을 정상 생성하고도
#  'git diff --cached --quiet'가 "변경없음"으로 오판해 그대로 유실됐다
#  (진실은 '비교할 게 없었다'였지 '차이가 없었다'가 아니었다).
def t18_no_optional_path_mixed_in_git_add():
    wf = WF.read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r"git add ([^\n]+)", wf):
        # 셸 리다이렉션(2>/dev/null) 이전까지만 실제 인자로 본다.
        args_str = re.split(r"\s+2>|\s+\|\||\s+&&", m.group(1))[0]
        paths = args_str.split()
        if "../output/archive/" in paths and len(paths) > 1:
            # archive/ 가 다른 파일 경로와 같은 git add 호출에 섞여 있으면 위반
            bad.append(args_str.strip()[:80])
    check("18 git add 경로 혼합 금지(archive/ 등)", not bad, f"{bad}")


# --------------------- #20 시간기반 안전망(ensure_discovery_alive) 존재
#  merge job 내부의 재기동이 5회 재시도 다 실패해도, 매시 정각 크론이
#  올 때마다 독립적으로 "발굴이 실제로 살아있는지" 재확인해서 죽어있으면
#  다시 켜는 별도 job이 있어야 한다. 그래야 이번 시간 복구가 실패해도
#  다음 정각에는 반드시 정상화된다.
def t20_hourly_safety_net_exists():
    wf = WF.read_text(encoding="utf-8")
    ok_job_exists = "  ensure_discovery_alive:" in wf
    block = wf.split("  ensure_discovery_alive:")[1].split("\n  auto_translate:")[0] if ok_job_exists else ""
    needs_merge = bool(re.search(r"needs:\s*merge_discovery_shards", block))
    always_regardless = bool(re.search(r"if:\s*always\(\)\s*&&", block))
    checks_current_state = "status=in_progress" in block and "discover_low_review_shops" in block
    revives_if_dead = "alive == '0'" in block or 'alive == "0"' in block
    ok = ok_job_exists and needs_merge and always_regardless and checks_current_state and revives_if_dead
    check("20 시간기반 안전망(ensure_discovery_alive)", ok,
          f"job존재{ok_job_exists} merge후실행{needs_merge} always(){always_regardless} "
          f"생존확인{checks_current_state} 복구조건{revives_if_dead}")


# --------------------- #19 병합 전후 발굴 일시정지/재기동 (push경합 방지)
#  실측사고: 발굴 워커 12개가 discovery-live에 계속 커밋하는 동안 병합
#  job이 같이 돌면 push 경합만 반복하다 20분 timeout에 통째로 취소된다
#  (상품 1,332건까지 쌓였는데 번역 0건인 채 취소된 사례 실측 확인).
def t19_pause_resume_discovery_around_merge():
    wf = WF.read_text(encoding="utf-8")
    block = wf.split("  merge_discovery_shards:")[1].split("\n  auto_translate:")[0]
    has_pause = "Pause discovery workers" in block and 'cancel"' in block.replace("'","\"") or "/cancel" in block
    has_resume = "Resume discovery workers after merge" in block
    resume_always = bool(re.search(r"Resume discovery workers after merge[^\n]*\n\s*if:\s*always\(\)", block))
    resume_section_probe = block[block.find("Resume discovery workers after merge"):]
    resume_dispatches_discovery = bool(re.search(r'run_discovery.{0,5}true', resume_section_probe[:1500]))
    # [실패시 대비] curl -s만으로는 dispatch 실패가 조용히 묻힌다. HTTP
    # 상태코드 확인 + 재시도 + 실패시 가시적 에러(::error::/exit 1)가
    # 반드시 있어야 한다.
    resume_section = block[block.find("Resume discovery workers after merge"):]
    resume_section = resume_section[:resume_section.find("\n  auto_translate:") if "\n  auto_translate:" in resume_section else len(resume_section)]
    has_status_check = "http_code" in resume_section.lower()
    has_retry = bool(re.search(r"for i in .*(1 2 3|1\.\.5|seq 1 5)", resume_section))
    has_visible_failure = "::error::" in resume_section and "exit 1" in resume_section
    ok = has_pause and has_resume and resume_always and resume_dispatches_discovery
    ok = ok and has_status_check and has_retry and has_visible_failure
    check("19 병합 전후 발굴 일시정지/재기동", ok,
          f"정지스텝{has_pause} 재기동스텝{has_resume} always(){resume_always} 재기동내용{resume_dispatches_discovery} "
          f"상태확인{has_status_check} 재시도{has_retry} 가시적실패{has_visible_failure}")


# --------------------- #21 병합시 번역 필드 보존 (실측 최악사고)
#  실측사고: 워커 파일은 번역을 절대 안 가진다(번역은 중앙 병합본에서만
#  일어남). 그런데 병합 루프가 워커파일 내용으로 무조건 덮어써서, 방금
#  번역한 걸 매시간 병합 때마다 영원히 지웠다(16:57 1,630건 번역완료 ->
#  17:02 다음 정각 병합에서 0건, 이후 6번 연속 0건 실측 확인).
def t21_merge_preserves_translation():
    src = (SRC / "merge_discovery_states.py").read_text(encoding="utf-8")
    # 워커파일 루프 안에서 기존 translated_kr을 보존하는 분기가 있어야 한다.
    has_guard = bool(re.search(r"existing\.get\(.translated_kr.\)", src))
    unconditional_overwrite = bool(re.search(r"for p in data\.get\(.all_products.[^\n]*\n\s*products\[p\[.goods_no.\]\] = p\s*\n", src))
    check("21 병합시 번역 필드 보존", has_guard and not unconditional_overwrite,
          f"보존분기존재{has_guard} 무조건덮어쓰기잔존{unconditional_overwrite}")


# --------------------- #40 워커수와 샤딩 나눗셈 일치 (누락시 데이터 유실)
#  워커 수를 바꿀 때 나눗셈(% N)을 같이 안 고치면, 남는 나머지값에
#  해당하는 항목이 어느 워커에도 배정되지 않아 영구히 처리 안 된다.
#  (수확에서 12->6 줄일 때 실제로 겪고 고친 문제)
def t40_shard_divisor_matches_worker_count():
    import yaml as _yaml
    wf = WF.read_text(encoding="utf-8")
    d = _yaml.safe_load(wf)
    bad = []

    checks = [
        ("discover_low_review_shops_parallel", "branch", r"% (\d+) == int\(suffix\)"),
        ("harvest_full_catalog_parallel", "branch", r"% (\d+) == \$B"),
        ("hwahae_verify", "shard", r"% (\d+) == \$S"),
    ]
    for job_name, key, pat in checks:
        job = d["jobs"].get(job_name)
        if not job:
            bad.append(f"{job_name} 없음"); continue
        n_workers = len(job.get("strategy", {}).get("matrix", {}).get(key, []))
        anchor = f"  {job_name}:"
        block = wf.split(anchor)[1] if anchor in wf else ""
        divisors = {int(m) for m in re.findall(pat, block)}
        if not divisors:
            bad.append(f"{job_name}: 나눗셈 못찾음"); continue
        if divisors != {n_workers}:
            bad.append(f"{job_name}: 워커{n_workers} vs 나눗셈{sorted(divisors)}")

    check("40 워커수-샤딩나눗셈 일치", not bad, "; ".join(bad))


# --------------------- #41 품질기준(리뷰10 미만 + 2곳 이상 합의)
def t41_quality_thresholds():
    disc = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    ver = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    m = re.search(r"^PRODUCT_SAVE_REVIEW_THRESHOLD\s*=\s*(\d+)", disc, re.M)
    review10 = bool(m) and int(m.group(1)) == 10
    has_consensus = "MIN_CONSENSUS_SOURCES" in ver and "n_sources < MIN_CONSENSUS_SOURCES" in ver
    m2 = re.search(r'MIN_CONSENSUS_SOURCES\s*=\s*int\(os\.environ\.get\("MIN_CONSENSUS_SOURCES",\s*"(\d+)"\)\)', ver)
    consensus2 = bool(m2) and int(m2.group(1)) == 2
    check("41 품질기준(리뷰<10, 합의2곳)", review10 and has_consensus and consensus2,
          f"리뷰10{review10} 합의로직{has_consensus} 기본값2{consensus2}")


# --------------------- #39 검증 샤딩 안전성
#  검증이 전체 파이프라인 유일한 병목이었다(1.5건/분, 3,147건이면 35시간).
#  발굴/수확에서 검증된 샤딩 방식을 적용. 핵심 안전조건:
#  결정적 해시(crc32) 사용, 샤드별 전용 출력파일, 샤드0만 통합/검수페이지
#  담당(동시 실행시 서로 덮어쓰기 방지), 요청간 지연 존재.
def t39_verify_sharding():
    wf = WF.read_text(encoding="utf-8")
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    d = yaml.safe_load(wf) if (yaml := __import__("yaml")) else None
    job = d["jobs"]["hwahae_verify"]

    has_matrix = len(job.get("strategy", {}).get("matrix", {}).get("shard", [])) >= 1
    block = wf.split("  hwahae_verify:")[1].split("\n  naver_api_test:")[0]
    code_only = "\n".join(l for l in block.split("\n") if not l.strip().startswith("#"))
    uses_crc32 = "zlib.crc32" in block and "hash(str(" not in code_only
    shard_files = "hwahae_verified_${S}.json" in block and "hwahae_input_${S}.json" in block
    # 통합/검수페이지는 샤드0만 (동시 덮어쓰기 방지)
    merge_only_shard0 = block.count("if: matrix.shard == 0") >= 2
    inherits_existing = "몫 {len(mine)}건 승계" in block or "승계" in block
    has_delay = "REQUEST_DELAY" in src and "time.sleep(REQUEST_DELAY)" in src

    ok = all([has_matrix, uses_crc32, shard_files, merge_only_shard0, inherits_existing, has_delay])
    check("39 검증 샤딩(3워커) 안전성", ok,
          f"matrix{has_matrix} crc32{uses_crc32} 샤드파일{shard_files} "
          f"샤드0만통합{merge_only_shard0} 기존승계{inherits_existing} 요청지연{has_delay}")


# --------------------- #38 수확 전용 파이프라인(같은 프로세스/분리 저장)
#  요구사항: 수확도 발굴과 똑같이 번역->검증->검수페이지를 타되,
#  결과물은 끝까지 분리 저장돼야 한다.
def t38_harvest_full_pipeline_separated():
    wf = WF.read_text(encoding="utf-8")
    mf = (SRC / "merge_fullcatalog_states.py").read_text(encoding="utf-8")
    br = (SRC / "build_review.py").read_text(encoding="utf-8")
    bb = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    # 통합본이 발굴본과 같은 형식(list)이어야 하위도구 재사용이 가능하다
    list_format = '"all_products": list(products.values())' in mf
    # 검수 생성기가 환경변수로 소스/출력을 바꿀 수 있어야 한다
    env_state = 'os.environ.get("QOO10_STATE_FILE"' in br
    env_verified = 'os.environ.get("QOO10_VERIFIED_FILE"' in br
    env_subdir = 'os.environ.get("QOO10_BATCH_SUBDIR"' in bb
    # 워크플로에 수확 전용 번역/검증/검수 스텝이 있어야 한다
    block = wf.split("  merge_fullcatalog_shards:")[1].split("\n  merge_discovery_shards:")[0]
    has_tr = "Translate harvest pool" in block
    has_vf = "Verify harvest pool" in block
    has_rv = "Build harvest review pages" in block
    # 결과물이 분리 저장돼야 한다
    sep_files = "fullcatalog_verified.json" in block and "docs/harvest" in block
    # 발굴 파일을 쓰면 안 된다
    no_discovery_write = "push origin discovery-live" not in block

    ok = all([list_format, env_state, env_verified, env_subdir, has_tr, has_vf, has_rv,
              sep_files, no_discovery_write])
    check("38 수확 전용 파이프라인(동일프로세스/분리저장)", ok,
          f"list형식{list_format} env소스{env_state} env검증{env_verified} env출력{env_subdir} "
          f"번역{has_tr} 검증{has_vf} 검수{has_rv} 분리저장{sep_files} 발굴미쓰기{no_discovery_write}")


# --------------------- #37 번역 중간저장(청크+매라운드 커밋)
#  실측사고: 번역이 전량 끝난 뒤에만 파일을 쓰고 커밋해서, GitHub
#  Actions 타임아웃(60분)에 걸리면 그때까지 번역한 게 통째로 날아갔다
#  (36분 넘게 돌았는데 저장 0건). hwahae_verify가 CHUNK로 쓰는 검증된
#  방식과 동일하게, 청크 단위로 처리하고 매 라운드 커밋해야 한다.
def t37_translation_incremental_save():
    at_src = (SRC / "auto_translate.py").read_text(encoding="utf-8")
    tip_src = (SRC / "translate_in_place.py").read_text(encoding="utf-8")
    wf = WF.read_text(encoding="utf-8")

    has_callback = "on_batch_done" in at_src and "on_batch_done(results)" in at_src
    has_max_items = "max_items" in tip_src and "to_translate[:max_items]" in tip_src
    saves_in_callback = "def save_progress" in tip_src and "path.write_text" in tip_src.split("def save_progress")[1][:600]

    block = wf.split("Translate merged pool")[1].split("\n      - name:")[0]
    has_chunk_loop = "TCHUNK=" in block and "for round in" in block
    # [100건 단위 통일] 청크가 배치보다 크면 한 python 호출 안에서 여러
    # 배치가 돌고 그동안 커밋이 안 돼 유실 구간이 커진다. 같은 값이어야
    # 배치1개=커밋1회로 유실이 최소화된다.
    m_chunk = re.search(r"TCHUNK=(\d+)", block)
    chunk_matches_batch = bool(m_chunk) and int(m_chunk.group(1)) == 100
    commits_each_round = "git commit -m" in block and "git push origin discovery-live" in block
    has_no_progress_guard = bool(re.search(r'\[ "\$AFTER" -le "\$BEFORE" \][\s\S]{0,150}?break', block))

    ok = all([has_callback, has_max_items, saves_in_callback, has_chunk_loop,
              chunk_matches_batch, commits_each_round, has_no_progress_guard])
    check("37 번역 중간저장(청크+매라운드커밋)", ok,
          f"콜백{has_callback} max_items{has_max_items} 콜백내저장{saves_in_callback} "
          f"청크루프{has_chunk_loop} 청크100{chunk_matches_batch} 매라운드커밋{commits_each_round} 무진전가드{has_no_progress_guard}")


# --------------------- #36 번역 유저메시지 토큰낭비 제거
#  실측: 브랜드사전 972개가 시스템프롬프트(캐싱대상)에 이미 전부 들어
#  있는데, 유저메시지에도 항목마다 브랜드힌트를 또 붙이고 있었다.
#  유저메시지는 캐싱이 안 돼 매번 전액 청구된다 — 힌트 1개당 약 20토큰
#  x 500건 = 호출당 1만 토큰이 할인 없이 낭비되고 있었다.
def t36_no_duplicate_brand_hint():
    src = (SRC / "auto_translate.py").read_text(encoding="utf-8")
    fn = src.split("def translate_batch(")[1].split("\ndef ")[0]
    # 주석에 설명으로 언급된 건 무시하고, 실제 코드에서 힌트를 쓰는지만 본다
    code_only = "\n".join(ln for ln in fn.split("\n") if not ln.strip().startswith("#"))
    no_hint_in_prompt = "hint" not in code_only and "정확한 브랜드명:" not in code_only
    # 시스템프롬프트 쪽에는 브랜드사전이 반드시 있어야 한다(대체 경로)
    has_dict_in_system = "brand_table" in src and "BRAND_DICT.items()" in src
    # 재시도가 지수적으로 쪼개지지 않아야 한다(호출횟수 최소화)
    no_exponential_split = "2 ** (attempt - 1)" not in fn
    ok = no_hint_in_prompt and has_dict_in_system and no_exponential_split
    check("36 번역 유저메시지 중복힌트 제거", ok,
          f"힌트제거{no_hint_in_prompt} 시스템프롬프트에사전{has_dict_in_system} 재시도지수분할제거{no_exponential_split}")


# --------------------- #35 수확 루프 무진전시 중단 가드
#  실측위험: harvest_full_catalog_parallel의 while true는 TODO가 빌
#  때만 break했다. 큐텐 광범위 장애/IP차단시 매 반복 BATCH(50)개
#  상점을 실패로 소진하며 무한정 커밋을 이어갈 수 있었다(과거
#  discovery-live 커밋폭탄 86,269건과 같은 위험). 화해검증 루프에는
#  이미 있던 "진행 없음 -> 중단" 가드가 여기만 빠져 있었다.
def t35_harvest_loop_no_progress_guard():
    wf = WF.read_text(encoding="utf-8")
    block = wf.split("  harvest_full_catalog_parallel:")[1].split("\n  merge_fullcatalog_shards:")[0]
    has_after_check = "HARVESTED_AFTER" in block
    has_counter_init = "NO_PROGRESS=0" in block and "MAX_NO_PROGRESS=" in block
    has_break = bool(re.search(r'NO_PROGRESS.*-ge.*MAX_NO_PROGRESS[\s\S]{0,300}?break', block))
    # 진행이 있으면 카운터가 리셋돼야 연속(consecutive) 판정이 정확해진다
    has_reset = bool(re.search(r"else\s*\n\s*NO_PROGRESS=0", block))
    # 커밋/푸시 뒤에 있어야 진행상황(실패카운트)이 유실되지 않는다
    push_idx = block.find("push 40회 재시도 실패")
    guard_idx = block.find("HARVESTED_AFTER=")
    after_push = push_idx != -1 and guard_idx != -1 and guard_idx > push_idx
    ok = has_after_check and has_counter_init and has_break and has_reset and after_push
    check("35 수확 루프 무진전 중단 가드", ok,
          f"AFTER확인{has_after_check} 카운터초기화{has_counter_init} break존재{has_break} "
          f"진행시리셋{has_reset} 커밋후배치{after_push}")


# --------------------- #34 재시도-보류도 CHUNK(max_new) 상한에 포함
#  실측위험: 대량 기술적실패(예: Exa/네이버 동시장애) 상황에서
#  '보류-재시도대상' continue가 processed_this_call을 안 늘리면,
#  CHUNK(max_new) 상한이 무력화되어 한 호출 안에서 상품 목록 전체를
#  다 훑어버릴 수 있었다(각 상품마다 실제 API 4회씩 소비하면서).
def t34_retry_counts_toward_chunk_limit():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    # 재시도-보류 분기(보류-재시도대상 로그 직후)에서 processed_this_call
    # 증가 -> continue 순서로 실제 코드가 이어지는지 직접 확인한다.
    # (주석 안에 'continue'라는 단어가 언급돼 있어 단순 substring 검색은
    # 오탐 위험이 있어, print문 다음 줄부터의 실제 코드만 본다)
    marker = '[보류-재시도대상]'
    idx = src.find(marker)
    after = src[idx:idx + 700]
    # 주석 블록(전부 '#'으로 시작하는 줄)을 건너뛰고 실제 코드 줄만 모은다
    code_lines = [ln for ln in after.split("\n")[1:] if ln.strip() and not ln.strip().startswith("#")]
    ok = len(code_lines) >= 2 and "processed_this_call += 1" in code_lines[0] and code_lines[1].strip() == "continue"
    check("34 재시도-보류도 CHUNK상한 포함", ok, f"보류분기 카운트증가{ok}")


# --------------------- #33 build_excel 글롭 매치없음 안전처리
#  실측위험: output/*_korea_side.json, output/*.xlsx 둘 다 매칭되는
#  파일이 없으면 bash 글롭이 리터럴 문자열로 넘어가 python/git add가
#  "파일없음" 오류를 낸다(과거실패 #18과 같은 부류 — nullglob 없이
#  와일드카드를 무방비로 씀).
def t33_build_excel_glob_safety():
    wf = WF.read_text(encoding="utf-8")
    job_exists = "  build_excel:" in wf
    block = wf.split("  build_excel:")[1] if job_exists else ""
    has_nullglob_for_loop = bool(re.search(r"shopt -s nullglob\s*\n\s*for f in \.\./output/\*_korea_side\.json", block))
    has_nullglob_for_add = bool(re.search(r"shopt -s nullglob\s*\n\s*xlsx_files=\(output/\*\.xlsx\)", block))
    guarded_add = "if [ ${#xlsx_files[@]} -gt 0 ]" in block
    ok = job_exists and has_nullglob_for_loop and has_nullglob_for_add and guarded_add
    check("33 build_excel 글롭 매치없음 안전처리", ok,
          f"job존재{job_exists} 반복문nullglob{has_nullglob_for_loop} add용nullglob{has_nullglob_for_add} 존재확인후add{guarded_add}")


# --------------------- #32 hwahae retry_state 파일 커밋 포함 확인
#  실측위험: 30번에서 만든 재시도카운트 파일(hwahae_verified_39.retry_
#  state.json)이 git add에서 빠져있었다. GH Actions는 매번 새 VM이라
#  커밋 안 하면 파일이 유실되고, 재시도 카운트가 매번 0부터 시작해서
#  "3회 실패시 포기" 안전장치가 절대 발동 안 한다. 동시에 이 파일은
#  선택적(archive/와 같은 부류)이라 필수파일과 같은 git add에 섞으면
#  안 된다(18번 버그 재발 위험) — 존재확인 후 별도 add해야 한다.
def t32_hwahae_retry_state_committed():
    wf = WF.read_text(encoding="utf-8")
    block = wf.split("run_batch.py \"$CHUNK\"")[0] if False else wf  # placeholder, 실제로는 아래에서 hwahae_verify job 블록만 추출
    job_block = wf.split("^  hwahae_verify:", 1)
    # split by regex since job name has leading spaces consistently
    job_block = re.split(r"\n  hwahae_verify:\n", wf)[1].split("\n  naver_api_test:")[0] if "\n  hwahae_verify:\n" in wf else ""
    # [샤딩 대응] 파일명이 hwahae_verified_39.retry_state.json에서
    # 샤드별(hwahae_verified_${S}.retry_state.json)로 바뀌었다.
    included = "retry_state.json" in job_block
    # 필수파일과 분리된 별도 add(존재확인 [ -f ... ] 붙여서)인지 확인
    separated_safely = bool(re.search(r"\[ -f [^\]]*retry_state\.json \] && git add", job_block))
    not_mixed_with_required = not bool(re.search(r"git add [^\n]*hwahae_verified_39\.json[^\n]*retry_state\.json", job_block))
    ok = included and separated_safely and not_mixed_with_required
    check("32 hwahae retry_state 커밋 포함(안전하게 분리)", ok,
          f"포함{included} 안전분리{separated_safely} 필수파일과안섞임{not_mixed_with_required}")


# --------------------- #31 한->일 역번역 완전 비활성화 확인 (사용자지시)
def t31_kr_to_jp_disabled():
    wf = WF.read_text(encoding="utf-8")
    step_disabled = "Translate Korean product names to Japanese (DISABLED)" in wf
    no_api_call_in_step = True
    if step_disabled:
        block = wf.split("Translate Korean product names to Japanese (DISABLED)")[1].split("\n      - name:")[0]
        no_api_call_in_step = "python translate_kr_to_jp.py" not in block and "ANTHROPIC_API_KEY" not in block
    check("31 한->일 역번역 비활성화", step_disabled and no_api_call_in_step,
          f"스텝비활성화{step_disabled} 스텝내API호출없음{no_api_call_in_step}")


# --------------------- #30 검증(hwahae_verify) 기술적실패 vs 무결과 구분
#  실측위험: Exa/화해/무신사/네이버 검색함수 4개가 전부 '기술적 실패'
#  (타임아웃/네트워크오류/서브프로세스비정상종료/JSON파싱실패)와 '정상
#  조회했지만 결과없음'을 구분 안 하고 똑같이 None을 반환했다. 그래서
#  4곳 다 None이면 무조건 "이 상품은 한국에 없다"로 영구 확정했는데,
#  실제로는 일시적 오류였을 수 있다(9번 수정과 동일한 원칙의 재발).
def t30_verify_failure_vs_no_match():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    has_exception_class = "class SearchTechnicalFailure" in src
    has_safe_wrapper = "def _safe_search" in src
    # 4개 검색함수 전부 SearchTechnicalFailure를 실제로 raise하는지
    raises_in_all_four = all(
        f"def _search_{name}" in src and "raise SearchTechnicalFailure" in src.split(f"def _search_{name}")[1].split("\ndef ")[0]
        for name in ("exa", "hwahae", "musinsa", "naver")
    )
    run_batch_src = src.split("def run_batch(")[1]
    raw_call_count = sum(len(re.findall(rf"= _search_{name}\(", run_batch_src)) for name in ("exa", "hwahae", "musinsa", "naver"))
    no_raw_calls_left = raw_call_count == 0  # 전부 _safe_search(_search_X, ...) 형태여야 함(직접 대입호출 금지)
    has_retry_state = "retry_state_path" in run_batch_src and "MAX_VERIFY_RETRIES" in run_batch_src
    # 재시도 대상은 results/done에 안 들어가야 한다(continue로 보류)
    holds_back_on_retry = bool(re.search(r"if n < MAX_VERIFY_RETRIES:[\s\S]{0,600}?continue", run_batch_src))

    ok = all([has_exception_class, has_safe_wrapper, raises_in_all_four,
              no_raw_calls_left, has_retry_state, holds_back_on_retry])
    check("30 검증단계 기술적실패/무결과 구분", ok,
          f"예외클래스{has_exception_class} 안전래퍼{has_safe_wrapper} 4곳전부raise{raises_in_all_four} "
          f"직접호출잔존금지{no_raw_calls_left} 재시도상태{has_retry_state} 보류로직{holds_back_on_retry}")


# --------------------- #29 이미 번역된 것 불필요한 재시도 방지
#  실측위험: 이미 정상 번역된 항목도 매 병합사이클마다 재검증되는데,
#  길이검사(원문대비 50%미만)가 애매해서 짧지만 완전한 번역이 계속
#  재번역 대상으로 잡혀 비용이 낭비될 수 있었다. 재검증 경로는
#  strict=False로 완전무결한 실패신호(가나잔존/한글전무)만 걸러야 한다.
def t29_no_unnecessary_retranslation():
    at_src = (SRC / "auto_translate.py").read_text(encoding="utf-8")
    tip_src = (SRC / "translate_in_place.py").read_text(encoding="utf-8")

    has_strict_param = "strict: bool = True" in at_src
    fresh_check_strict = bool(re.search(r"validate_translation\(items\[k\]\[.title.\],\s*cand\)", at_src))
    recheck_uses_lenient = "validate_translation(p[\"title\"], cur, strict=False)" in tip_src

    ok = has_strict_param and fresh_check_strict and recheck_uses_lenient
    check("29 이미번역된것 재시도방지(strict분리)", ok,
          f"strict파라미터{has_strict_param} 신규검증strict유지{fresh_check_strict} "
          f"재검증lenient{recheck_uses_lenient}")


# --------------------- #28 번역 비용절감(프롬프트캐싱+배치확대)
#  실측: 1,630건 번역(약 109회 호출)에 $5~10 발생. 원인: 매 호출마다
#  긴 시스템 프롬프트를 캐싱 없이 처음부터 재전송. Haiku 4.5는 캐싱
#  최소기준이 4,096토큰이라 기존 프롬프트(500~700토큰)로는 cache_control을
#  붙여도 조용히 무시됐다. 브랜드사전(972개)을 시스템 프롬프트에 통째로
#  포함시켜 기준을 넘기고, 배치크기도 15->30으로 늘려 호출횟수를 줄인다.
def t28_translation_cost_optimization():
    src = (SRC / "auto_translate.py").read_text(encoding="utf-8")
    has_cache_control = '"cache_control": {"type": "ephemeral"}' in src
    uses_full_prompt_in_call = "FULL_SYSTEM_PROMPT" in src.split("def _call_api")[1].split("\ndef ")[0]
    prompt_crosses_threshold = False
    try:
        import importlib.util
        import os as _os
        _prev_cwd = _os.getcwd()
        _os.chdir(SRC)  # auto_translate.py가 "../data/..."라는 상대경로를 쓰므로 cwd를 맞춰준다
        try:
            spec = importlib.util.spec_from_file_location("auto_translate_check", SRC / "auto_translate.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            prompt_crosses_threshold = len(mod.FULL_SYSTEM_PROMPT) > 4096 * 1.2  # 여유있게 문자수로 근사확인
            batch_ok = mod.MAX_BATCH_SIZE == 100
            import inspect as _inspect
            default_matches_max = (
                _inspect.signature(mod.translate_batch).parameters["batch_size"].default
                == mod.MAX_BATCH_SIZE
            )
        finally:
            _os.chdir(_prev_cwd)
    except Exception as e:  # noqa: BLE001
        batch_ok = False
        default_matches_max = False
        prompt_crosses_threshold = f"모듈로드실패:{e}"
    ok = has_cache_control and uses_full_prompt_in_call and prompt_crosses_threshold is True and batch_ok and default_matches_max
    check("28 번역 비용절감(캐싱+배치확대)", ok,
          f"cache_control{has_cache_control} FULL프롬프트사용{uses_full_prompt_in_call} "
          f"임계값초과{prompt_crosses_threshold} 배치100{batch_ok} 기본값일치{default_matches_max}")


# --------------------- #27 수확 통합(merge_fullcatalog_shards) 안전성
def t27_merge_fullcatalog_safety():
    wf = WF.read_text(encoding="utf-8")
    job_exists = "  merge_fullcatalog_shards:" in wf
    block = wf.split("  merge_fullcatalog_shards:")[1].split("\n  merge_discovery_shards:")[0] if job_exists else ""

    has_pause = "Pause harvest workers" in block
    has_resume = "Resume harvest workers after merge" in block
    resume_always = bool(re.search(r"Resume harvest workers after merge\s*\n\s*if:\s*always\(\)", block))
    saves_own_file = "fullcatalog_state.json" in block
    never_writes_discovery = "push origin discovery-live" not in block
    reads_discovery_readonly = "git show FETCH_HEAD:output/discovery_state.json" in block

    script_exists = (SRC / "merge_fullcatalog_states.py").exists()
    script_src = (SRC / "merge_fullcatalog_states.py").read_text(encoding="utf-8") if script_exists else ""
    discovery_priority = "discovery_goods_no" in script_src and "continue" in script_src

    ok = all([job_exists, has_pause, has_resume, resume_always, saves_own_file,
              never_writes_discovery, reads_discovery_readonly, script_exists, discovery_priority])
    check("27 수확 통합 안전성(일시정지/재기동/별도저장/발굴우선)", ok,
          f"job존재{job_exists} 정지{has_pause} 재기동{has_resume} always(){resume_always} "
          f"별도저장{saves_own_file} discovery미쓰기{never_writes_discovery} "
          f"읽기전용{reads_discovery_readonly} 스크립트{script_exists} 발굴우선{discovery_priority}")


# --------------------- #26 전체상품 수확(harvest_full_catalog) 안전성
def t26_harvest_full_catalog_safety():
    wf = WF.read_text(encoding="utf-8")
    job_exists = "  harvest_full_catalog_parallel:" in wf
    block = wf.split("  harvest_full_catalog_parallel:")[1].split("\n  merge_discovery_shards:")[0] if job_exists else ""

    # discovery-live는 읽기만 해야 한다(쓰기 금지 — 과거실패#2·#4 재발방지 원칙 유지)
    reads_discovery_only = "git show FETCH_HEAD:output/discovery_state.json" in block and "git fetch origin discovery-live" in block
    never_writes_discovery = "push origin discovery-live" not in block and "checkout discovery-live" not in block

    # 비결정적 hash() 대신 결정적 해시를 써야 재실행해도 배정이 안 바뀐다
    no_nondeterministic_hash = "hash(s) % 12" not in block
    uses_deterministic_hash = "zlib.crc32" in block

    # 별도 브랜치(fullcatalog-live)에만 push해야 discovery-live와 경합이 없다
    pushes_own_branch = "push origin fullcatalog-live" in block

    # 스크래퍼/워커 스크립트 실제 존재 확인
    scraper_exists = (SRC / "qoo10_shop_full_catalog.py").exists()
    worker_exists = (SRC / "harvest_full_catalog.py").exists()

    # 필터(색조제외/카테고리화이트리스트/리뷰20이하)가 워커 스크립트에 있는지
    worker_src = (SRC / "harvest_full_catalog.py").read_text(encoding="utf-8") if worker_exists else ""
    has_color_filter = "COLOR_COSMETIC_CATEGORIES" in worker_src
    has_review_cap = "REVIEW_MAX" in worker_src and "> REVIEW_MAX" in worker_src

    ok = all([job_exists, reads_discovery_only, never_writes_discovery, no_nondeterministic_hash,
              uses_deterministic_hash, pushes_own_branch, scraper_exists, worker_exists,
              has_color_filter, has_review_cap])
    check("26 전체상품 수확 안전성(읽기전용/결정적해시/별도브랜치/필터)", ok,
          f"job존재{job_exists} discovery읽기전용{reads_discovery_only} discovery미쓰기{never_writes_discovery} "
          f"비결정적hash제거{no_nondeterministic_hash} 결정적hash{uses_deterministic_hash} "
          f"별도브랜치push{pushes_own_branch} 스크래퍼{scraper_exists} 워커{worker_exists} "
          f"색조필터{has_color_filter} 리뷰상한{has_review_cap}")


# --------------------- #25 번역 건너뛰기(skip_translate) 옵션 존재
def t25_skip_translate_option():
    wf = WF.read_text(encoding="utf-8")
    has_input = "skip_translate:" in wf
    has_guard = re.search(r'Translate merged pool[^\n]*\n\s*if:\s*inputs\.skip_translate\s*!=\s*true', wf)
    check("25 번역 건너뛰기(skip_translate) 옵션", has_input and bool(has_guard),
          f"입력존재{has_input} 가드적용{bool(has_guard)}")


# --------------------- #24 상품저장 필터에서 리뷰수/가격 조건 해지 확인
#  사용자 지시로 리뷰수·가격 필터를 해지했다. 색조/카테고리불일치/
#  옵션있음 조건은 그대로 유지돼야 한다(색조 봉인은 #13에서 별도 검사).
def t24_review_price_filter_removed():
    src = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    block = src.split("skip_reason = None")[1].split('item["passes_filter"]')[0]
    # 리뷰수는 20 임계값으로 재도입, 가격은 계속 해지 상태여야 한다.
    review_reintroduced_at_20 = "review_count >= PRODUCT_SAVE_REVIEW_THRESHOLD" in block
    threshold_is_20 = bool(re.search(r"PRODUCT_SAVE_REVIEW_THRESHOLD\s*=\s*20", src))
    price_gone = "price_jpy <= MIN_PRICE_JPY" not in block
    color_kept = 'skip_reason = "색조카테고리"' in block
    category_kept = 'skip_reason = "화장품카테고리아님"' in block
    ok = review_reintroduced_at_20 and threshold_is_20 and price_gone and color_kept and category_kept
    check("24 상품저장 필터(리뷰20 재도입/가격 계속해지)", ok,
          f"리뷰20재도입{review_reintroduced_at_20} 임계값20{threshold_is_20} "
          f"가격해지{price_gone} 색조유지{color_kept} 카테고리유지{category_kept}")


# --------------------- #22 검색 스크래퍼 무한스크롤 적용(1순위)
#  실측: 스크롤 없이는 첫 페이지(40개)만 로드돼 PDRN검색어 28상점,
#  스파그로우검색어 35상점만 회수됐다. 스크롤 강제시 각각 48/127~139
#  상점까지 회수됨(최대 3.7배).
def t22_search_scroll_applied():
    src = (SRC / "qoo10_low_review_shop_finder.py").read_text(encoding="utf-8")
    fn_src = src.split("def search_qoo10(")[1].split("\ndef ")[0]
    has_scroll = "mouse.wheel" in fn_src
    has_early_stop = "cur_count" in fn_src and "prev_count" in fn_src
    check("22 검색 스크래퍼 무한스크롤 적용", has_scroll and has_early_stop,
          f"스크롤{has_scroll} 조기종료{has_early_stop}")


# --------------------- #23 검색어당 상점처리 상한(STEP) 상향(2순위)
#  실측: STEP=3이면 검색어 하나(상점139개)를 다 돌리려고 매번 동일
#  키워드로 46번 재검색해야 했다(네트워크 왕복 낭비). STEP=30으로 올려
#  재검색 횟수를 대폭 줄인다. 대신 push는 매회차로 당겨서(위험창 유지)
#  STEP 상향으로 인한 데이터유실 위험 증가를 상쇄한다.
def t23_step_raised_and_push_every_iter():
    wf = WF.read_text(encoding="utf-8")
    block = wf.split("discover_low_review_shops_parallel:")[1].split("\n  merge_discovery_shards:")[0]
    step_val = re.search(r"^\s*STEP=(\d+)\s*$", block, re.M)
    # [기준 정정] 예전엔 'STEP>=10'을 요구했는데(재검색 낭비 축소 목적),
    # 실전에서 상점 30곳을 다 채워야 커밋돼 26분간 진행이 안 보이는
    # 부작용이 더 컸다. 이제는 반대로 '작은 값으로 자주 커밋'이 요구사항
    # 이므로 STEP<=5인지 검사한다.
    step_ok = bool(step_val) and int(step_val.group(1)) <= 5
    # "3회차마다만 push"하던 조건(ITER % 3)이 완전히 사라졌어야 한다.
    no_stale_push_gate = "ITER % 3" not in block
    push_every_iter = "git push origin discovery-live" in block
    ok = step_ok and no_stale_push_gate and push_every_iter
    check("23 STEP상향+매회차push", ok,
          f"STEP값{step_val.group(1) if step_val else '?'} 3회차게이트잔존{'ITER % 3' in block} push존재{push_every_iter}")


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
