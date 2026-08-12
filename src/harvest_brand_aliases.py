"""harvest_brand_aliases.py — 검증 결과에서 브랜드 대응을 안전하게 수확한다.

[배경] 브랜드 판정에는 두 경로가 있다.
    ① 사전 조회        アヌア -> 아누아
    ② 영문 그대로 포함  COSRX -> "코스알엑스 (COSRX)"
②로 맞은 건은 사전에 없어도 통과하지만, 그 대응 자체는 사전에 남지 않는다.
실측 1,475건 중 205건이 ②로 통과했고 브랜드 171종이 여기 해당했다.
이걸 사전에 넣으면 다음 회차부터 B등급이 A등급으로 올라가 검수가 빨라진다.

[그런데 그냥 넣으면 위험하다 — 세 가지 함정]
 ① 짧은 영문은 우연히 맞는다. 알파벳만 남겨 부분 문자열로 비교하므로
    'LOA'는 'FLOAT'에, 'CURE'는 'SECURE'에 들어간다. 우연이 사전에
    들어가면 영구 규칙으로 굳는다.
 ② 대응값이 한글이 아니라 영문인 경우가 있다(AHC -> "AHC"). 넣어도
    아무 일도 하지 않는다 — 영문 포함 규칙이 이미 잡고 있어 중복이다.
 ③ 브랜드가 아니라 판매처명이 들어온다(Purito -> "퓨리토서울").
    한 번 나온 대응은 믿지 않고 2건 이상 반복될 때만 받는다.

그래서 세 조건을 모두 통과한 것만 등록한다.

사용법:
    python harvest_brand_aliases.py ../output/hwahae_verified_39.json \\
        ../output/discovery_state.json [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_review import check_brand, _sim_token, _sim_bigram  # noqa: E402

HANGUL_RE = re.compile(r"[가-힣]")
PAREN_RE = re.compile(r"\s*[\(（][^)）]*[\)）]\s*")

MIN_ALNUM_LEN = 5      # 영문 4자 이하는 우연 일치 위험이 크다
MIN_OCCURRENCES = 2    # 한 번은 우연일 수 있다


def alnum(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "")


def harvest(verified_path: str, discovery_path: str, brand_dict_path: str,
            dry_run: bool = False) -> int:
    brand_dict = json.loads(Path(brand_dict_path).read_text(encoding="utf-8"))
    clean_dict = {k: v for k, v in brand_dict.items() if not k.startswith("_")}

    products = {}
    for p in json.loads(Path(discovery_path).read_text(encoding="utf-8")).get("all_products", []):
        products[str(p.get("goods_no"))] = p

    votes: dict[str, Counter] = defaultdict(Counter)
    for x in json.loads(Path(verified_path).read_text(encoding="utf-8")):
        if not x.get("product_url"):
            continue
        q = products.get(str(x.get("goods_no")))
        if not q:
            continue
        jp = (q.get("brand") or "").strip()
        kr_raw = (x.get("brand") or "").strip()
        if not jp or not kr_raw or jp in clean_dict:
            continue
        # 두 갈래를 수확한다.
        #  ① 사전 없이 '영문 포함'으로 통과한 건 (COSRX -> '코스알엑스 (COSRX)')
        #  ② 브랜드는 판단불가인데 제품명이 거의 일치하는 건
        #     (ブランネイチャー '9배 고농축 어성초 토너패드' =
        #      블랑네이처 '9배 고농축 어성초 토너패드')
        #     이름이 이 정도로 맞으면 브랜드 대응도 맞다고 볼 수 있다.
        #     실측: 이 조건에 2건 이상 반복까지 걸면 표본 14종 전부 정확했다
        #     (로라메르시에·쌔뮤·더샘·논픽션·온더바디 등). 1건짜리만 받으면
        #     판매처명이 섞여 정확도가 3분의 2로 떨어졌다.
        status = check_brand(jp, kr_raw, clean_dict)
        if status == "unknown":
            name = x.get("name") or ""
            tr = x.get("translated_kr") or q.get("translated_kr") or ""
            if max(_sim_token(tr, name), _sim_bigram(tr, name)) < 0.7:
                continue
        elif status != "match":
            continue
        kr = PAREN_RE.sub(" ", kr_raw).strip()
        if kr:
            votes[jp][kr] += 1

    added, skipped = {}, Counter()
    for jp, counter in votes.items():
        kr, n = counter.most_common(1)[0]
        if len(alnum(jp)) < MIN_ALNUM_LEN:
            skipped["영문 4자 이하"] += 1
            continue
        if not HANGUL_RE.search(kr):
            skipped["대응값에 한글 없음"] += 1
            continue
        if n < MIN_OCCURRENCES:
            skipped["1건뿐(우연 가능)"] += 1
            continue
        if len(counter) > 1:
            # 대응이 갈리면 사람이 봐야 한다 — 자동으로 고르지 않는다.
            skipped["대응이 여러 갈래"] += 1
            continue
        added[jp] = kr

    print(f"[후보] 사전 없이 영문포함으로 통과한 브랜드 {len(votes)}종")
    for reason, n in skipped.most_common():
        print(f"  [제외] {reason}: {n}종")
    print(f"[등록 대상] {len(added)}종")
    for jp, kr in list(added.items())[:10]:
        print(f"  {jp} -> {kr}")

    if dry_run:
        print("[모의실행] 파일을 쓰지 않았다")
        return 0
    if not added:
        print("[변경 없음]")
        return 0

    brand_dict.update(added)
    Path(brand_dict_path).write_text(
        json.dumps(brand_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {brand_dict_path} — 총 {len(brand_dict)}개")
    return len(added)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    harvest(sys.argv[1], sys.argv[2],
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "data", "brand_translations_learned.json"),
            "--dry-run" in sys.argv)
