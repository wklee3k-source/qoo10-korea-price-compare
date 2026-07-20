"""
async_price_finder.py

권고사항 #16(async Playwright 전환) + #23(브라우저1개+컨텍스트N개 구조)를
합쳐서 구현. 지금까지는 병렬처리를 스레드로 했는데, 스레드마다 별도
브라우저 프로세스를 띄워서(threading in korea_price_finder.py의
batch_find_parallel) 메모리를 많이 먹었다. 외부 AI가 지적한 이상적인
구조는:

    브라우저 프로세스 1개
    ├── Context 1 (검색 1)
    ├── Context 2 (검색 2)
    ├── Context 3 (검색 3)
    └── Context 4 (검색 4)

브라우저 프로세스는 하나만 뜨고, 그 안에서 가벼운 컨텍스트(쿠키/세션이
분리된 탭 묶음)만 여러 개 만들어 동시에 돌리는 방식이라 스레드+개별
브라우저 방식보다 메모리와 기동속도 모두 유리하다. asyncio를 쓰면 이
구조를 자연스럽게 구현할 수 있다(동기 Playwright는 컨텍스트를 진짜
동시에 못 돌리고 순서대로 처리하게 된다).

사용법:
    python async_price_finder.py --batch <items_dir> <output.json> [<keywords_map.json>] [concurrency]

[실측 결과 — 솔직한 기록] 8건을 concurrency=4로 테스트했더니 90초에
4건만 처리됨(korea_price_finder.py의 스레드+개별브라우저 방식은 8건을
54초에 완료했었다). 구조적으로는 정상 작동하지만(원자적저장/재시도 다
잘 됨), 이 샌드박스 환경에서는 "브라우저 1개+컨텍스트 N개"가 "스레드
N개+브라우저 N개"보다 오히려 느렸다 — 리소스가 제한된 환경에서는
컨텍스트들이 하나의 브라우저 프로세스 내 리소스를 나눠 써서 병목이
생기는 것으로 추정된다. 리소스가 넉넉한 서버(예: 전용 VM)에서는
결과가 다를 수 있다. 그래서 지금은 기존 스레드 방식(batch_find_parallel)
을 기본으로 유지하고, 이 async 버전은 대안 옵션으로 남겨둔다.
"""

import asyncio
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

import korea_price_finder as danawa  # UA_POOL, parse_candidates, atomic_write_json 재사용


async def _search_one(context, keyword: str, max_results: int = 5) -> list[dict]:
    """컨텍스트 하나로 다나와 검색 1건을 수행한다(재시도 포함)."""
    url = f"https://search.danawa.com/dsearch.php?query={urllib.parse.quote(keyword)}"
    page = await context.new_page()
    delay = 1.0
    html = ""
    try:
        for attempt in range(1, 4):
            try:
                await page.goto(url, timeout=15000, wait_until="load")
                await asyncio.sleep(2.5)
                html = await page.content()
                break
            except Exception as e:  # noqa: BLE001
                if attempt < 3:
                    print(f"    [RETRY {attempt}/3] {e}", file=sys.stderr)
                    await asyncio.sleep(delay)
                    delay *= 2
    finally:
        await page.close()

    return danawa.parse_candidates(html, max_results) if html else []


async def batch_find_async(items_dir: str, out_path: str, keywords_map_path: str | None = None, concurrency: int = 4):
    out_file = Path(out_path)
    results = []
    done_goods_no = set()
    if out_file.exists():
        results = json.loads(out_file.read_text(encoding="utf-8"))
        done_goods_no = {r["goods_no"] for r in results}
        print(f"[RESUME] 이미 처리된 {len(done_goods_no)}건부터 이어서 진행")

    keywords_map = {}
    if keywords_map_path and Path(keywords_map_path).exists():
        keywords_map = json.loads(Path(keywords_map_path).read_text(encoding="utf-8"))

    all_items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(items_dir).glob("*.json"))]
    todo = [it for it in all_items if it.get("goods_no") not in done_goods_no]
    print(f"[INFO] 남은 상품 {len(todo)}건 / 전체 {len(all_items)}건 — 브라우저 1개 + 컨텍스트 {concurrency}개 동시처리")

    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)  # 동시에 뜨는 컨텍스트 수를 제한

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # 브라우저는 딱 1개만

        async def process(item):
            async with semaphore:
                goods_no = item.get("goods_no")
                brand = item.get("brand_name") or ""
                name = item.get("item_name") or ""
                keyword = keywords_map.get(goods_no) or f"{brand} {name}"[:60]

                context = await browser.new_context(user_agent=danawa.random_ua(), ignore_https_errors=True)
                try:
                    candidates = await _search_one(context, keyword)
                finally:
                    await context.close()  # 컨텍스트만 닫고 브라우저는 유지

                for c in candidates:
                    c["kr_site"] = "가격비교사이트 후보(danawa, async) — 실제 판매처/정가 여부 확인 필요"

                entry = {
                    "goods_no": goods_no,
                    "qoo10_name": name,
                    "brand_name": brand,
                    "keyword_used": keyword,
                    "candidates": candidates,
                }
                async with lock:
                    results.append(entry)
                    danawa.atomic_write_json(out_file, results)

                status = f"{len(candidates)}건" if candidates else "후보없음"
                print(f"[SEARCH] {goods_no}: {keyword} -> {status}")

        await asyncio.gather(*(process(item) for item in todo))
        await browser.close()

    print(f"\n[DONE] {len(results)}건 처리 완료 -> {out_path}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "--batch":
        print(__doc__)
        sys.exit(1)
    kw_map = sys.argv[4] if len(sys.argv) > 4 else None
    concurrency = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    asyncio.run(batch_find_async(sys.argv[2], sys.argv[3], kw_map, concurrency))


if __name__ == "__main__":
    main()
