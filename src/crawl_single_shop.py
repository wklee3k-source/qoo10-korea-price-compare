"""
crawl_single_shop.py

crawl_shop_best5(shop_id)를 별도 프로세스로 격리해서 실행한다. 결과는
JSON으로 stdout에 출력한다.

[왜 이렇게 하는가] 기존에는 같은 프로세스 안에서 signal.alarm(90)으로
상점 하나당 시간제한을 걸었는데, 실측으로 이게 신뢰할 수 없다는 게
확인됐다 — Playwright의 페이지 로딩 예외처리 도중 signal이 전달되지
않고 프로세스가 3시간 넘게 완전히 멈춰버린 사례가 있었다. subprocess로
격리하면, 호출하는 쪽(부모 프로세스)이 `subprocess.run(timeout=N)`으로
확실하게 SIGKILL을 보낼 수 있다 — 자식 프로세스 내부에서 무슨 일이
일어나든(시그널이 씹히든 뭐든) 운영체제 수준에서 강제 종료되므로 100%
확실하다.

사용법:
    python crawl_single_shop.py <shop_id>
    -> stdout에 JSON 배열(상품 리스트) 출력, 실패시 빈 배열 "[]"
"""

import json
import sys

sys.path.insert(0, ".")
from iterative_low_review_discovery import crawl_shop_best5  # noqa: E402


if __name__ == "__main__":
    shop_id = sys.argv[1]
    try:
        products = crawl_shop_best5(shop_id)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] {shop_id}: {type(e).__name__}: {e}", file=sys.stderr)
        products = []
    print(json.dumps(products, ensure_ascii=False))
