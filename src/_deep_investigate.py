"""심층조사: 최근 실패건 20개를 실제 파이프라인 함수 그대로 재현해서
진짜 성공/실패 여부를 정확히 확인한다."""
import json
import sys

sys.path.insert(0, ".")
from hwahae_verify_batch import _search_exa, _search_hwahae, _search_naver, _clean_query, _extract_quantity, _normalize_volume_ml

queries = json.loads('''[["1210417855", "[신작한정발매]유니콘과기사의향수바니가든시리즈스트로베리큐피드프래그런스향수딸기잼향퍼퓸아토마이저높은부향률매력적인향선물"], ["1181192539", "[토니모리]원더세라마이드모찌토너500ml/에이징케어/저자극/탱글탱글"], ["1168004689", "퍼퓸샴푸+린스세트[스위트파라워리/프레시러쉬/바이올렛/그린릴리/화이트데이지]윤기영양보습수분향수샴푸부드러운모발한국인기샴푸"], ["960305004", "다프트앤도프트퍼퓸드바디로션엔젤코튼2개300ml"], ["943904657", "타이거밤넥앤숄더크림50g1개입"], ["1208942440", "마데카크림미스트,120ml"], ["1208942269", "마데카크림타임리버스제로,80ml"], ["1195929409", "익스퍼트마데카멜라캡처앰플프로30ml"], ["1200523478", "셀메이징콜라겐젤마스크,10매"], ["1203428079", "페이스팩,시트마스크대용량개별포장,비타민C히알루론산에센스마스크,시원한냉감모공케어,여름용시원한스킨케어,아침팩페이스마스크"], ["1190966589", "15매세트앰플페이스마스크시트마스크개별포장에센스마스크[히알루론산비타민C골드에센스]초박밀착시트데일리팩보습팩페이스팩"], ["1133988984", "센티드핸드크림40ml/한국화장품/퍼퓸핸드크림"], ["1132391030", "아토베리어365크림80ml"], ["1203692533", "한국헤어케어데미지테라피노워시트리트먼트EX250ml로즈머스크향230℃열보호7종콜라겐안씻어내는아웃배스드라이기전케어한국살롱케어"], ["1141188697", "[5+5]로얄블랙스네일앰플마스크10매"], ["1209834072", "[1+1]저분자콜라겐아이마사지앰플15ml x2개"], ["1205657917", "선뮤즈톤업&코렉팅피치핑크선스크린SPF50+PA++++50ml x1개"], ["1207151859", "펩타리프팅앰플마스크1매입15개"], ["1207151738", "X5오라이트레티놀앰플1개250ml"], ["1207185783", "알로에에센스마스크팩1개입50개"]]''')

success_count = 0
for goods_no, kw_raw in queries:
    kw_cleaned = _clean_query(kw_raw)
    m = _normalize_volume_ml(kw_raw)
    known_volume = f"{m}ml" if m else ""
    known_brand = ""

    try:
        cand_exa = _search_exa(kw_raw)
    except Exception as e:
        cand_exa = None
        print(f"  [EXA오류] {goods_no}: {e}")

    try:
        cand_hwahae = _search_hwahae(kw_cleaned, known_volume, known_brand)
    except Exception as e:
        cand_hwahae = None
        print(f"  [화해오류] {goods_no}: {e}")

    try:
        cand_naver = _search_naver(kw_cleaned, known_brand)
    except Exception as e:
        cand_naver = None
        print(f"  [네이버오류] {goods_no}: {e}")

    final_url = None
    if cand_naver:
        qoo10_qty = _extract_quantity(kw_raw)
        naver_qty = _extract_quantity(cand_naver.get("name") or "")
        if qoo10_qty == naver_qty:
            final_url = cand_naver.get("product_url")
        else:
            requery = f"{kw_cleaned} 1개".strip()
            try:
                retry = _search_naver(requery, known_brand)
            except Exception:
                retry = None
            if retry and _extract_quantity(retry.get("name") or "") == qoo10_qty:
                final_url = retry.get("product_url")

    status = "성공" if final_url else "실패"
    if final_url:
        success_count += 1
    print(json.dumps({"goods_no": goods_no, "query": kw_raw[:40], "status": status, "final_url": final_url}, ensure_ascii=False))

print(f"### 총 {success_count}/{len(queries)}건 지금 재현하면 성공")
