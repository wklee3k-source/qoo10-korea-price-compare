import json
import sys

sys.path.insert(0, ".")
from hwahae_verify_batch import _search_exa, _search_hwahae, _search_naver, _clean_query, _extract_quantity, _normalize_volume_ml

targets = [
    ("1190755588", "바이오콜라겐리얼딥마스크,8매"),
    ("1212606720", "콜라겐젤리세럼미스트,50ml"),
    ("1211961274", "밸런스풀아젤라익애씨드세럼,30ml"),
    ("1200827735", "5번백옥글루타치온100xTXA10집중토닝에센스"),
    ("1210345860", "하트브러시콤팩트헤어브러시"),
]

for goods_no, kw_raw in targets:
    print(f"=== {goods_no}: {kw_raw} ===")
    kw_cleaned = _clean_query(kw_raw)
    m = _normalize_volume_ml(kw_raw)
    known_volume = f"{m}ml" if m else ""
    known_brand = ""

    cand_exa = _search_exa(kw_raw)
    print("  exa:", cand_exa.get("name") if cand_exa else None)

    cand_hwahae = _search_hwahae(kw_cleaned, known_volume, known_brand)
    print("  hwahae:", cand_hwahae.get("name") if cand_hwahae else None)

    cand_naver = _search_naver(kw_cleaned, known_brand)
    print("  naver(1차):", cand_naver.get("name") if cand_naver else None, "| url:", cand_naver.get("product_url") if cand_naver else None)

    if cand_naver:
        qoo10_qty = _extract_quantity(kw_raw)
        naver_qty = _extract_quantity(cand_naver.get("name") or "")
        print(f"  수량체크: 큐텐={qoo10_qty} vs 네이버={naver_qty}")
        if qoo10_qty != naver_qty:
            requery = f"{kw_cleaned} 1개".strip()
            cand_naver_retry = _search_naver(requery, known_brand)
            retry_qty = _extract_quantity(cand_naver_retry.get("name") or "") if cand_naver_retry else None
            print(f"  재검색: {cand_naver_retry.get('name') if cand_naver_retry else None} | 재검색수량: {retry_qty}")
    print()
