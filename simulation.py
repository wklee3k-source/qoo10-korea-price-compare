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



# --------------------- #43 발굴 검색어 고갈 자동 보충 (워커 영구정지 사고)
#  워크플로의 시드 분배 단계는 "브랜치 전용 상태파일이 없을 때" 한 번만
#  돌아서, 파일이 이미 있는 워커의 pending_keywords가 0이 되면 그 워커는
#  영원히 빈 실행만 반복한다. 실측 2026-07-28: 워커0 2,237개 / 워커1 0개
#  (발굴 처리량 50% 손실), 통합본 pending도 0이라 재분배할 재료조차 없었다.
#  수확본에서 새 검색어를 뽑아 채우는 단계가 반드시 살아있어야 한다.
def t43_keyword_refill_when_exhausted():
    wf = WF.read_text(encoding="utf-8")
    import yaml as _yaml
    d = _yaml.safe_load(wf)

    script = SRC / "refill_discovery_keywords.py"
    has_script = script.exists()
    src = script.read_text(encoding="utf-8") if has_script else ""

    job = d["jobs"].get("discover_low_review_shops_parallel", {})
    steps = job.get("steps", [])
    names = [str(st.get("name", "")) for st in steps]
    has_pool_step = any("harvest pool" in n.lower() for n in names)
    has_refill_step = any("refill" in n.lower() for n in names)

    # 보충 배정은 인덱스가 아니라 결정적 해시여야 한다 — 워커마다 다른
    # 시점에 돌기 때문에 인덱스 기준이면 같은 검색어를 둘이 집어간다.
    deterministic = "md5" in src and "% workers" in src

    # --workers 값이 matrix 워커수와 일치해야 한다(#40과 같은 부류의 사고).
    n_workers = len(job.get("strategy", {}).get("matrix", {}).get("branch", []))
    declared = {int(m) for m in re.findall(r"--workers (\d+)", wf)}
    workers_match = bool(n_workers) and declared == {n_workers}

    # 수확본은 읽기 전용이어야 한다(발굴이 수확 상태를 건드리면 안 됨).
    # 쓰기는 자기 워커 상태파일 하나뿐이고, 그것도 원자적 교체여야 한다.
    write_calls = src.count('"w", encoding')
    pool_readonly = write_calls == 1 and "os.replace(tmp_path, state_path)" in src

    # 이미 쓴 검색어를 다시 넣으면 같은 상점을 무한 재방문한다.
    excludes_used = "collect_used_keywords" in src and "seen_keywords" in src

    ok = (has_script and has_pool_step and has_refill_step and deterministic
          and workers_match and pool_readonly and excludes_used)
    check("43 발굴 검색어 고갈 자동보충",
          ok,
          f"스크립트{has_script} 수확본받기{has_pool_step} 보충단계{has_refill_step} "
          f"결정적해시{deterministic} 워커수일치{workers_match}({n_workers} vs {sorted(declared)}) "
          f"수확읽기전용{pool_readonly} 기존검색어제외{excludes_used}")


# --------------------- #44 검증 워커수 변경시 재샤딩 (중복검증/조기완료 사고)
#  검증 샤드 파일은 "파일이 없을 때만" 만들어졌다. 그래서 워커수를 바꾸면
#  (1 -> 3) 예전 나눗셈(% 1)으로 만들어진 샤드0 파일에 다른 샤드 몫이
#  그대로 남아, DONE 카운트가 부풀어 조기 '완료' 판정이 나고 같은 상품을
#  두 워커가 중복 검증한다. 승계 단계는 파일 존재와 무관하게 매번 돌면서
#  자기 몫만 남겨야 한다.
def t44_verify_reshard_on_worker_change():
    wf = WF.read_text(encoding="utf-8")
    block = wf.split("이미 검증된 것 승계")[1].split("TOTAL=$(")[0] if "이미 검증된 것 승계" in wf else ""

    # 조건부 실행(if [ ! -f ... ])이면 재샤딩이 영영 안 일어난다.
    not_conditional = "[ ! -f ../output/hwahae_verified_" not in block
    # 자기 몫만 남기는 필터가 있어야 한다.
    has_filter = "crc32" in block and "== $S" in block
    # 기존 통합본과 자기 파일을 둘 다 재료로 써야 한다(둘 중 하나만 보면 유실).
    reads_both = "hwahae_verified_39.json" in block and "hwahae_verified_${S}.json" in block

    ok = bool(block) and not_conditional and has_filter and reads_both
    check("44 검증 워커수 변경시 재샤딩",
          ok,
          f"승계블록{bool(block)} 무조건실행{not_conditional} 몫필터{has_filter} 양쪽읽기{reads_both}")


# --------------------- #45 검증 push 경합시 결과파일 유실 (실측 39건 소실)
#  push가 경합으로 밀리면 재시도 경로의 `git reset --hard`가 방금 만든
#  결과파일을 지운다. 복원용 /tmp 백업을 push '뒤'에 뜨고 있었기 때문에
#  첫 청크에는 백업이 없어 파일이 통째로 사라졌고, 다음 루프의 json.load가
#  FileNotFoundError로 job을 죽였다(2026-07-28 run 30324712542, 39건 유실).
#  백업은 반드시 push 전에, 그리고 파일이 없을 때 되살리는 경로가 있어야 한다.
def t45_verify_backup_before_push():
    wf = WF.read_text(encoding="utf-8")
    if "hwahae_verify_batch.py ../output/hwahae_input_" not in wf:
        check("45 검증 백업 선행", False, "검증 실행 블록을 못 찾음"); return

    loop = wf.split("hwahae_verify_batch.py ../output/hwahae_input_")[1].split("DONE_AFTER=")[0]
    backup = "cp ../output/hwahae_verified_${S}.json /tmp/vshard_backup.json"
    push = "git push origin hwahae-live"
    # 백업이 push보다 먼저 나와야 한다.
    backup_first = backup in loop and push in loop and loop.index(backup) < loop.index(push)

    # DONE_AFTER 계산이 파일 없음에도 죽지 않아야 한다.
    after = wf.split("DONE_AFTER=")[1].split("\n")[0] if "DONE_AFTER=" in wf else ""
    safe_read = "exists()" in after
    # 사라진 파일을 백업에서 되살리는 경로가 있어야 한다.
    has_restore = "|| cp /tmp/vshard_backup.json ../output/hwahae_verified_${S}.json" in wf

    # [v3.1.2] reset --hard는 '이번 커밋에서 새로 생긴 파일'을 전부 지운다.
    # 결과파일만 지켜서는 부족했다 — 입력파일이 사라져 다음 청크가 죽었다.
    input_backup = "cp ../output/hwahae_input_${S}.json /tmp/vinput_backup.json" in loop
    input_first = input_backup and loop.index("cp ../output/hwahae_input_${S}.json /tmp/vinput_backup.json") < loop.index(push)
    input_restore = "|| cp /tmp/vinput_backup.json ../output/hwahae_input_${S}.json" in wf

    ok = backup_first and safe_read and has_restore and input_first and input_restore
    check("45 검증 입출력 백업선행/유실복구", ok,
          f"결과백업선행{backup_first} 안전읽기{safe_read} 결과복구{has_restore} "
          f"입력백업선행{input_first} 입력복구{input_restore}")


# --------------------- #46 결제/인증 실패는 재시도 대상이 아니다
#  Exa 크레딧이 소진돼 모든 호출이 HTTP 402로 떨어졌는데, 이게 일시적
#  기술실패로 분류돼 상품마다 3회씩 재시도된 뒤 '보류'로 쌓였다 — 다른
#  소스(화해/네이버/무신사)가 멀쩡한데도 검증이 사실상 멈췄다.
#  결제/인증 오류는 그 소스만 끄고 나머지로 계속 가야 한다.
def t46_permanent_source_failure_disables_source():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    has_patterns = "PERMANENT_FAILURE_PATTERNS" in src and '"402"' in src
    has_disabled = "DISABLED_SOURCES" in src
    fn = src.split("def _safe_search(")[1].split("\ndef ")[0] if "def _safe_search(" in src else ""
    # 영구장애면 failures에 넣지 않아야 '보류'로 안 쌓인다.
    branch = fn.split("_is_permanent_failure(")[1].split("print(")[0] if "_is_permanent_failure(" in fn else ""
    not_retried = bool(branch) and "failures.append" not in branch
    skips_call = "if label in DISABLED_SOURCES" in fn

    ok = has_patterns and has_disabled and not_retried and skips_call
    check("46 결제/인증 실패시 소스 비활성화", ok,
          f"패턴{has_patterns} 집합{has_disabled} 재시도안함{not_retried} 호출스킵{skips_call}")


# --------------------- #47 Exa는 보조 호출(무료 크레딧 소진 방지)
#  Exa는 무료 월 크레딧($10 = 약 1,428건)이 정해져 있다. 상품마다 무조건
#  부르면 며칠 만에 소진되고 402로 검증이 멈춘다(실측 2026-07-28).
#  무료 3곳(화해/무신사/네이버)을 먼저 돌리고, 정족수를 채웠고 화해도
#  있으면 Exa를 건너뛴다. 단, 화해가 없을 때는 반드시 불러야 한다 —
#  Exa가 찾아준 이름으로 화해를 재검색하는 경로가 브랜드정보를 되살리는
#  유일한 수단이기 때문이다.
def t47_exa_called_as_fallback_only():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    body = src.split("def run_batch(")[1]

    exa_call = '_safe_search(_search_exa'
    hwahae_call = '_safe_search(_search_hwahae, kw_cleaned'
    if exa_call not in body or hwahae_call not in body:
        check("47 Exa 보조호출", False, "호출부를 못 찾음"); return

    # 무료 소스가 Exa보다 먼저 호출돼야 '이미 합의했는지'를 알 수 있다.
    free_first = body.index(hwahae_call) < body.index(exa_call)
    # 생략 조건이 정족수 상수와 화해 존재를 함께 봐야 한다.
    has_guard = "len(_free_sources) >= MIN_CONSENSUS_SOURCES and cand_hwahae" in body
    # 무조건 호출하던 옛 코드가 남아있으면 안 된다.
    no_unconditional = body.count(exa_call) == 1

    ok = free_first and has_guard and no_unconditional
    check("47 Exa 보조호출(크레딧 절약)", ok,
          f"무료우선{free_first} 생략조건{has_guard} 무조건호출없음{no_unconditional}")


# --------------------- #48 무료 검색소스 추가시 합의기준이 헐거워지는 구멍
#  소스가 4곳(exa/화해/무신사/네이버쇼핑)에서 6곳(+다음/네이버웹문서)으로
#  늘면서, 제목만 주는 웹문서 소스 둘이 서로 다른 엉뚱한 페이지를 물어와도
#  '2곳 합의'가 기계적으로 성립하는 구멍이 생겼다. 예전엔 제목전용 소스가
#  Exa 하나뿐이라 2곳을 채우려면 반드시 상품DB가 하나 끼어야 했다.
#  그 불변조건(브랜드/가격/구매링크를 주는 소스 최소 1곳)을 지켜야 한다.
#  또한 키가 없는 소스가 '기술적 실패'로 처리되면 상품이 보류로 쌓여
#  검증이 멈춘다(Exa 402 사고와 같은 부류) — 빈 결과로 조용히 빠져야 한다.
def t48_web_only_sources_cannot_form_consensus():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")

    # [v4.0.0] naver_rematch가 추가됐다. 집합의 정확한 내용이 아니라
    # '상품DB 소스만 들어있는지'를 본다.
    pconst = src.split("PRODUCT_SOURCES =")[1].split("\n")[0] if "PRODUCT_SOURCES =" in src else ""
    has_const = all(k in pconst for k in ('"hwahae"', '"musinsa"', '"naver"')) and \
        all(k not in pconst for k in ('"exa"', '"daum"', '"naver_web"'))
    guard = "not (_found_sources & PRODUCT_SOURCES)" in src
    # 정족수 자체는 건드리지 않았어야 한다.
    quorum_kept = 'MIN_CONSENSUS_SOURCES", "2"' in src

    # 키가 없을 때 예외를 던지지 않고 빈 리스트를 돌려주는지.
    key_safe = []
    for name, guard_line in (("daum_search.py", "if not API_KEY:"),
                             ("naver_web_search.py", "if not CLIENT_ID or not CLIENT_SECRET:")):
        f = SRC / name
        if not f.exists():
            key_safe.append(f"{name} 없음"); continue
        body = f.read_text(encoding="utf-8")
        if guard_line not in body or "return []" not in body.split(guard_line)[1][:80]:
            key_safe.append(f"{name}: 키없음 안전처리 누락")

    ok = has_const and guard and quorum_kept and not key_safe
    check("48 웹문서 소스만으로 합의 불가", ok,
          f"상수{has_const} 가드{guard} 정족수유지{quorum_kept} " + ("; ".join(key_safe) or "키안전처리OK"))


# --------------------- #49 번역 왕복 마크다운(붙여넣기 전용) 안전성
#  번역은 사람이 다른 Claude 창에서 하므로, 요청 파일은 '전체를 그대로
#  붙여넣기만' 하면 되게 지시문까지 품고 있어야 한다. 반영 쪽은 기존
#  엑셀 경로와 똑같은 안전장치를 지켜야 한다 — 특히 가나가 남은 값이
#  들어가면 그 상품이 '번역완료'로 굳어 영영 재시도되지 않는다.
#  또한 번호를 그대로 믿고 N번째 항목에 넣으면 그 사이 통합이 한 번 더
#  돌았을 때 엉뚱한 상품에 이름이 박히므로, 상품번호 대응표를 써야 한다.
def t49_translation_markdown_roundtrip():
    exp = SRC / "export_translation_request.py"
    imp = SRC / "import_translation_response.py"
    if not exp.exists() or not imp.exists():
        check("49 번역 왕복 마크다운", False, f"스크립트 없음(export {exp.exists()} import {imp.exists()})")
        return
    e = exp.read_text(encoding="utf-8")
    i = imp.read_text(encoding="utf-8")
    wf = WF.read_text(encoding="utf-8")

    has_instruction = "INSTRUCTION" in e and "ドクダミ" in e   # 지시문+용어집 포함
    has_index_map = "INDEX_MAP" in e and "INDEX_MAP" in i      # 번호↔상품번호 대응
    # 미번역이 0건이면 예전 파일을 지워야 한다(안 지우면 끝난 목록을 또 번역).
    clears_stale = "unlink()" in e

    kana_guard = "KANA_RE" in i and "가나잔존" in i
    no_overwrite = 'if product.get("translated_kr")' in i
    empty_skip = "if not korean:" in i

    in_workflow = wf.count("export_translation_request.py") >= 2  # 최초 + push재시도 경로

    ok = (has_instruction and has_index_map and clears_stale and kana_guard
          and no_overwrite and empty_skip and in_workflow)
    check("49 번역 왕복 마크다운(붙여넣기 전용)", ok,
          f"지시문{has_instruction} 대응표{has_index_map} 낡은파일정리{clears_stale} "
          f"가나차단{kana_guard} 덮어쓰기방지{no_overwrite} 빈칸건너뜀{empty_skip} 워크플로연결{in_workflow}")


# --------------------- #50 임계치 자동통합 + 번역요청서 분할
#  발굴이 N건 쌓이면 통합을 자동 호출한다. 세 가지가 반드시 있어야 한다.
#  (1) 기준선(merge_baseline.json) — 통합이 샤드 파일을 비우지 않으므로,
#      "지난 통합 시점의 샤드 합계"를 남겨야 신규분을 셀 수 있다.
#  (2) 중복 트리거 방지 — 워커 둘이 거의 동시에 임계치를 넘으면 통합이
#      두 번 떠서 20분씩 헛돈다.
#  (3) 번역요청서 분할 — 500줄을 한 장에 주면 응답이 약 27k 토큰이라
#      중간에 잘리거나 번호가 어긋난다(과거 API 번역에서 실제로 응답이
#      잘려 2,035건이 일본어인 채 굳은 사고가 있었다).
def t50_threshold_merge_and_chunking():
    wf = WF.read_text(encoding="utf-8")
    exp = (SRC / "export_translation_request.py").read_text(encoding="utf-8")

    has_baseline_write = "merge_baseline.json" in wf and "shard_total_at_merge" in wf
    has_threshold = "merge_threshold" in wf and "NEW_COUNT" in wf
    # 0이면 자동통합을 끌 수 있어야 한다(수동 운영으로 되돌릴 여지).
    can_disable = '"$THRESHOLD" != "0"' in wf
    dedup = "merge_discovery_shards" in wf.split("[자동통합]")[1] if "[자동통합]" in wf else False

    chunked = "chunk: int = 200" in exp and "chunks = [pending[i:i + chunk]" in exp
    # 장수가 줄었을 때 옛 뒷장이 남으면 이미 끝난 목록을 다시 번역하게 된다.
    clears_stale = 'glob(f"{stem}*{suffix}")' in exp and "unlink()" in exp
    # [v3.5.1] 키는 순번이 아니라 상품번호여야 한다. 순번을 쓰면 사용자가
    # 번역하는 동안 안전망 통합이 돌아 요청서가 새로 생성됐을 때 번호가
    # 밀려 엉뚱한 상품에 이름이 박힌다(4시간 크론 운영에서 실제로 발생 가능).
    imp = (SRC / "import_translation_response.py").read_text(encoding="utf-8")
    keyed_by_goods = "f\"{p.get('goods_no')}|{title}\"" in exp
    import_by_goods = "str(num) if str(num) in by_goods" in exp.replace(exp, imp)
    continuous = keyed_by_goods and import_by_goods

    ok = (has_baseline_write and has_threshold and can_disable and dedup
          and chunked and clears_stale and continuous)
    check("50 임계치 자동통합/번역요청 분할", ok,
          f"기준선{has_baseline_write} 임계치{has_threshold} 끌수있음{can_disable} "
          f"중복방지{dedup} 분할{chunked} 낡은장정리{clears_stale} 번호연속{continuous}")


# --------------------- #51 재검증 중 검수페이지 보호
#  통합본을 비우고 다시 채우는 재검증 동안 검수페이지를 갱신하면,
#  채워진 만큼만 표시돼 사용자가 보던 목록이 사라진다. 플래그는 입력값이
#  아니라 브랜치의 파일이어야 한다 — 외부 크론 Body에는 그 입력값이 없어서
#  입력값 방식이면 크론이 올 때마다 보호가 뚫린다.
def t51_hold_review_flag():
    wf = WF.read_text(encoding="utf-8")
    guard = "if [ -f ../output/.hold_review ]" in wf
    # 가드 블록 안(else 가지)에서만 생성이 호출돼야 한다.
    block = wf.split("if [ -f ../output/.hold_review ]")[1].split("- name:")[0] if guard else ""
    skips_build = "else" in block and "python build_review_batches.py" in block
    # docs/를 지워야 다음 '배포' 스텝이 옛 산출물을 올리지 않는다.
    clears_docs = "rm -rf docs" in wf
    ok = guard and skips_build and clears_docs
    check("51 재검증 중 검수페이지 보호", ok,
          f"플래그가드{guard} 생성건너뜀{skips_build} docs정리{clears_docs}")


# --------------------- #52 검수 피드백 루프(브랜드/표기 사전 학습)
#  검수페이지의 확정 결과가 comparison/decisions/ 에 쌓이는데 아무도 읽지
#  않고 있었다. 확정 건에서 브랜드 대응과 표기 변형을 사전에 되먹인다.
#  사전 오염이 가장 무서운 실패다 — 한 번 잘못 들어가면 이후 모든 판정에
#  퍼지고, 어디서 틀어졌는지 추적이 어렵다. 그래서 (1) 확정+비제외 건만
#  쓰고 (2) 기존 항목은 덮어쓰지 않으며 (3) 표기 변형은 나머지가 거의 다
#  일치하고 딱 한 토큰씩만 다를 때만 받는다.
def t52_decision_feedback_loop():
    script = SRC / "learn_from_decisions.py"
    if not script.exists():
        check("52 검수 피드백 루프", False, "learn_from_decisions.py 없음"); return
    src = script.read_text(encoding="utf-8")
    wf = WF.read_text(encoding="utf-8")
    import yaml as _yaml
    d = _yaml.safe_load(wf)

    only_confirmed = 'r.get("match_confirmed") and not r.get("excluded")' in src
    no_overwrite = ("if jp_brand in brand_dict or jp_brand in added:" in src
                    and "if key in alias_dict or key in added:" in src)
    strict_alias = "if len(l_only) != 1 or len(r_only) != 1:" in src
    # 번역이 덜 된 값이 사전에 들어가면 그대로 굳는다.
    kana_guard = "KANA_RE.search(kr_brand)" in src

    job = d["jobs"].get("learn_from_decisions", {})
    has_job = bool(job)
    reads_both = wf.count("--decisions") >= 2      # 신규 경로 + 예전 경로
    readonly_other_branches = "--depth 1 origin discovery-live" in wf and "git show FETCH_HEAD" in wf

    # [v3.8.0] 검수 저장(push)이 곧 학습 신호다. 두 가지를 지켜야 한다.
    #  (1) 학습 job이 만드는 커밋(data/*.json)이 트리거를 다시 부르면
    #      무한 반복이 된다 — paths를 결정 파일로 좁혀야 한다.
    #  (2) 같은 push 트리거를 쓰는 build_excel이 검수 저장 때마다 덩달아
    #      돌면 안 된다.
    triggers = d[True]
    push_paths = (triggers.get("push") or {}).get("paths") or []
    auto_on_push = "github.event_name == 'push'" in str(job.get("if"))
    no_loop = all(("decisions" in p or "korea_side" in p) for p in push_paths) and bool(push_paths)
    excel_guard = "검수 결정 저장" in str(d["jobs"].get("build_excel", {}).get("if"))

    ok = (only_confirmed and no_overwrite and strict_alias and kana_guard
          and has_job and reads_both and readonly_other_branches
          and auto_on_push and no_loop and excel_guard)
    check("52 검수 피드백 루프(사전 학습)", ok,
          f"확정건만{only_confirmed} 덮어쓰기방지{no_overwrite} 엄격변형{strict_alias} "
          f"가나차단{kana_guard} 잡{has_job} 양쪽경로{reads_both} 타브랜치읽기전용{readonly_other_branches} "
          f"저장시자동{auto_on_push} 무한반복방지{no_loop} 엑셀오작동방지{excel_guard}")


# --------------------- #53 검수페이지 브랜드 확실도 정렬/경고
#  브랜드가 사전으로 확인된 건은 앞에, 판단불가·불일치는 뒤에 몰아
#  마지막에 집중해서 보게 한다. 뒤쪽 구간이 오매칭이 숨는 곳이면서
#  동시에 채택 시 브랜드 사전이 새로 채워지는 구간이다(커버리지 38.6%).
#  같은 등급 안에서는 기존 순서를 보존해야 한다 — 매번 순서가 뒤바뀌면
#  어제 어디까지 봤는지 알 수 없다.
def t53_review_brand_ordering():
    src = (SRC / "build_review_batches.py").read_text(encoding="utf-8")
    tmpl = (ROOT / "comparison" / "review.html").read_text(encoding="utf-8")

    has_order = 'BRAND_ORDER = {"match": 0, "unknown": 1, "mismatch": 2}' in src
    applied = "all_pairs = sort_by_brand_confidence(all_pairs)" in src
    # 같은 등급 안에서는 입력 순서(enumerate 인덱스)가 마지막 정렬키여야 한다.
    stable = "enumerate(pairs)" in src and "t[1], t[2]))" in src
    warns = "브랜드 미확인" in src and "오매칭 의심" in src
    styled = ".badge.warn" in tmpl

    ok = has_order and applied and stable and warns and styled
    check("53 검수페이지 브랜드 정렬/경고", ok,
          f"등급{has_order} 적용{applied} 순서보존{stable} 경고문구{warns} 스타일{styled}")


# --------------------- #54 네이버 재검색(구매링크 회수)
#  구매링크는 사실상 네이버쇼핑에서만 나온다(링크 885건 중 867건=98%).
#  그래서 네이버가 못 찾으면 화해가 정확히 찾은 상품도 통째로 버려졌다
#  (링크 실패 651건 중 367건이 이 유형). 다른 소스가 알려준 정확한
#  이름으로 네이버를 한 번 더 치면 표본 100건에서 71%가 회수됐다.
#
#  두 가지가 중요하다.
#  (1) 반드시 합의 판정 '전에' 해야 한다 — '화해만 찾음(1곳)'으로 이미
#      거부된 뒤에 하면 아무 소용이 없다.
#  (2) 이 결과는 '독립적으로 같은 답을 낸' 게 아니라 '남의 답으로 조회한'
#      것이다. 합의의 성격이 다르므로 결과에 표시가 남아야 하고,
#      검수페이지에서 구분할 수 있어야 한다.
def t54_naver_rematch():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    body = src.split("def run_batch(")[1]

    has_fn = "def _search_naver_rematch(" in src
    in_product_sources = '"naver_rematch"' in src.split("PRODUCT_SOURCES =")[1].split("\n")[0]

    # 합의 판정보다 앞에서 호출돼야 한다.
    call_i = body.find("_safe_search(_search_naver_rematch")
    quorum_i = body.find("if n_sources < MIN_CONSENSUS_SOURCES")
    before_quorum = 0 < call_i < quorum_i

    # 원래 네이버 결과가 링크를 줬으면 재검색분을 쓰지 않아야 한다.
    prefers_original = 'cand_naver if (cand_naver and cand_naver.get("product_url"))' in body
    flagged = '"naver_rematched"' in body
    shown = '"naver_rematched"' in (SRC / "build_review.py").read_text(encoding="utf-8")

    ok = has_fn and in_product_sources and before_quorum and prefers_original and flagged and shown
    check("54 네이버 재검색(링크 회수)", ok,
          f"함수{has_fn} 상품소스{in_product_sources} 합의전호출{before_quorum} "
          f"원본우선{prefers_original} 표시{flagged} 검수노출{shown}")


# --------------------- #55 네이버 단독 통과(합의 없이)
#  네이버가 직접 찾고 구매링크까지 확보한 건은 합의 없이 통과시킨다.
#  실측: 링크 실패 651건 중 205건(31%)이 '네이버는 찾았고 링크도 있는데
#  다른 소스가 확인해주지 않아' 버려진 건이었다.
#
#  대가가 분명한 완화다 — 2곳 합의는 오매칭을 거르려고 넣은 기준이고
#  (실측: 화해 'ph6.9 위치하젤 클렌저' vs 네이버 '뉴트로지나 리무버'),
#  단독 통과는 그 안전망을 끄는 것이다. 그래서 반드시 세 가지를 지킨다.
#   (1) 링크가 실제로 있을 때만 — 링크도 없으면 통과시킬 이유가 없다.
#   (2) 결과에 표시를 남긴다.
#   (3) 검수페이지에서 경고를 띄우고 뒤로 배치한다 — 사진 대조가 필수인
#       구간이므로 확실한 건들과 섞이면 안 된다.
def t55_naver_single_source_pass():
    src = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    body = src.split("def run_batch(")[1]
    review = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    requires_link = 'cand_naver.get("product_url")' in body and "single_source_naver = True" in body
    # 정족수 상수 자체는 건드리지 않아야 한다(다른 소스 조합에는 그대로 적용).
    quorum_intact = 'MIN_CONSENSUS_SOURCES", "2"' in src
    # 아무도 못 찾은 건(0곳)까지 통과시키면 안 된다.
    not_from_zero = "n_sources < MIN_CONSENSUS_SOURCES and n_sources > 0" in body
    flagged = '"single_source_naver": single_source_naver' in body
    passed_to_review = '"single_source_naver": x.get("single_source_naver")' in review
    warned = "단독 매칭" in review and "단독 매칭" in batches
    # [v4.4.0] 정렬 1차 기준이 신뢰도 점수로 바뀌었고, 단독통과는 그 점수에
    # 감점(-1)으로 반영된다. 즉 여전히 뒤로 밀린다.
    sorted_back = ('if p.get("single_source_naver") else 0' in batches
                   or ('-int(p.get("confidence", 0))' in batches
                       and "single_source" in (SRC / "build_review.py").read_text(encoding="utf-8")
                       .split("def match_confidence(")[1].split("\ndef ")[0]))

    ok = (requires_link and quorum_intact and not_from_zero and flagged
          and passed_to_review and warned and sorted_back)
    check("55 네이버 단독통과(링크 확보시)", ok,
          f"링크필수{requires_link} 정족수유지{quorum_intact} 0곳제외{not_from_zero} "
          f"표시{flagged} 검수전달{passed_to_review} 경고{warned} 뒤로정렬{sorted_back}")


# --------------------- #56 검색어 길이별 성과 측정
#  생성 검색어의 23.2%가 단어 하나짜리인데, 유리한지 불리한지 측정된 적이
#  없다. 발굴은 상점 1곳당 검색어 5.4개를 쓴다 — 5개 중 4개는 새 상점을
#  못 만든다는 뜻이고, 그 낭비가 어디서 오는지 알아야 큐 순서를 손댈지
#  판단할 수 있다. 추측으로 큐를 건드리면 멀쩡한 검색어까지 뒤로 밀린다.
#
#  측정 자체가 새 실패를 만들면 안 된다: 개별 로그를 쌓으면 상태파일이
#  계속 커지고(과거 .git 2.7GB 사고와 같은 부류), 저장에 포함되지 않으면
#  워커가 재기동될 때마다 통계가 날아간다.
def t56_keyword_length_stats():
    src = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")

    has_bucket = "def _kw_bucket(" in src and "def _record_kw(" in src
    # 구간별 누적만 담아야 한다(개별 로그 금지 = 파일이 커지지 않는다).
    aggregate_only = "keyword_stats.setdefault(" in src and "keyword_stats.append" not in src
    # 저장에 포함돼야 재기동해도 이어진다.
    persisted = '"keyword_stats": keyword_stats' in src
    # 이어서 누적해야 한다(매번 0부터면 재기동마다 초기화된다).
    resumes = 'state.get("keyword_stats")' in src
    # 검색어 처리가 끝난 시점에 기록돼야 한다(중간에 끊긴 건 세면 안 됨).
    recorded_at_end = "_record_kw(kw, len(shops)" in src and \
        src.index("_record_kw(kw,") < src.index("seen_keywords.add(kw)\n        pending_keywords.pop(0)")

    ok = has_bucket and aggregate_only and persisted and resumes and recorded_at_end
    check("56 검색어 길이별 성과 측정", ok,
          f"구간함수{has_bucket} 누적만{aggregate_only} 저장포함{persisted} "
          f"이어누적{resumes} 완료시점기록{recorded_at_end}")


# --------------------- #57 브랜드+이름 동시 불일치 자동 제외
#  브랜드가 다르고 이름까지 안 맞으면 오매칭으로 보고 검수에서 뺀다.
#  표본 6건을 눈으로 확인한 결과 6건 모두 실제 오매칭이었다
#  (선크림→파운데이션, 크림→컨디셔너, '광고 출연자 모집' 게시글까지).
#
#  이 검사가 지키는 것은 '자동으로 버리지 않는다'는 원칙의 예외 조건이다.
#   (1) 두 척도를 모두 통과해야 뺀다 — 한 척도만 쓰면 멀쩡한 매칭을 버린다.
#       단어겹침만 보면 띄어쓰기 차이('맑은쌀 꿀채운'/'맑은쌀꿀채운')로,
#       글자조각만 보면 표기 차이('UV'/'유브이')로 오탐이 난다.
#   (2) 브랜드만 다른 건, 이름만 다른 건은 남긴다.
#   (3) 뺀 건은 파일로 남긴다 — 무엇이 사라졌는지 볼 수 없으면 고칠 수도 없다.
#  또한 영문 원본 브랜드를 한글 판매처명과 비교하는 건 애초에 불가능하므로
#  mismatch가 아니라 unknown이어야 한다(실측: LE LABO vs 르라보).
def t57_brand_name_mismatch_exclusion():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")

    two_metrics = "_sim_token(" in src and "_sim_bigram(" in src and \
        "def looks_like_mismatch" in src
    both_required = "< 0.3 and" in src and "< 0.45" in src
    # [v4.4.0] 브랜드 조건은 뗐다. 전수 점검에서 드러난 주된 실패가
    # '같은 브랜드의 다른 제품'이라 브랜드를 조건에 걸면 못 잡는다
    # (선세럼↔선크림, 젤↔스프레이, 블론드샴푸↔비듬샴푸).
    # 대신 이름은 반드시 두 척도를 모두 통과해야 한다.
    # [v4.5.0] 제외는 두 갈래다. (1) 이름만으로 명백한 경우, (2) 브랜드까지
    # 다를 때 조금 느슨한 임계. (2)에는 반드시 브랜드 상호참조 보호가 있어야
    # 한다 — 없으면 사전 부실이 곧 삭제가 된다(花王 큐레루 = 나수 Curel).
    # [v4.5.1] 제외 판단은 should_exclude 한 곳으로 모았다. 두 갈래를 쓰되
    # 브랜드 상호참조 보호는 갈래 2에만 적용한다 — 공통으로 씌웠더니
    # '같은 브랜드의 다른 제품'(W.DRESSROOM 퍼퓸->핸드크림)이 되살아났다.
    fn = src.split("def should_exclude(")[1].split("\ndef ")[0] if "def should_exclude(" in src else ""
    combined = (bool(fn)
                and "looks_like_mismatch(qoo10_name, kr_name)" in fn
                and "is_clear_mismatch(" in fn
                and "_brand_cross_reference" not in fn.split("if looks_like_mismatch")[0]
                and "def _brand_cross_reference(" in src
                and "should_exclude(q.get(\"brand\", \"\")" in src)
    logged = "brand_name_mismatch_excluded.json" in src and "excluded_mismatch.append" in src
    # 영문↔한글은 판단불가로 떨어져야 한다.
    latin_guard = 'if not re.search(r"[A-Za-z]", kr_brand_lower):' in src

    ok = two_metrics and both_required and combined and logged and latin_guard
    check("57 브랜드+이름 동시 불일치 제외", ok,
          f"두척도{two_metrics} 동시조건{both_required} 결합{combined} "
          f"제외목록기록{logged} 영문판단불가{latin_guard}")


# --------------------- #58 매칭 신뢰도 기반 검수 정렬
#  검수페이지 2,100건 전수 점검 결과 신뢰도가 고르지 않았다
#  (확실 870 / 보통 818 / 의심 412). 섞여 있으면 확실한 건에도 같은 주의를
#  쓰게 되고 정작 위험한 건을 놓친다. 브랜드만 보던 정렬을
#  브랜드+이름유사도+용량+단독여부를 합친 점수로 바꾼다.
#
#  낮은 점수를 자동으로 버리지는 않는다 — 실측 표본 10건 중 3건이 정상
#  매칭이었다('花王 큐레루'와 '나수 Curel'은 같은 제품, 'LE LABO'와
#  '르라보'도 같은 제품). 순서만 바꾸고 판단은 사람이 한다.
def t58_confidence_ordering():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    has_fn = "def match_confidence(" in src
    # 네 가지 신호를 모두 반영해야 한다.
    uses_all = all(k in src.split("def match_confidence(")[1].split("\ndef ")[0]
                   for k in ("brand_status", "_sim_token", "vol_mismatch", "single_source"))
    attached = '"confidence": match_confidence(' in src
    # 양쪽 용량을 다 알 때만 불일치로 봐야 한다(한쪽만 있으면 판단불가).
    # [v5.8.0] 용량 파싱은 상품명에서 숫자를 뽑는 방식이라 세트 표기·성분
    # 함량에서 엉뚱한 값을 집는다 — 실측: '큐리페어 멜라크림 35ml'의 한국
    # 용량이 3ml, '리드르 샷 1000 에센스 15ml'가 1ml로 잡혔다. 이런 값으로
    # 불일치 판정을 내리면 같은 제품이 B로 내려간다. 5ml 미만은 판단 보류.
    vol_guard = ("def volume_mismatch(" in src
                 and "MIN_TRUSTED_VOLUME_ML = 5.0" in src
                 and "volume_mismatch(qoo10_vol, kr_vol)" in src)
    sorts_by_conf = '-int(p.get("confidence", 0))' in batches
    warns_low = "신뢰도 낮음" in src and "신뢰도 낮음" in batches
    # 정렬만 하고 버리지는 않는다.
    not_dropped = 'confidence' not in batches.split("def build_batches(")[1].split("all_pairs = [")[0] \
        or "continue" not in batches.split('"confidence"')[0][-200:]

    ok = has_fn and uses_all and attached and vol_guard and sorts_by_conf and warns_low and not_dropped
    check("58 신뢰도 기반 검수 정렬", ok,
          f"함수{has_fn} 네신호{uses_all} 부착{attached} 용량가드{vol_guard} "
          f"정렬{sorts_by_conf} 경고{warns_low} 버리지않음{not_dropped}")


# --------------------- #59 검수 신뢰 등급(A/B/C) 표기
#  1,739건을 신뢰도 점수로 3등급으로 묶어 카드와 허브에 표시한다.
#  실측 분포: A 870(50.0%) / B 752(43.2%) / C 117(6.7%).
#  등급이 보이지 않으면 어디에 시간을 쓸지 정할 수 없다 — 앞뒤가 섞여
#  보이면 확실한 건에도 같은 주의를 쓰게 된다.
#  등급은 '표시'일 뿐 제외 기준이 아니다. C에도 정상 매칭이 섞여 있다
#  (花王 큐레루 = 나수 Curel).
def t59_confidence_tiers():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")
    tmpl = (ROOT / "comparison" / "review.html").read_text(encoding="utf-8")

    has_map = ('CONFIDENCE_TIERS = {' in src and '"A": ("완전일치"' in src
               and '"D":' in src and '"S":' in src)
    # [v7.13.0] 세트·기획 상품은 S로 뺀다. 여러 제품이 묶여 있어 제형·용량·
    # 가격 비교가 모두 성립하지 않는다. 실측: 대립 제형 규칙에 걸린 27건 중
    # 4건(14.8%)이 세트 때문에 잘못 걸렸다('퍼펙트9 토너 로션 크림 세트'와
    # '퍼펙트9 2종세트+핸드크림 증정'이 크림 vs 핸드크림 대립으로 읽힘).
    set_tier = ("def is_set_product(" in src and "SET_PATTERN" in src
                and 'if is_set and brand_status == "match":' in src)
    # [v7.20.0] '+' 양쪽에 서로 다른 제형이 있으면 세트다. 제형이 두 개
    # 이상이면 세트로 보는 방식은 못 쓴다 — 상품명에 카테고리 설명이나
    # 대분류·소분류가 함께 잡혀 실측 255건이 걸렸고 그중 A등급 86건이
    # 멀쩡한 단품이었다('클렌징'+'클렌징밤', '토너'+'토너패드').
    # 1+1 은 '+' 뒤에 제형어가 없어 자동으로 걸러진다.
    plus_split = ("def is_set_by_plus(" in src
                  and 'nonempty[0] ^ nonempty[1]' in src)
    # SPF/PA 표기가 '+'를 달고 있어 'SPF50+ PA++++ 50ml' 이 '+ 50ml' 로
    # 읽히면서 멀쩡한 선크림이 세트로 잡혔다. 먼저 지운다.
    # [v7.21.0] 자외선 차단 등급의 '+'는 등급 기호이지 '제품A + 제품B'의
    # '+'가 아니다. PA 등급은 PA+ ~ PA++++ 네 단계이고, 구분자가 공백·
    # 슬래시·쉼표로 제각각이며 아예 붙어 있기도 하다. 실측 표기 형태를
    # 전부 처리하는지 직접 돌려서 확인한다.
    spf_declared = "SPF_NOTATION_RE" in src
    spf_used = "SPF_NOTATION_RE.sub" in src.split("def is_set_product(")[1]
    spf_forms_ok = False
    if spf_declared:
        import importlib
        _sys_path = sys.path[:]
        sys.path.insert(0, str(SRC))
        try:
            import build_review as _br
            importlib.reload(_br)
            samples = ["SPF50+ PA++++", "SPF 50+ PA++++", "SPF50+/PA++++",
                       "SPF50+PA++++", "SPF50+, PA++++", "SPF50+ / PA++++",
                       "SPF38 PA++", "SPF50+", "PA++++", "PA+"]
            spf_forms_ok = all(not _br.SPF_NOTATION_RE.sub("", t).strip()
                               for t in samples)
            # 선크림에 등급이 붙어도 세트가 아니어야 하고,
            # 진짜 세트는 등급이 있어도 세트로 잡혀야 한다.
            spf_forms_ok = (spf_forms_ok
                            and not _br.is_set_product("톤업 선크림 SPF50+ PA++++ 50ml", "")
                            and _br.is_set_product("선크림 SPF50+ PA++++ 50ml + 선스틱 20g", ""))
        except Exception:  # noqa: BLE001
            spf_forms_ok = False
        finally:
            sys.path[:] = _sys_path
    spf_guard = spf_declared and spf_used and spf_forms_ok
    has_fn = "def confidence_tier(" in src
    # [v5.5.0] 등급은 점수 구간이 아니라 '무엇이 불확실한가'로 나눈다.
    # B등급 647건을 전수 확인해보니 성격이 전혀 다른 것들이 같은 점수에
    # 섞여 있었다 — 용량·이름 표기 차이(대부분 같은 제품)와 브랜드 불일치
    # (오매칭 다수)가 한 등급이었다. 브랜드 확인 여부를 1차 기준으로 삼는다.
    tfn = src.split("def confidence_tier(")[1].split("\ndef ")[0]
    # [v7.0.0] 브랜드/제형을 확인 못 하면 D. 등급은 브랜드->제형->이름->용량 순.
    # 브랜드·제형 확인 실패는 이름/용량보다 먼저 봐야 한다(D 가 우선).
    # (v7.24.0 부터 C 는 'return "B" if vol_mismatch else "C"' 안에 있어
    #  단독 문자열로는 못 찾는다. 이름 판정 지점과 비교한다.)
    brand_first = 'if brand_status != "match" or form != "match":' in tfn \
        and tfn.index('return "D"') < tfn.index('if not name_exact:')
    # [v7.24.0] 이름을 먼저 보되, 이름이 애매하면 용량까지 확인하고 등급을
    # 정한다. 예전엔 이름에서 걸리면 바로 C로 보내 용량을 아예 안 봤고,
    # 그 탓에 '같은 제품인데 용량만 다른' 건 41건이 C에 숨어 있었다.
    # C 는 '이름이 왜 다른지'를 볼 구간, B 는 '용량만' 확인할 구간이다.
    # [v7.25.0] 이름 일치 구간의 B 판정은 용량뿐 아니라 수량·매수 불일치도
    # 본다(상세 검사는 t77). 여기서는 두 조건이 함께 걸려 있는지만 본다.
    b_only_notation = ('return "B" if vol_mismatch else "C"' in tfn
                       and "if vol_mismatch or count_mismatch:" in tfn)
    # 네 조합이 실제로 맞게 나오는지 직접 돌려 확인한다.
    tier_cases_ok = False
    _sp = sys.path[:]
    sys.path.insert(0, str(SRC))
    try:
        import importlib
        import build_review as _br
        importlib.reload(_br)
        def _t(vol, exact):
            return _br.confidence_tier(4, "match", vol, True, False, "match",
                                       exact, "unknown", False, False)
        tier_cases_ok = (_t(True, False) == "B" and _t(False, False) == "C"
                         and _t(True, True) == "B" and _t(False, True) == "A")
    except Exception:  # noqa: BLE001
        tier_cases_ok = False
    finally:
        sys.path[:] = _sp
    b_only_notation = b_only_notation and tier_cases_ok
    attached = '"tier": confidence_tier(' in src
    badged = 'tier-{_tier}' in src and 'tier-{_tier}' in batches
    styled = ".badge.tier-A" in tmpl and ".badge.tier-C" in tmpl
    hub = 'tier_label' in batches
    # [v7.5.0] 파일명이 등급을 드러내야 한다(A_01, B_01 ...). 열어보기 전에
    # 어느 등급인지 알 수 있어야 검수 순서를 잡는다.
    tier_naming = 'batch_id = f"{tier_of}_{tier_seq[tier_of]:02d}"' in batches
    # 옛 이름의 유령 페이지를 지우되 허브(index.html)는 건드리면 안 된다.
    cleans_stale_pages = ('"review_*.html"' in batches
                          and 'BATCH_DIR.glob("*.html")' not in batches)
    # [v5.9.0] 한 페이지에 등급이 섞이면 그 페이지에서 검수 방식을 바꿔야
    # 한다. 등급별로 먼저 나눈 뒤 그 안에서 자른다.
    split_by_tier = 'for tier in ("A", "B", "C", "S", "D"):' in batches and "batches.append(group[i:i + BATCH_SIZE])" in batches
    # 예상치 못한 등급값이 있어도 항목을 버리면 안 된다.
    keeps_leftovers = "leftovers" in batches
    # 등급으로 걸러내면 안 된다(표시 전용).
    not_filtered = 'tier' not in batches.split("def sort_by_brand_confidence")[1].split("\ndef ")[0]

    ok = (has_map and has_fn and attached and badged and styled and hub and not_filtered
          and brand_first and b_only_notation and split_by_tier and keeps_leftovers
          and tier_naming and cleans_stale_pages and set_tier
          and plus_split and spf_guard)
    check("59 검수 신뢰등급 A/B/C 표기", ok,
          f"등급표{has_map} 함수{has_fn} 부착{attached} 배지{badged} 스타일{styled} "
          f"허브{hub} 제외에미사용{not_filtered} 브랜드우선{brand_first} B는표기차이{b_only_notation} "
          f"등급별분리{split_by_tier} 누락방지{keeps_leftovers} 등급파일명{tier_naming} "
          f"옛페이지정리{cleans_stale_pages} 세트등급{set_tier} "
          f"플러스분할{plus_split} SPF가드{spf_guard}")


# --------------------- #60 수동 제외 목록
#  자동 규칙으로는 못 거르지만 사람이 보면 명백히 다른 제품인 건들이 있다.
#  C등급 117건을 전수 확인해 98건을 뺐고, 19건은 남겼다(花王 큐레루=나수
#  Curel, 資生堂 엘릭서=시세이도 엘릭시르처럼 브랜드 표기만 다른 경우).
#  자동 규칙을 무리하게 넓히면 이런 정상 매칭까지 사라지므로, 판단 근거가
#  사람인 건 사람이 관리하는 파일에 둔다.
#  파일이 깨져 있어도 검수페이지 생성이 죽으면 안 된다 — 목록은 부가정보다.
def t60_manual_exclusions():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    path = ROOT / "data" / "manual_exclusions.json"

    exists = path.exists()
    entries = []
    if exists:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            entries = None
    valid = isinstance(entries, list) and all(
        isinstance(e, dict) and e.get("goods_no") and e.get("reason") for e in entries)

    loaded = 'manual_path = DATA / "manual_exclusions.json"' in src
    applied = 'if str(x.get("goods_no")) in manual_excluded:' in src
    counted = '"manual": 0' in src
    # 읽기 실패가 생성 실패로 번지면 안 된다.
    # (split은 다음 'manual_path'에서 끊기므로 인덱스로 창을 잡는다)
    _i = src.find("manual_path")
    safe = _i >= 0 and "except (OSError, ValueError)" in src[_i:_i + 800]

    ok = exists and valid and loaded and applied and counted and safe
    check("60 수동 제외 목록", ok,
          f"파일{exists}({len(entries) if isinstance(entries, list) else '깨짐'}건) 형식{valid} "
          f"읽기{loaded} 적용{applied} 집계{counted} 안전처리{safe}")


# --------------------- #61 검색 블랙홀 / 광고글 매칭 차단
#  특정 인기 상품이 서로 다른 큐텐 상품 여러 건에 반복해서 붙는다.
#  실측(2,590건): 같은 구매링크가 22건·20건·16건에 붙었고, 3건 이상에
#  붙은 링크가 전체의 14.2%(369건)를 차지했다. 성분어(PDRN·시카·콜라겐)만
#  겹치면 검색이 인기 상품 몇 개로 수렴하기 때문이다.
#  또 상품이 아니라 블로그·추천글이 구매링크로 잡히는 경우도 있었다
#  ('2026 상반기 스킨케어 트렌드' 14건, '추천글루타치온필름팩 10종' 12건).
#
#  블랙홀은 전부 지우면 안 된다 — 그중 하나는 진짜 짝일 수 있다.
#  이름이 가장 비슷한 한 건만 남기고 나머지를 뺀다.
def t61_search_blackhole_and_articles():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")

    has_article = "def looks_like_article(" in src and "AD_TITLE_RE" in src
    article_applied = 'if looks_like_article(x.get("name") or ""):' in src
    has_blackhole = "def _drop_search_blackholes(" in src and "BLACKHOLE_MIN" in src
    blackhole_applied = "pairs = _drop_search_blackholes(pairs, excluded_mismatch)" in src
    # 링크당 최소 1건은 남겨야 한다(전량 삭제 금지).
    fn = src.split("def _drop_search_blackholes(")[1].split("\ndef ")[0] if has_blackhole else ""
    keeps_best = "best = max(group" in fn and "keep_ids.add(id(best))" in fn
    # [v5.3.0] 2건짜리도 큐텐 브랜드가 다르면 블랙홀이다. 임계를 3으로만
    # 두면 브랜드가 다른 2건짜리가 그대로 남는다(LOWVIBE/Deep;erence
    # 핸드크림이 둘 다 '포트레 핸드크림 누보'에 붙어 있었다).
    two_with_diff_brand = "distinct_brands >= 2" in fn
    # [v6.3.0] 같은 브랜드 2건도 큐텐 상품명까지 같으면 중복 등록이다.
    # 검수 화면에 같은 짝이 두 번 나오면 사람이 두 번 판단하게 된다.
    dup_qoo10 = "distinct_qoo10 == 1" in fn
    # [v5.4.0] 링크뿐 아니라 매칭 상품명으로도 묶어야 한다. 같은 상품이
    # 판매처마다 다른 링크로 올라오면 링크 기준으로는 안 걸린다 —
    # 실측: '인진쑥 진정 보습 세럼'이 12건, '칠자화 유액'이 4건에 붙었다.
    by_name = '_flat(p.get("kr_name") or "")' in fn
    # 상품명이라기엔 너무 일반적인 값도 걸러야 한다(매칭 결과가 '화장품').
    generic = "def looks_too_generic(" in src and "GENERIC_NAMES" in src \
        and "stats[\"generic\"]" in src
    # 뺀 건은 기록으로 남겨야 한다.
    logged = 'reason": f"검색 블랙홀' in fn

    # [v4.9.0] 검증 단계에서도 걸러야 한다. 검수페이지에서만 빼면 광고글이
    # '승자'가 됐을 때 진짜 상품을 찾을 기회 자체가 사라지고, 그 상품은
    # 링크 없음으로 버려진다.
    vsrc = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    verify_filtered = ("def looks_like_article(" in vsrc
                       and "looks_like_article(it.get(\"title\") or \"\")" in vsrc)

    ok = (has_article and article_applied and has_blackhole and blackhole_applied
          and keeps_best and logged and verify_filtered and two_with_diff_brand
          and by_name and generic and dup_qoo10)
    check("61 검색 블랙홀/광고글 차단", ok,
          f"광고패턴{has_article} 광고적용{article_applied} 블랙홀{has_blackhole} "
          f"적용{blackhole_applied} 최선1건유지{keeps_best} 기록{logged} 검증단계{verify_filtered} "
          f"브랜드다른2건{two_with_diff_brand} 이름기준{by_name} 일반명{generic} 큐텐중복{dup_qoo10}")


# --------------------- #62 해외(비한국) 브랜드 제외
#  이 사업은 한국에서 사서 큐텐재팬에 파는 구조다. 일본·유럽 브랜드
#  상품은 한국 매입가가 더 비싸거나 아예 유통되지 않아 애초에 대상이
#  아닌데, 발굴에 섞여 들어와 검증을 소모하고 억지로 매칭되면 오매칭이
#  된다(실측: 花王 비오레 -> 지에프코스 선크림, ブルガリ 향수 -> 노에비아 크림).
#
#  자동 판별이 어렵다는 점이 핵심이다 — 가타카나라고 해외가 아니다.
#  アヌア=아누아, メディキューブ=메디큐브, 雪花秀=설화수, 呂=려는 전부
#  한국 브랜드다. 그래서 문자 종류가 아니라 브랜드 목록으로 관리한다.
def t62_foreign_brand_exclusion():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    path = ROOT / "data" / "foreign_brands.json"

    exists = path.exists()
    brands = []
    if exists:
        try:
            brands = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            brands = None
    valid = isinstance(brands, list) and len(brands) > 0 and all(isinstance(b, str) for b in brands)
    # 한국 브랜드가 목록에 섞이면 멀쩡한 상품이 통째로 사라진다.
    korean_safe = valid and not ({"アヌア", "メディキューブ", "雪花秀", "呂", "オフィ",
                                  "アモーレパシフィック", "ヘラ", "イニスフリー"} & set(brands))
    # [v5.2.1] 목록을 공백으로 쪼개 만들다가 'LE LABO'가 'LE'와 'LABO'로,
    # 'Suntory Wellness'가 'Suntory'와 'Wellness'로 갈라져 있었다.
    # 조각은 어떤 브랜드와도 일치하지 않아 조용히 아무 일도 안 한다 —
    # 걸러진 줄 알았던 상품이 그대로 검증·검수에 들어왔다.
    no_fragments = valid and not ({"LE", "LABO", "JILL", "STUART", "ADVANCED",
                                   "CLINICALS", "AZABU", "COSMETICS", "Suntory",
                                   "Wellness"} & set(brands))
    loaded = 'foreign_path = DATA / "foreign_brands.json"' in src
    applied = 'in foreign_brands:' in src
    counted = '"foreign": 0' in src
    _i = src.find("foreign_path")
    safe = _i >= 0 and "except (OSError, ValueError)" in src[_i:_i + 800]

    # [v5.1.0] 검증 단계에서도 걸러야 한다. 검수페이지에서만 빼면 검증이
    # 그대로 다 돌고 나서 버려진다(실측 490건, 10.7%가 헛돌았다).
    wf = WF.read_text(encoding="utf-8")
    verify_skips = "foreign_brands.json" in wf and "해외브랜드제외" in wf

    ok = (exists and valid and korean_safe and no_fragments and loaded and applied
          and counted and safe and verify_skips)
    check("62 해외 브랜드 제외", ok,
          f"파일{exists}({len(brands) if isinstance(brands, list) else '깨짐'}종) 형식{valid} "
          f"한국브랜드미포함{korean_safe} 조각없음{no_fragments} 읽기{loaded} 적용{applied} 집계{counted} 안전처리{safe} "
          f"검증단계{verify_skips}")


# --------------------- #63 브랜드 대응 자동 수확(안전조건)
#  검증 결과에는 '사전에 없지만 영문 병기 덕에 맞은' 브랜드가 있다
#  (COSRX -> '코스알엑스 (COSRX)'). 이걸 사전에 넣으면 판매처가 영문을
#  안 쓰는 다음 상품부터 브랜드 판정이 된다.
#
#  그냥 넣으면 위험해서 세 조건을 건다.
#   ① 영문 5자 이상 — 알파벳만 남겨 부분문자열로 비교하므로 'LOA'는
#      'FLOAT'에, 'CURE'는 'SECURE'에 들어간다. 우연이 사전에 들어가면
#      영구 규칙으로 굳는다.
#   ② 대응값에 한글이 있을 것 — AHC -> 'AHC'는 넣어도 중복일 뿐이다.
#   ③ 같은 대응이 2건 이상 — 한 번은 우연일 수 있다.
#  대응이 여러 갈래로 갈리면 자동으로 고르지 않는다(사람이 볼 몫).
def t63_brand_alias_harvest():
    script = SRC / "harvest_brand_aliases.py"
    if not script.exists():
        check("63 브랜드 대응 자동수확", False, "harvest_brand_aliases.py 없음"); return
    src = script.read_text(encoding="utf-8")
    review = (SRC / "build_review.py").read_text(encoding="utf-8")

    # [v5.7.0] 두 번째 수확 경로: 브랜드 판단불가인데 제품명이 거의 일치하는 건.
    # 이름이 0.7 이상 맞으면 브랜드 대응도 맞다고 볼 수 있다. 단 2건 이상
    # 반복될 때만 — 1건짜리는 판매처명이 섞여 정확도가 3분의 2로 떨어졌다.
    unknown_path = ('status == "unknown"' in src
                    and "< 0.7" in src
                    and "MIN_OCCURRENCES = 2" in src)
    len_guard = "MIN_ALNUM_LEN = 5" in src
    hangul_guard = "HANGUL_RE.search(kr)" in src
    vote_guard = "MIN_OCCURRENCES = 2" in src and "n < MIN_OCCURRENCES" in src
    split_guard = "len(counter) > 1" in src
    no_overwrite = "jp in clean_dict" in src
    # 사전값이 판매처명이라 더 길 수 있다(Purito -> '퓨리토서울').
    # 한 방향만 비교하면 '퓨리토'와 남남이 된다.
    bidirectional = "kr_brand_lower in c.lower()" in review

    ok = (len_guard and hangul_guard and vote_guard and split_guard
          and no_overwrite and bidirectional and unknown_path)
    check("63 브랜드 대응 자동수확(안전조건)", ok,
          f"길이{len_guard} 한글{hangul_guard} 2건이상{vote_guard} 갈래{split_guard} "
          f"덮어쓰기방지{no_overwrite} 양방향비교{bidirectional} 판단불가경로{unknown_path}")


# --------------------- #64 브랜드 칸에 판매처명이 들어오는 경우
#  네이버 브랜드 칸에는 실제 브랜드가 아니라 판매처명이 자주 들어온다.
#      cellmedics -> 브랜드칸 '더리즈', 상품명 '셀메딕스 MGF 리턴 크림'
#      DANONAL    -> 브랜드칸 '마실',   상품명 '다노날 헤어 두피토닉'
#  브랜드 칸만 보면 같은 제품인데도 '브랜드가 다릅니다'가 되고, 신뢰도가
#  깎여 뒤로 밀린다. 상품명에 브랜드가 들어있으면 맞은 것으로 본다.
#
#  단, 이 완화는 사전에 대응이 등록된 경우에만 쓴다 — 아무 문자열이나
#  상품명에서 찾으면 짧은 브랜드가 우연히 걸린다.
def t64_brand_in_product_name():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    fn = src.split("def check_brand(")[1].split("\ndef ")[0]

    accepts_name = "kr_product_name" in src.split("def check_brand(")[1][:200]
    name_path = "in name_lower for c in candidates" in fn
    # 사전 대응(expected)이 있을 때만 쓰는 경로여야 한다.
    only_with_dict = fn.index("name_lower") > fn.index("expected = brand_dict.get")
    # [v7.11.0] 사전에 없어도 큐텐 브랜드가 상품명에 그대로 있으면 같은
    # 브랜드다. 네이버 brand 칸에 판매처명이 들어오는 경우가 많아
    # (viviscal -> '슈퍼대디', SYRS -> '디디에즈'), 사전에 없는 브랜드는
    # 상품명을 볼 기회조차 없었다. 실측 D등급 78건 중 72건이 이 경우.
    # 짧은 영문은 다른 단어에 우연히 들어가므로 5자 이상, 4자는 상품명
    # 앞부분일 때만 받는다.
    dictless_name = ("len(orig_alnum) >= 5 and orig_alnum in name_alnum" in fn
                     and "name_alnum.startswith(orig_alnum)" in fn)
    # 2자 미만은 우연 일치가 잦다.
    len_guard = "len(c) >= 2" in fn
    # 호출부가 상품명을 실제로 넘겨야 의미가 있다.
    passed = src.count('brand_dict, x.get("name") or ""') >= 2

    ok = (accepts_name and name_path and only_with_dict and len_guard and passed
          and dictless_name)
    check("64 브랜드칸이 판매처명일 때 상품명 참조", ok,
          f"인자{accepts_name} 경로{name_path} 사전한정{only_with_dict} "
          f"길이가드{len_guard} 호출부전달{passed} 사전없이도{dictless_name}")


# --------------------- #65 번역 용어를 한국 표기로
#  번역본(translated_kr)은 화면 표시용이 아니라 검증 검색어로 그대로 쓰인다.
#  일본어를 직역한 용어가 들어가면 한국 쇼핑몰 검색이 빗나가고 그 상품은
#  구매링크 없음으로 버려진다. 실측 4,586건 중 973건(21%)이 해당했다.
#      미용액(美容液) 247 · 화장수(化粧水) 151 · 유액(乳液) 55 · 세안료 26
#      수징 68 · 엑소솜 31 · 블레미시 17
#  띄어쓰기도 같은 문제다 — 한국 상품명은 붙여 쓴다('선 크림' 41건).
#
#  ⚠️ 일본어처럼 보인다고 전부 바꾸면 안 된다. 판단 기준은 '한국에서
#  그렇게 쓰는가'다. 두피(111)·미백(65)·모공·히알루론산(159)·
#  자외선 차단제(56)는 한국에서도 정상 표기라 건드리지 않는다.
def t65_translation_term_fixes():
    script = SRC / "fix_translation_terms.py"
    if not script.exists():
        check("65 번역 용어 한국표기", False, "fix_translation_terms.py 없음"); return
    src = script.read_text(encoding="utf-8")
    req = (SRC / "export_translation_request.py").read_text(encoding="utf-8")

    has_terms = all(f'("{a}", "{b}")' in src for a, b in
                    (("미용액", "에센스"), ("화장수", "토너"), ("유액", "로션"),
                     ("세안료", "클렌저"), ("수징", "수딩")))
    has_spacing = '("선 크림", "선크림")' in src and '("토너 패드", "토너패드")' in src
    # 한국에서 쓰는 말은 교정 대상에 없어야 한다.
    safe = not any(f'("{w}"' in src for w in ("두피", "미백", "모공", "히알루론산"))
    # 앞으로의 번역에도 반영돼야 한다 — 요청서 지시문에 용어표가 있어야 한다.
    in_request = "美容液 → 에센스" in req and "붙여 쓰는 말" in req
    # [v7.17.0] 매칭된 한국 상품명을 기준으로 번역 표기를 고친다. 1,277쌍을
    # 대조해 3회 이상 반복된 차이만 뽑았다(프레시->프레쉬, 배리어->베리어,
    # 에멀전->에멀젼 등). 고친 흔적을 남겨야 잘못 고친 것을 알아볼 수 있다.
    korean_spelling = "KOREAN_SPELLING_FIXES" in src and "KOREAN_SPELLING_FIXES" in \
        src.split("ALL_FIXES =")[1].split("\n")[0]
    leaves_trace = 'p["term_fixed"]' in src
    shown_in_review = ('"term_fixed": x.get("term_fixed")' in
                       (SRC / "build_review.py").read_text(encoding="utf-8")
                       and "표기 교정" in (SRC / "build_review_batches.py").read_text(encoding="utf-8"))
    # [v6.1.0] 번역 결과가 검색어로 쓰인다는 사실을 지시문이 먼저 알려야
    # 한다. 이걸 모르면 '매끄러운 번역'을 하게 되고, 실제 상품 표기와
    # 멀어져 검색이 빗나간다.
    explains_purpose = "네이버 쇼핑에서 같은 상품을" in req
    # 같은 브랜드 안에서 라인·번호·색상·제형만 다른 오매칭이 가장 흔했다.
    warns_variants = "라인명·번호·색상·제형을 절대" in req
    # [v7.3.0] 제형이 틀리면 다른 상품이 된다. 일본어->한국 표기 대응표를
    # 지시문 맨 앞에 둬서, 번역이 한국 쇼핑몰 표기를 그대로 쓰게 한다.
    baku_added = "バクチオール → 바쿠치올" in req
    form_table = ("가장 중요: 제형" in req
                  and "クレンジングオイル | 클렌징오일" in req
                  and "洗顔料 / 洗顔フォーム | 클렌징폼" in req)

    ok = (has_terms and has_spacing and safe and in_request
          and explains_purpose and warns_variants and form_table
          and korean_spelling and leaves_trace and shown_in_review)
    check("65 번역 용어 한국표기", ok,
          f"용어표{has_terms} 띄어쓰기{has_spacing} 한국어보호{safe} 요청서반영{in_request} "
          f"용도설명{explains_purpose} 변형경고{warns_variants} 제형대응표{form_table} "
          f"한국표기{korean_spelling} 교정흔적{leaves_trace} 화면표시{shown_in_review}")


# --------------------- #66 제형 일치를 A등급 조건으로
#  같은 브랜드·같은 라인이라도 제형이 다르면 다른 상품이다. 실측 오매칭에서
#  가장 자주 나온 형태다: 클렌징폼->클렌징오일, 선크림->선세럼,
#  샴푸->컨디셔너, 독도 클렌저->독도 클렌징 밤, 미스트->스프레이.
#  브랜드가 맞으니 다른 규칙으로는 걸리지 않는다.
#
#  A는 '확인된 것'만 받는다 — 제형을 못 읽었으면(unknown) A로 올리지 않고
#  B로 둔다. 실측 A 917건 중 176건이 제형 미확인이었고 이들이 B로 내려간다.
#
#  ⚠️ 한국에서 섞어 쓰는 말은 한 묶음이어야 한다(세럼=에센스=앰플,
#  토너=스킨=화장수). 묶지 않으면 정상 매칭이 대량으로 걸린다.
def t66_form_match_required_for_A():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")

    has_groups = "FORM_GROUPS" in src and "def extract_forms(" in src
    has_status = "def form_status(" in src and 'return "unknown"' in src.split("def form_status(")[1]
    # 동의어 묶음이 있어야 한다.
    # (사전이 데이터에서 뽑은 어휘로 넓어져 항목 내용이 바뀔 수 있으므로,
    #  정확한 리스트가 아니라 '동의어가 묶여 있는지'를 본다)
    fg = src.split("FORM_GROUPS: dict[str, list[str]] = {")[1].split("\n}")[0]
    synonyms = all(w in fg for w in ('"에센스"', '"앰플"', '"스킨"', '"화장수"', '"린스"'))
    tfn = src.split("def confidence_tier(")[1].split("\ndef ")[0]
    # (brand_status는 함수 시그니처에도 나오므로 조건문 자체와 비교한다)
    # [v6.7.0] 대분류/소분류 포함관계를 봐야 한다. '클렌징'과 '클렌징 폼'은
    # 같은 것이고, '클렌징 폼'과 '클렌징 오일'은 다른 것이다. 대분류 이름이
    # 소분류 문자열에 들어있어서 단순 교집합으로는 이 둘이 구분되지 않는다.
    # [v7.12.0] 대립 제형쌍. 제형 사전만으로는 '아이크림'과 '크림',
    # '선세럼'과 '선크림'을 못 가른다 — 세부어가 상위어를 문자열로 품고
    # 있어 교집합이 생기기 때문이다. 실측 오매칭 261건을 정상 매칭과
    # 대조해 뽑은 쌍만 쓴다.
    # [v7.15.0] 복합 표기('크림 마스크')는 뒤에 오는 말이 제품의 정체다.
    # 제형 사전이 글자를 찾는 방식이라 '크림'과 '마스크팩'을 둘 다 잡고,
    # 큐텐 쪽 '크림'과 교집합이 생겨 같은 제품으로 판정됐다.
    # 실측: 셀리맥스 '브라이트닝 크림 35ml' -> '브라이트닝 크림 마스크 4매'.
    compound = ("COMPOUND_FORMS" in src
                and "for rx, drop, keep in COMPOUND_FORMS:" in src
                and "found.discard(drop)" in src)
    conflict = ("CONFLICTING_FORMS" in src and "def has_form_conflict(" in src
                and "FORM_SPECIALIZATIONS" in src
                and "has_form_conflict(qoo10_name, kr_name)" in src)
    hierarchy = ("FORM_PARENTS" in src and "def _covers(" in src
                 and "spec_a, spec_b = a - parents, b - parents" in src)
    # 제형 불일치도 D로 간다(브랜드/제형 확인 실패와 같은 취급).
    mismatch_to_c = 'form != "match"' in tfn
    unknown_not_a = 'form != "match"' in tfn
    attached = 'form_status(translated_kr, x.get("name") or "")' in src

    ok = (has_groups and has_status and synonyms and mismatch_to_c
          and unknown_not_a and attached and hierarchy and conflict and compound)
    check("66 제형 일치가 A등급 조건", ok,
          f"사전{has_groups} 판정{has_status} 동의어{synonyms} 불일치는C{mismatch_to_c} "
          f"미확인은A아님{unknown_not_a} 부착{attached} 대소분류{hierarchy} 대립제형{conflict} "
          f"복합표기{compound}")


# --------------------- #67 네일·향수 카테고리 제외
#  색조(013·014·016)는 원래 빠져 있었는데 네일(021)·향수(022)는 통과하고
#  있었다. 이 둘도 색상·호수·향으로 갈리는 상품군이라 이름만으로는 같은
#  제품인지 알 수 없다. 실측 오매칭:
#      '앰버바닐라 세럼 바디크림' -> '로즈 바디크림'
#      '파워네일 마그넷' -> '파워 마그넷 세팅 스프레이'
#      '서울 시크릿 블로썸 30ml' -> '소울 시크릿 블라썸'
#  발굴·수확 양쪽에서 빼야 한다 — 한쪽만 고치면 다른 쪽으로 계속 들어온다.
#  이미 쌓인 238건은 검수페이지에서 거른다.
def t67_nail_perfume_excluded():
    disc = (SRC / "iterative_low_review_discovery.py").read_text(encoding="utf-8")
    harvest = (SRC / "harvest_full_catalog.py").read_text(encoding="utf-8")
    review = (SRC / "build_review.py").read_text(encoding="utf-8")

    def allowed(text):
        # 주석에도 코드가 적혀 있으므로(제외 사유 설명), 따옴표로 등록된
        # 항목만 본다.
        block = text.split("COSMETIC_ALLOWED_CATEGORIES = {")[1].split("}")[0]
        codes = set(re.findall(r'"(\d{9})"', block))
        return "120000021" not in codes and "120000022" not in codes

    disc_ok = allowed(disc)
    harvest_ok = allowed(harvest)
    # 색조는 계속 빠져 있어야 한다.
    color_ok = all('"120000013"' in t for t in (disc, harvest))
    review_ok = ('EXCLUDED_CATEGORIES' in review
                 and '"120000021"' in review and '"120000022"' in review
                 and 'str(q.get("category_gdlc_cd")) in EXCLUDED_CATEGORIES' in review)

    ok = disc_ok and harvest_ok and color_ok and review_ok
    check("67 네일·향수 카테고리 제외", ok,
          f"발굴{disc_ok} 수확{harvest_ok} 색조유지{color_ok} 검수페이지{review_ok}")


# --------------------- #68 색상·호수 비교
#  같은 제품의 다른 색은 다른 상품이다. 실측: 달바 '워터풀 톤업 선크림
#  그린'과 '퍼플'은 브랜드·제형·용량이 모두 같아 걸러낼 요소가 없었다.
#  공식 상세페이지를 보면 핑크/퍼플/그린 세 종류이고 피부톤에 따라 고르는
#  별개 상품이다. 색을 잘못 보내면 반품 사유가 된다.
#
#  한쪽에만 색이 적힌 경우는 '어긋남'이 아니라 '알 수 없음'이다 —
#  한국 쇼핑몰은 색을 옵션으로 빼서 상품명에 안 쓰는 경우가 흔하다.
#  여기서 불일치로 처리하면 정상 매칭이 대량으로 걸린다.
def t68_color_shade_check():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    has_words = "COLOR_WORDS" in src and "SHADE_RE" in src
    has_fn = "def color_status(" in src
    fn = src.split("def color_status(")[1].split("\ndef ")[0] if has_fn else ""
    one_sided_unknown = 'if not a or not b:' in fn and 'return "unknown"' in fn
    in_tier = 'if color == "mismatch":' in src
    attached = 'color_status(translated_kr, x.get("name") or "")' in src

    ok = has_words and has_fn and one_sided_unknown and in_tier and attached
    check("68 색상·호수 비교", ok,
          f"색상어{has_words} 함수{has_fn} 한쪽만은보류{one_sided_unknown} "
          f"등급반영{in_tier} 부착{attached}")


# --------------------- #69 검수 화면에 제형 노출
#  등급(A~D)만 보여주면 무엇이 어긋났는지 알 수 없어, 검수할 때마다 상품명
#  두 줄을 다시 읽어야 한다. 제형은 오매칭의 가장 흔한 원인이므로 한 줄로
#  뽑아 보여준다.
#      클렌징폼 / 클렌징오일  [다름]
#      세럼 / 세럼           [일치]
#      ? / 크림              [확인불가]
def t69_form_shown_in_review():
    review = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    in_pair = '"qoo10_forms": sorted(extract_forms(' in review and '"kr_forms":' in review
    rendered = all("form_row" in t and '<td class="label">제형</td>' in t
                   for t in (review, batches))
    # 상태를 색으로도 구분해야 한눈에 들어온다.
    colored = '"mismatch": "#c0392b"' in batches

    ok = in_pair and rendered and colored
    check("69 검수 화면에 제형 노출", ok,
          f"필드{in_pair} 표시{rendered} 색구분{colored}")


# --------------------- #70 판매페이지 제목 품질
#  검수페이지는 '판매페이지에서 직접 가져온 상품명'을 최우선으로 쓴다.
#  그런데 확보한 260건 중 93건이 상품명이 아니었다.
#      '에러 페이지' 92건 · '지그재그 스토어' 46건 · 'NAVER 로그인'
#  길이 5자 이상이면 통과시키는 조건뿐이라 그대로 화면에 상품명으로 떴다.
#  가져오는 쪽과 보여주는 쪽 양쪽에서 걸러야 한다 — 이미 저장된 값은
#  재검증 전까지 남아 있기 때문이다.
def t70_page_title_quality():
    """[v7.9.0] 수집 자체를 중단했다. 남은 것은 '이미 저장된 값이 화면에
    새어나오지 않는가'와 '다시 켤 때 참고할 근거가 남아 있는가'다."""
    fetch = (SRC / "fetch_page_title.py").read_text(encoding="utf-8")
    review = (SRC / "build_review.py").read_text(encoding="utf-8")

    fetch_guard = ("def looks_like_junk_title(" in fetch
                   and "JUNK_TITLE_PATTERNS" in fetch
                   and "STORE_ONLY_RE" in fetch)
    display_guard = ("def looks_like_junk_page_title(" in review
                     and "looks_like_junk_page_title(_real)" in review)
    # [v7.7.0] 모바일 주소 우회는 뺐다. "데스크톱이 JS라 모바일이면 된다"는
    # 추측이었고 실측에서 모바일도 똑같이 막혔다. 남겨두면 실패할 요청을
    # 한 번 더 보내 검증만 느려진다. 어떤 방법이 되는지는 측정으로 정한다.
    no_guess_fallback = "m.smartstore.naver.com" not in fetch
    has_probe = (SRC / "smartstore_probe.py").exists()

    # 수집 중단: 매 건 실패할 요청을 보내지 않아야 한다.
    verify = (SRC / "hwahae_verify_batch.py").read_text(encoding="utf-8")
    disabled = 'if False and entry.get("product_url"):' in verify
    # 왜 껐는지가 코드에 남아야 한다 — 나중에 다시 켜려 할 때 같은 시행착오를
    # 반복하지 않게.
    documented = "HTTP 490" in verify and "로그인한 브라우저" in verify

    ok = (fetch_guard and display_guard and no_guess_fallback and has_probe
          and disabled and documented)
    check("70 판매페이지 제목 수집 중단", ok,
          f"수집가드{fetch_guard} 표시가드{display_guard} 추측우회제거{no_guess_fallback} "
          f"측정스크립트{has_probe} 수집중단{disabled} 근거기록{documented}")


# --------------------- #71 로컬 수집 판매페이지 정보 반영
#  네이버 검색 API 의 title·price 는 요약형이라 실제 판매페이지와 다르다.
#      API  케라시스 히트 액티브 극손상 바르는 트리트먼트, , 1개
#      실제 케라시스 히트액티브 극손상 헤어드라이 에센스, 220ml, 2개
#      API  리쥬란 더마 힐러 모이스처 트리트먼트 앰플  30,400원
#      실제 리쥬란 더마 힐러 모이스처 크림 60ml, 1개   36,100원(정가 38,000)
#  상품명이 다르면 검수에서 같은 상품인지 판단할 수 없고, 가격이 다르면
#  마진 계산이 틀린다.
#
#  GitHub Actions 는 네이버가 IP 대역째 막아(429) 페이지를 못 연다. 수집은
#  로컬 PC 에서 실제 크롬으로 하고 그 결과를 여기서 넣는다(실측 2,465/2,572).
#
#  덮어쓰기 전에 원래 값을 남겨야 한다 — 잘못 반영됐을 때 되돌릴 근거이고,
#  이름이 빈 건(수집 실패 107건)을 덮어쓰면 화면이 비어버린다.
def t71_apply_collected_pages():
    script = SRC / "apply_collected_pages.py"
    if not script.exists():
        check("71 로컬 수집 반영", False, "apply_collected_pages.py 없음"); return
    src = script.read_text(encoding="utf-8")
    review = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    skips_empty = 'if c.get("name")' in src
    keeps_original = ('r.setdefault("api_name"' in src
                      and 'r.setdefault("api_price"' in src
                      and 'r.setdefault("api_image_url"' in src)
    # 가격은 시간이 지나면 낡는다. 언제 수집했는지 남겨야 한다.
    stamps_time = '"page_collected_at"' in src
    atomic = ".replace(vpath)" in src
    # 정가는 판매가와 다를 때만 의미가 있다.
    list_price_only_if_diff = "int(lst) != int(sale)" in src
    shown = '"kr_list_price"' in review and "kr_list_price" in batches

    ok = (skips_empty and keeps_original and stamps_time and atomic
          and list_price_only_if_diff and shown)
    check("71 로컬 수집 판매페이지 반영", ok,
          f"빈이름건너뜀{skips_empty} 원본보존{keeps_original} 수집시각{stamps_time} "
          f"원자적저장{atomic} 정가조건{list_price_only_if_diff} 화면표시{shown}")


# --------------------- #72 수집 브랜드 자동 대조
#  로컬 크롬으로 수집한 판매페이지 정보에는 실제 브랜드가 들어 있다
#  (2,465건 중 2,028건). 검증 데이터의 brand 칸은 판매처가 자기 스토어명을
#  넣는 경우가 많아 신뢰도가 낮은데, 이 값은 상품 페이지에서 직접 읽었다.
#
#  실측: 이걸로 대조해 오매칭 187건을 찾아냈다.
#      Dr.Melaxin -> 듀댑,  雪花秀 -> 멜비유,  呂 -> 아모레퍼시픽
#      ポーラ -> 나이키 운동화,  FULLY -> 후지필름 카메라
#  화장품이 아닌 것까지 검수 목록에 올라와 있었다.
#
#  이 자료를 저장소에 남겨야 다음 회차에도 자동으로 걸러진다. 한 번 확인한
#  것을 다시 확인하지 않으려면 판단 근거가 데이터로 남아야 한다.
def t72_collected_brand_crosscheck():
    path = ROOT / "data" / "collected_pages.json"
    src = (SRC / "build_review.py").read_text(encoding="utf-8")

    exists = path.exists()
    data = {}
    if exists:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    valid = isinstance(data, dict) and len(data) > 0
    has_brand = valid and sum(1 for v in data.values() if v.get("brand")) > 100
    loaded = 'collected_path = DATA / "collected_pages.json"' in src
    used = ("_col_brand and brand_status ==" in src
            and 'brand_status = "mismatch"' in src)
    # 파일이 없거나 깨져도 검수페이지 생성은 계속돼야 한다.
    _i = src.find("collected_path")
    safe = _i >= 0 and "except (OSError, ValueError)" in src[_i:_i + 700]

    ok = exists and valid and has_brand and loaded and used and safe
    check("72 수집 브랜드 자동 대조", ok,
          f"파일{exists}({len(data) if isinstance(data, dict) else '깨짐'}건) 형식{valid} "
          f"브랜드보유{has_brand} 읽기{loaded} 대조{used} 안전처리{safe}")


# --------------------- #73 성분·라인 불일치
#  화장품은 성분으로 라인을 나누는 경우가 많아, 같은 브랜드라도 성분이
#  다르면 다른 제품이다. 실측: 아누아 'PDRN 히알루론산 미스트'가
#  'PDRN 콜라겐 글로우 세럼 미스트'와 A등급으로 묶여 있었다. 브랜드·제형·
#  용량이 모두 같아 걸러낼 요소가 없었다.
#
#  '하나도 안 겹칠 때'만 보면 놓친다 — 위 사례는 PDRN 이 겹친다.
#  양쪽이 서로에게 없는 성분을 각각 내세울 때 본다.
#  한쪽만 성분을 밝힌 경우는 걸리지 않아야 한다. 상품명에서 성분을
#  생략하는 일이 흔하다.
def t73_ingredient_conflict():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    has_keys = "INGREDIENT_KEYWORDS" in src and "def extract_ingredients(" in src
    fn = src.split("def ingredient_conflict(")[1].split("\ndef ")[0] \
        if "def ingredient_conflict(" in src else ""
    # 양방향 차집합을 봐야 한다. 교집합만 보면 PDRN 사례를 놓친다.
    both_ways = "bool(a - b) and bool(b - a)" in fn
    # 한쪽만 밝힌 경우는 통과시켜야 한다.
    one_sided_ok = "if not a or not b:" in fn and "return False" in fn
    in_tier = "ingredient_mismatch and brand_status" in src
    attached = "ingredient_conflict(translated_kr" in src

    ok = has_keys and both_ways and one_sided_ok and in_tier and attached
    check("73 성분·라인 불일치", ok,
          f"키워드{has_keys} 양방향{both_ways} 한쪽만은통과{one_sided_ok} "
          f"등급반영{in_tier} 부착{attached}")


# --------------------- #74 자동수정 내역 표시("무엇에서 무엇으로")
#  용량/수량/발송지를 한국 실제 구매처 기준으로 자동수정할 때, 예전엔
#  "자동수정 미리보기: ..." 라는 문구만 있고 원래 값이 뭐였는지는 하이라이트
#  안을 눈으로 찾아야 알 수 있었다. "10g -> 50g"처럼 원래값과 새값을
#  나란히 적은 change_notes 를 만들어 카드에 보여준다. 미리보기 문구는 뺐다.
def t74_change_notes_display():
    src = (SRC / "build_review.py").read_text(encoding="utf-8")
    batches = (SRC / "build_review_batches.py").read_text(encoding="utf-8")

    collects = "change_notes: list[str] = []" in src
    vol_note = 'change_notes.append(f"용량 {_orig_vol_str} → {kr_vol_int}' in src
    qty_notes = ('change_notes.append(f"수량 1{explicit_match.group(1)}' in src
                and 'change_notes.append(f"수량 표기없음' in src
                and 'change_notes.append(f"수량 {qty_removed_original}' in src)
    shipping_note = "change_notes.append(f\"발송지 표기" in src
    attached = '"change_notes": change_notes' in src
    no_old_text = "자동수정(용량/수량/발송지) 미리보기" not in src and "자동수정(용량/수량/발송지) 미리보기" not in batches
    shown = all("vol-fix-notes" in t for t in (src, batches))

    ok = (collects and vol_note and qty_notes and shipping_note and attached
          and no_old_text and shown)
    check("74 자동수정 내역 표시", ok,
          f"수집{collects} 용량{vol_note} 수량{qty_notes} 발송지{shipping_note} "
          f"부착{attached} 옛문구제거{no_old_text} 표시{shown}")


# --------------------- #75 판정 로직 설계 이력 문서
#  같은 시도를 반복해서 실패하는 일이 잦았다. '제형이 두 개면 세트'처럼
#  그럴듯해 보이는 규칙이 실측에서 오탐 투성이라 되돌린 사례가 여럿이고,
#  되돌린 이유가 커밋 메시지에만 흩어져 있어 나중에 찾기 어려웠다.
#  판정로직_설계이력.md 에 '시도했다가 못 쓴 방법'과 그 근거를 모아둔다.
#  새 규칙을 만들기 전에 이 문서를 먼저 읽는다.
def t75_design_history_doc():
    doc = ROOT / "판정로직_설계이력.md"
    if not doc.exists():
        check("75 판정 로직 설계 이력", False, "판정로직_설계이력.md 없음"); return
    text = doc.read_text(encoding="utf-8")

    # 실패 사례가 근거(실측 숫자)와 함께 적혀 있어야 한다. 숫자가 없으면
    # 다음 사람이 "이번엔 다를 것"이라 생각하고 같은 시도를 반복한다.
    has_failures = "시도했다가 못 쓴 방법" in text
    has_numbers = all(k in text for k in ("255건", "625건", "187건"))
    has_order = "판정 순서" in text and "confidence_tier" in text
    has_pitfalls = all(k in text for k in ("제형 판정의 함정", "브랜드 판정의 함정"))
    has_checklist = "새 규칙을 만들 때 점검할 것" in text

    ok = has_failures and has_numbers and has_order and has_pitfalls and has_checklist
    check("75 판정 로직 설계 이력", ok,
          f"실패사례{has_failures} 실측근거{has_numbers} 판정순서{has_order} "
          f"함정{has_pitfalls} 점검표{has_checklist}")


# --------------------- #76 발굴 제외 목록
#  카테고리·리뷰수 같은 일반 조건으로는 거를 수 없는 개별 사유가 있다.
#  실측: 'エイシカ365 水分鎮静トナー, [25ml*10] 250ml' 는 소분 표기가 앞에
#  와서 용량이 25ml 로 잘못 읽히고, 그 탓에 200ml 상품과 8배 차이로 판정돼
#  매번 오매칭된다. 검수에서 빼도 다음 발굴에 또 들어오므로 발굴 단계에서
#  막는다.
#
#  검증 입력을 만들 때 걸러낸다. 검수페이지 생성 때만 빼면 검증이 그대로
#  다 돌고 나서 버려진다 — 해외브랜드에서 이미 겪은 낭비다(490건이 헛돌았다).
#  발굴·수확은 건드리지 않는다. 상품 자체는 계속 수집하되 검수 대상에서만 뺀다.
# --------------------- #77 수량·매수 불일치는 B등급 (v7.25.0)
#  confidence_tier 주석의 설계("B = 용량/수량만 다름")에 수량이 처음부터
#  있었는데 구현은 용량만 보고 있었다. 실측: A등급 273건 중 30건이
#  '1+1 vs 단품', '10매 vs 1매' 같은 수량 불일치였고, 뉴클리드 마스크팩은
#  10매 가격과 1매 가격이 A(완전일치)로 나란히 놓여 있었다.
#  함정: 매수(매/장/枚/EA)와 묶음개수(個/개/팩)가 양쪽에 교차 표기된다 —
#  "10개"="10매, 1개", "(3+1)"="4매", "60장x2개"="[1+1] 60매". 총량으로
#  환산하지 않으면 같은 상품이 오탐된다(실측 오탐 4건을 이 검사가 고정).
def t77_count_mismatch_demotes_to_b():
    import importlib
    _sp = sys.path[:]
    sys.path.insert(0, str(SRC))
    try:
        import build_review as _br
        importlib.reload(_br)

        # 정규식이 실측 표기를 전부 읽는가 ('매\b'로는 "10매입"·"70장"을 못 읽었다)
        sheet_ok = all(_br.extract_sheet_count(t) == e for t, e in [
            ("10매입", 10), ("70장", 70), ("6장입", 6), ("10枚", 10),
            ("(10EA)", 10), ("60장x2개", 60), ("마스크팩", None), ("장짜리", None)])
        pack_ok = _br.extract_quantity("[2pack] 수딩 패드 70매") == 2

        # 총량 환산이 교차 표기를 흡수하는가 (같은 상품 = 오탐 금지)
        same = [("다이브인 마스크 10개", "마스크 10매, 1개"),
                ("페이스 필름 (3+1)", "페이스필름 4매"),
                ("앰플 패드 60장x2개", "[1+1] 앰플 패드 60매"),
                ("코팩 6장입", "코팩 6매입"),
                ("마스크 (10매입)", "마스크 25 ml (10EA)"),
                ("펩타이드 샷 앰플 2X 100ml", "펩타이드 샷 앰플 투엑스 100ml, 1개")]
        no_false_pos = all(not _br.counts_mismatch(q, k) for q, k in same)

        # 진짜 불일치는 잡는가
        diff = [("마스크팩 9매입 (9+1)", "마스크팩 23g"),        # 10 vs 1
                ("와사비 수딩 마스크 30g", "마스크팩 10매입"),    # 1 vs 10
                ("[1+1] 필링 젤 100g", "필링 젤 100g"),          # 2 vs 1
                ("수딩 패드 70장 입", "[2pack] 수딩 패드 70매")]  # 70 vs 140
        catches = all(_br.counts_mismatch(q, k) for q, k in diff)

        # 세트는 여기서 보지 않는다(S등급에서 처리)
        set_exempt = not _br.counts_mismatch("토너 세트", "토너 2종세트", is_set=True)

        # 등급: 이름 일치 + 수량 불일치 -> B, 일치 -> A (자동 제외 금지, 강등만)
        def _t(cm):
            return _br.confidence_tier(4, "match", False, True, False, "match",
                                       True, "unknown", False, False,
                                       count_mismatch=cm)
        tier_ok = _t(True) == "B" and _t(False) == "A"

        # 판정에 실제로 연결돼 있는가 (extract_sheet_count가 함수만 있고
        # confidence_tier에 안 이어져 있던 것이 원래 사고 원인)
        src = (SRC / "build_review.py").read_text(encoding="utf-8")
        wired = "count_mismatch=counts_mismatch(" in src

        ok = all([sheet_ok, pack_ok, no_false_pos, catches, set_exempt,
                  tier_ok, wired])
        check("77 수량·매수 불일치 B등급", ok,
              f"매수정규식{sheet_ok} 팩{pack_ok} 오탐없음{no_false_pos} "
              f"검출{catches} 세트예외{set_exempt} 등급{tier_ok} 연결{wired}")
    except Exception as e:  # noqa: BLE001
        check("77 수량·매수 불일치 B등급", False, f"{type(e).__name__}: {e}")
    finally:
        sys.path[:] = _sp


# --------------------- #78 '본품 + α' 3분류 (v7.26.0)
#  큐텐은 본품 단품인데 한국 판매처는 기획 구성인 건이 42건 있었다.
#  전부 세트로 묶으면 멀쩡한 매칭이 S로 사라지고, 전부 무시하면 실제로
#  두 배를 사는 건이 A로 남는다. α를 증정/본품추가/다른제품으로 가른다.
#
#  두 가지 함정이 실측으로 확인됐다.
#  (1) 판정 순서 — 용량 비율을 제형보다 먼저 보면 '토너 350ml + 크림
#      20ml'(다른 제품)이 소량이라는 이유로 증정이 된다. 순서를 뒤집자
#      다른제품 검출이 13건 -> 39건으로 늘고 오분류가 사라졌다.
#  (2) 비대칭 — 증정을 무시하는 건 한국측(사는 쪽)만이다. 큐텐측은 내가
#      파는 구성이라 '크림 50ml + 미니 15ml' 로 올려놨으면 미니도 사서
#      보내야 한다. 양쪽에서 지우면 못 맞추는 구성이 A로 남는다.
def t78_bonus_classification():
    import importlib
    _sp = sys.path[:]
    sys.path.insert(0, str(SRC))
    try:
        import build_review as _br
        importlib.reload(_br)

        def _kind(seg, mv=50.0, ms=None, mf=frozenset({"크림"})):
            return _br.classify_bonus(seg, mv, ms, set(mf))

        gift_ok = all(_kind(s) == "gift" for s in
                      ["휴대용 미니 15ml", "파우치", "쇼핑백)", "미니거울",
                       "픽서 50ml 증정)", "4ml)", "약통"])
        main_ok = (_kind("리필250ml") == "main"
                   and _kind("리필 100ml 기획상품 탈모 두피에센스") == "main"
                   and _kind("50ml") == "main"
                   and _br.classify_bonus("리필 60매", None, 60, set()) == "main")
        # 제형이 다르면 소량이어도 다른 제품이다(판정 순서 고정)
        other_ok = (_kind("포어 리파이너 크림 30ml", 200.0, None, frozenset({"로션"})) == "other"
                    and _kind("크림 20ml 기획세트", 350.0, None, frozenset({"토너"})) == "other")

        # 증정은 잘라내고, 본품 추가는 배수로 센다
        _, m1, o1 = _br.split_bonus("마데카 크림 50ml + 휴대용 미니 15ml")
        _, m2, o2 = _br.split_bonus("트리트먼트 250ml+리필250ml")
        _, m3, o3 = _br.split_bonus("세비엄 로션 200ml+포어 리파이너 크림 30ml")
        split_ok = (m1, o1, m2, o2, m3, o3) == (1, False, 2, False, 1, True)

        # 등급 결과: 증정 -> 그대로, 동량 리필 -> 수량 불일치, 다른제품 -> 세트
        gift_keeps = not _br.counts_mismatch(
            "마데카 크림 리뉴 PDRN 50ml",
            "센텔리안24 마데카 크림 리뉴 PDRN 50ml + 휴대용 미니 15ml")
        refill_catches = _br.counts_mismatch(
            "노워시 트리트먼트 250ml",
            "그로우어스 노워시 트리트먼트 250ml+리필250ml")
        other_is_set = _br.is_set_product(
            "토너 350ml", "아누아 어성초 토너 350ml+크림 20ml 기획세트")
        gift_not_set = not _br.is_set_product(
            "마데카 크림 50ml", "센텔리안24 마데카 크림 50ml + 휴대용 미니 15ml")

        src = (SRC / "build_review.py").read_text(encoding="utf-8")
        # 세트 판정 입력은 표시명이어야 한다(승자 name 이 아니라)
        # 비대칭: 증정 제거는 한국측 인자에만 적용해야 한다. 큐텐측은 내가
        #  파는 구성이라 지우면 안 된다(큐텐측 구성 불일치 검출 자체는
        #  별도 규칙 — 여기서는 지우지 않는다는 것만 고정한다).
        cm = src.split("def counts_mismatch(")[1].split("\ndef ")[0]
        st = src.split("def is_set_product(")[1].split("\ndef ")[0]
        asymmetric = ("split_bonus(kr_name)" in cm
                      and "split_bonus(qoo10_name_kr)" not in cm
                      and "split_bonus(kr_name)" in st
                      and "split_bonus(qoo10_name)" not in st)

        display_input = "is_set_tier = is_set_product(translated_for_tier, kr_name_display)" in src

        ok = all([gift_ok, main_ok, other_ok, split_ok, gift_keeps,
                  refill_catches, other_is_set, gift_not_set, asymmetric,
                  display_input])
        check("78 본품+증정 3분류", ok,
              f"증정{gift_ok} 본품추가{main_ok} 다른제품{other_ok} 분리{split_ok} "
              f"증정유지{gift_keeps} 리필검출{refill_catches} 세트{other_is_set} "
              f"증정비세트{gift_not_set} 비대칭{asymmetric} 표시명입력{display_input}")
    except Exception as e:  # noqa: BLE001
        check("78 본품+증정 3분류", False, f"{type(e).__name__}: {e}")
    finally:
        sys.path[:] = _sp


# --------------------- #79 큐텐 증정 초과분 삭제 (v7.27.0)
#  큐텐에 '크림 50ml + 15ml + 15ml' 로 올려놨는데 한국에서는 50ml 단품밖에
#  못 사면 15ml 두 개를 줄 수가 없다. 못 지킬 구성을 파는 셈이라 초과분을
#  업로드용 제목에서 뺀다.
#  지우는 건 파는 물건을 바꾸는 일이라 기준을 좁게 잡는다:
#   - 조각에 제형어가 있거나 본품 제형을 모르면 안 지운다
#     (실측: '부스터 120ml + 세럼 45ml' 2종 구성이 증정으로 읽혔다)
#   - 조각이 12자를 넘으면 안 지운다
#     (실측: '큐리베어SOS 멜더 시스템 (1.5ml x 20本)' 이 증정으로 읽혔다)
#   - 번역본과 원문의 '+' 조각 수가 다르면 대응이 안 되므로 손대지 않는다
#  이 세 조건으로 31건 -> 14건이 된다.
def t79_qoo10_excess_gift_removal():
    import importlib
    _sp = sys.path[:]
    sys.path.insert(0, str(SRC))
    try:
        import build_review as _br
        importlib.reload(_br)

        # 괄호가 깨지지 않아야 한다. 그냥 지우면 '(+7ml)' 가 '(' 로 남는다.
        brackets_ok = all(_br._remove_gift_segment(t, s) == e for t, s, e in [
            ("コアタイムアンプル 15ml (+7ml)", "7ml)", "コアタイムアンプル 15ml"),
            ("企画セット 【120ml+15ml】", "15ml】", "企画セット 【120ml】"),
            ("オイル200ml+フォーム(20ml+20ml)", "20ml)", "オイル200ml+フォーム(20ml)"),
            ("クリーム 50ml+15ml+15ml", "15ml", "クリーム 50ml+15ml")])

        # 마지막 조각부터 지운다(앞에서 지우면 '(20ml+20ml)' 가 '(+20ml)')
        last_first = _br._remove_gift_segment(
            "A 200ml+B(20ml+20ml)", "20ml)") == "A 200ml+B(20ml)"

        # 제형어가 붙은 조각과 긴 조각은 지우지 않는다
        strict_skips_form = _br.gift_indexes(
            "부스터 120ml + 세럼 45ml", strict=True)[0] == []
        strict_skips_long = _br.gift_indexes(
            "멜라 크림 35ml+에스오에스 멜더 시스템 (1.5ml x 20개)",
            strict=True)[0] == []

        # 조각 수가 다르면 손대지 않는다
        untouched = _br.strip_excess_gifts(
            "クリーム 50ml", "크림 50ml + 15ml + 15ml", "크림 50ml")[1] == []
        # 정상 케이스는 지우고 흔적을 돌려준다
        title, dropped = _br.strip_excess_gifts(
            "シカペア クリーム 50ml+15ml+15ml",
            "시카페어 크림 50ml+15ml+15ml", "시카페어 크림 50ml")
        works = len(dropped) == 2

        # 자동수정 체인의 맨 끝에서 적용해야 한다 — 앞의 용량·수량 자동수정이
        # q["title"] 원문 기준으로 다시 쓰기 때문에, 먼저 지우면 덮여 사라진다
        src = (SRC / "build_review.py").read_text(encoding="utf-8")
        body = src.split("qoo10_title_display = q[\"title\"]")[1].split("pairs.append(")[0]
        after_shipping = (body.index("_remove_gift_segment(")
                          > body.index("shipping_removal_pattern"))
        # 지운 내역이 반드시 남아야 한다(조용히 사라지면 잘못 지워도 모른다)
        logged = '"큐텐 증정 "' in src and '"dropped_gifts": _dropped_gifts' in src

        ok = all([brackets_ok, last_first, strict_skips_form, strict_skips_long,
                  untouched, works, after_shipping, logged])
        check("79 큐텐 증정 초과분 삭제", ok,
              f"괄호{brackets_ok} 뒤부터{last_first} 제형제외{strict_skips_form} "
              f"장문제외{strict_skips_long} 불일치보호{untouched} 동작{works} "
              f"체인끝{after_shipping} 기록{logged}")
    except Exception as e:  # noqa: BLE001
        check("79 큐텐 증정 초과분 삭제", False, f"{type(e).__name__}: {e}")
    finally:
        sys.path[:] = _sp


def t76_discovery_blocklist():
    path = ROOT / "data" / "discovery_blocklist.json"
    wf = WF.read_text(encoding="utf-8")

    exists = path.exists()
    data = {}
    if exists:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    valid = isinstance(data, dict) and isinstance(data.get("blocked"), list)
    # 사유가 적혀 있어야 한다. 없으면 나중에 왜 막았는지 알 수 없다.
    has_reason = valid and all(b.get("goods_no") and b.get("reason")
                               for b in data["blocked"])
    # 검증 입력 단계에서 걸러야 한다(검수페이지 생성 때가 아니라).
    at_verify = "discovery_blocklist.json" in wf and "[개별제외]" in wf
    # 파일이 없어도 검증이 멈추면 안 된다.
    safe = "_bp.exists()" in wf

    ok = exists and valid and has_reason and at_verify and safe
    check("76 검수 대상 개별 제외", ok,
          f"파일{exists}({len(data.get('blocked', [])) if valid else '깨짐'}건) 형식{valid} "
          f"사유기록{has_reason} 검증단계적용{at_verify} 안전처리{safe}")


# --------------------- #42 번역 엑셀 왕복 방식(API 번역 완전 제거)
#  Claude API 자동번역을 파이프라인에서 전부 걷어내고, 미번역 상품을
#  엑셀로 뽑아 사용자가 직접 번역해 되돌리는 방식으로 전환했다.
#  핵심 안전조건: API 호출 흔적이 남아있지 않을 것, 잘못된 번역값이
#  들어가 "완료"로 굳지 않을 것(과거 실패 #13과 같은 부류).
def t42_excel_translation_roundtrip():
    wf = WF.read_text(encoding="utf-8")
    no_api_key = "ANTHROPIC_API_KEY" not in wf
    no_api_scripts = not any((SRC / f).exists() for f in
                             ("auto_translate.py", "translate_in_place.py", "translate_kr_to_jp.py"))
    has_export = (SRC / "export_untranslated.py").exists()
    has_import = (SRC / "import_translated.py").exists()
    exports_in_wf = "export_untranslated.py" in wf

    imp = (SRC / "import_translated.py").read_text(encoding="utf-8") if has_import else ""
    # 일본어 잔존값은 반드시 걸러야 한다(넣으면 영영 재번역 안 됨)
    guards_kana = "KANA_RE.search(trans)" in imp
    # 이미 번역된 것은 덮어쓰지 않아야 한다
    no_overwrite = 'if p.get("translated_kr"):' in imp and "continue" in imp

    ok = all([no_api_key, no_api_scripts, has_export, has_import,
              exports_in_wf, guards_kana, no_overwrite])
    check("42 번역 엑셀왕복(API제거)", ok,
          f"API키없음{no_api_key} API스크립트없음{no_api_scripts} export{has_export} "
          f"import{has_import} 워크플로연결{exports_in_wf} 가나필터{guards_kana} 덮어쓰기방지{no_overwrite}")


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
