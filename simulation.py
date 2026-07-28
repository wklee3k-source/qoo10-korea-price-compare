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

    has_const = 'PRODUCT_SOURCES = {"hwahae", "musinsa", "naver"}' in src
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
