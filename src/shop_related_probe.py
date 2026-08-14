"""shop_related_probe.py — 큐텐 상점페이지에 "관련 상점" 링크가 실제로
있는지, 있다면 어떤 구조인지 조사한다.

[배경] 수확(harvest)은 발굴이 이미 찾은 상점만 재방문하는 구조라,
스스로 새 상점을 못 찾는다. 상점페이지 안에 다른 상점으로 가는 링크
(예: "이 판매자의 다른 상품", "추천 상점" 같은 것)가 있다면, 그걸
따라가서 발굴이 아직 못 찾은 새 상점을 발견하는 완전히 새로운 경로가
될 수 있다.

이게 실제로 있는지 이 대화 환경에서는 직접 못 봤다(데이터센터 IP
차단으로 페이지 접속 자체가 막힘 — 이전에 겪은 것과 같은 패턴).
GitHub Actions는 harvest_full_catalog가 이미 정상적으로 이 페이지를
여는 곳이라 결과가 다를 수 있다.

주소를 미리 정해놓고 셀렉터를 추측해서 코드부터 짜지 않는다 — 실제
페이지의 링크(href)를 전부 걷어서 파일로 남긴 뒤, 그 결과를 보고
"관련 상점처럼 보이는 패턴"이 있는지 사람이 눈으로 판단한다.

아무것도 바꾸지 않는 조사 전용 스크립트다. 실행 결과(JSON)만 만든다.

사용법:
    python shop_related_probe.py <shop_id_1> [<shop_id_2> ...]
"""
import json
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def probe_shop(shop_id: str) -> dict:
    """이 상점페이지에 있는 링크를 전부 걷어서, 자기 자신이 아닌
    '다른 상점'을 가리키는 것으로 보이는 것만 따로 추린다.

    큐텐 상점 URL 패턴이 /shop/<id> 형태라는 것만 이미 안다(harvest가
    이미 이 패턴으로 접속중). 그 외 어떤 링크가 있는지는 모르므로
    "href에 /shop/ 이 들어있고 자기 shop_id가 아닌 것"이라는 가장
    느슨한 기준으로 전부 모은다 — 진짜 '관련상점'인지는 사람이
    최종 판단한다.
    """
    url = f"https://www.qoo10.jp/shop/{shop_id}?search_mode=basic"
    result = {"shop_id": shop_id, "url": url, "status": None,
              "total_links": 0, "other_shop_links": [], "sample_all_hrefs": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=20000, wait_until="load")
            time.sleep(3)
            result["status"] = "ok"
        except Exception as e:  # noqa: BLE001
            result["status"] = f"실패: {e}"
            browser.close()
            return result

        try:
            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))"
            )
        except Exception as e:  # noqa: BLE001
            result["status"] = f"링크수집 실패: {e}"
            browser.close()
            return result

        browser.close()

    hrefs = [h for h in hrefs if h]
    result["total_links"] = len(hrefs)
    result["sample_all_hrefs"] = hrefs[:40]  # 전체 구조 파악용 샘플

    other_shops = set()
    for h in hrefs:
        if "/shop/" not in h:
            continue
        try:
            path = urlparse(h).path
        except Exception:  # noqa: BLE001
            continue
        parts = [p for p in path.split("/") if p]
        if "shop" not in parts:
            continue
        idx = parts.index("shop")
        if idx + 1 >= len(parts):
            continue
        other_id = parts[idx + 1]
        if other_id and other_id != shop_id:
            other_shops.add(h)
    result["other_shop_links"] = sorted(other_shops)[:30]

    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: python shop_related_probe.py <shop_id_1> [<shop_id_2> ...]")
        return 1

    shop_ids = sys.argv[1:]
    results = []
    for shop_id in shop_ids:
        print(f"\n[조사] {shop_id}")
        r = probe_shop(shop_id)
        print(f"  상태: {r['status']}")
        print(f"  전체 링크 수: {r['total_links']}")
        print(f"  다른 상점으로 보이는 링크 수: {len(r['other_shop_links'])}")
        if r["other_shop_links"]:
            print(f"  샘플: {r['other_shop_links'][:5]}")
        results.append(r)
        time.sleep(2)

    out_path = "../output/shop_related_probe_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[완료] 결과 저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
