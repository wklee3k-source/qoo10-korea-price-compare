"""정확한 재현: hwahae_verify_batch.py의 실제 로직(3곳 검색+수량체크)을
그대로 흉내내서, 특정 goods_no가 왜 실패하는지 단계별로 출력한다."""
import json
import sys

sys.path.insert(0, ".")
from hwahae_verify_batch import _search_exa, _search_hwahae, _search_naver, _clean_query, _extract_quantity, _normalize_volume_ml

targets = [
    ("1182595010", "메디큐브 PDRN 핑크비타코팅마스크 10매"),
    ("1209471569", "pleuvoir 히노키레더 오드퍼퓸 30ml"),
    ("1196939883", "아비브 레티날아이세럼 리프팅롤러 15ml"),
    ("1211311608", "[공식판매처]광채탄력콜라겐100멜팅마스크 6매입"),
]

for goods_no, kw_raw in targets:
    print(f"=== {goods_no}: {kw_raw} ===")
    kw_cleaned = _clean_query(kw_raw)
    known_volume = ""
    m = _normalize_volume_ml(kw_raw)
    known_volume = f"{m}ml" if m else ""
    known_brand = ""

    cand_exa = _search_exa(kw_raw)
    print("  exa:", cand_exa.get("name") if cand_exa else None)

    cand_hwahae = _search_hwahae(kw_cleaned, known_volume, known_brand)
    print("  hwahae:", cand_hwahae.get("name") if cand_hwahae else None, "| brand:", cand_hwahae.get("brand") if cand_hwahae else None)

    cand_naver = _search_naver(kw_cleaned, known_brand)
    print("  naver(1차):", cand_naver.get("name") if cand_naver else None, "| product_url:", cand_naver.get("product_url") if cand_naver else None)

    if cand_naver:
        qoo10_qty = _extract_quantity(kw_raw)
        naver_qty = _extract_quantity(cand_naver.get("name") or "")
        print(f"  수량체크: 큐텐={qoo10_qty} vs 네이버={naver_qty}")
        if qoo10_qty != naver_qty:
            requery = f"{known_brand or (cand_hwahae and cand_hwahae.get('brand')) or ''} {kw_cleaned} 1개".strip()
            cand_naver_retry = _search_naver(requery, known_brand)
            retry_qty = _extract_quantity(cand_naver_retry.get("name") or "") if cand_naver_retry else None
            print(f"  재검색결과: {cand_naver_retry.get('name') if cand_naver_retry else None} | 재검색수량: {retry_qty}")
            if not (cand_naver_retry and retry_qty == qoo10_qty):
                print("  -> 네이버 후보 폐기됨(수량불일치)")
    print()
