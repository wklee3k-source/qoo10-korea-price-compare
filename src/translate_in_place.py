"""
translate_in_place.py

1,2단계 통합: discover 워커가 상품을 발굴한 그 즉시, 같은 파일 안에서
바로 번역까지 끝낸다. 더 이상 별도 브랜치(translate-live)나 브랜치 간
아카이빙 조율이 필요 없다 — 각 워커의 discovery_state_<B>.json 안의
상품에 translated_kr 필드가 있으면 "번역완료", 없으면 "번역대기"인
것으로 그 파일 하나만 보면 전부 알 수 있다.

사용법:
    python translate_in_place.py <discovery_state_file.json>
        파일 안의 all_products 중 translated_kr이 없는 것만 찾아서
        Claude Haiku로 번역하고, 같은 필드를 채워서 같은 파일에 저장한다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_translate import translate_batch, validate_translation  # noqa: E402


def translate_in_place(state_path: str, brand_dict_path: str = "../data/brand_translations_learned.json", threshold: int = 100, max_items: int | None = None):
    path = Path(state_path)
    if not path.exists():
        print(f"[SKIP] {path} 없음")
        return

    state = json.loads(path.read_text(encoding="utf-8"))
    products = state.get("all_products", [])

    # 빈칸은 무조건 재번역 대상. 채워진 건 "명백히 나쁜 신호"(가나잔존/
    # 한글전무)만 재번역 대상으로 삼는다 — strict=False라서 길이검사는
    # 건너뛴다. 이미 확보한 정상 번역이 길이검사의 오탐 때문에 매 사이클
    # 다시 청구되는 낭비를 막기 위함(사용자 지시: "이미 번역된건 재시도
    # 안되게").
    to_translate = []
    for p in products:
        cur = p.get("translated_kr")
        if not cur:
            to_translate.append(p)
            continue
        ok, _ = validate_translation(p["title"], cur, strict=False)
        if not ok:
            to_translate.append(p)
    if not to_translate:
        print("[INFO] 새로 번역할 상품 없음")
        return
    if len(to_translate) < threshold:
        # [비용효율] 시스템프롬프트(약 400토큰)를 매번 반복 전송하는 게
        # 낭비이므로, threshold개 이상 모일 때까지 기다렸다가 한 번에
        # 번역한다 — 워커별로 독립적으로 판단하니 별도 동기화 없이도
        # "먼저 채운 워커부터 순서대로 번역"이 자연히 이뤄진다.
        print(f"[WAIT] {len(to_translate)}건 대기중(threshold={threshold} 미만, 더 모일 때까지 보류)")
        return

    print(f"[INFO] {len(to_translate)}건 신규 번역 대상")

    # [청크 처리 - 사용자 지적으로 도입] 예전엔 대기 중인 전량을 한 번의
    # 호출에서 다 번역하려 했다. 그래서 GitHub Actions 타임아웃(60분)에
    # 걸리면 커밋 전이라 전부 날아갔다(실측: 36분 넘게 돌았는데 저장 0건).
    # 이제 한 번에 max_items건만 처리하고 끝낸다 — 워크플로가 이걸
    # 반복 호출하면서 매번 커밋/푸시하므로, 중간에 잘려도 이미 커밋된
    # 만큼은 확실히 보존된다(hwahae_verify가 CHUNK로 쓰는 방식과 동일).
    if max_items is not None and len(to_translate) > max_items:
        to_translate = to_translate[:max_items]
        print(f"[INFO] 이번 호출에서는 {len(to_translate)}건만 처리(max_items={max_items})")

    try:
        brand_dict = json.loads(Path(brand_dict_path).read_text(encoding="utf-8"))
        brand_dict.pop("_설명", None)
        brand_dict.pop("_아도르_참고", None)
    except Exception:  # noqa: BLE001
        brand_dict = {}

    # [중대버그 수정] 예전엔 batch_size=len(items)로 전량을 한 통에 담아
    # 보냈다. 응답은 약 80건 분량에서 잘렸고, 잘린 뒤쪽은 '일본어 원문'으로
    # 채워진 뒤 "번역완료"로 취급돼 영영 재시도되지 않았다(실측 80.8% 오염).
    # 이제 auto_translate가 배치를 스스로 잘게 쪼개고, 검증 탈락분은 None을
    # 돌려준다. None은 필드를 건드리지 않고 비워둬서 다음 사이클에 재시도된다.
    items = [{"title": p["title"], "brand": p.get("brand", "")} for p in to_translate]

    # [중간저장 - 사용자 지적으로 수정] 예전엔 translate_batch가 전부
    # 끝난 뒤에야 파일을 썼다. 그래서 GitHub Actions 타임아웃(60분)에
    # 걸리면 그때까지 번역한 것 전부가 통째로 날아갔다(실측: 36분 넘게
    # 돌았는데 저장된 건 0건). 이제 배치 하나가 끝날 때마다 즉시
    # 파일에 반영해서, 중간에 잘려도 그때까지의 성과는 보존된다.
    def save_progress(partial_results):
        done_now = 0
        for p, t in zip(to_translate, partial_results):
            if t is None:
                continue  # 아직 안 됐거나 실패 — 빈칸으로 두면 다음에 재시도
            p["translated_kr"] = t
            p["known_brand"] = brand_dict.get(p.get("brand", ""), "")
            done_now += 1
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [중간저장] 누적 {done_now}/{len(to_translate)}건 -> {path}", flush=True)

    translated = translate_batch(items, on_batch_done=save_progress)

    done = 0
    for p, t in zip(to_translate, translated):
        if t is None:
            p.pop("translated_kr", None)  # 반드시 빈칸으로 남긴다
            continue
        p["translated_kr"] = t
        p["known_brand"] = brand_dict.get(p.get("brand", ""), "")
        done += 1

    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] {done}건 번역 완료 / {len(to_translate)-done}건 재시도 대기 -> {path}")


if __name__ == "__main__":
    state_arg = sys.argv[1] if len(sys.argv) > 1 else "../output/discovery_state.json"
    # 2번째 인자로 이번 호출 처리 상한(건수)을 받는다. 워크플로가 이걸
    # 주고 반복 호출하면서 매번 커밋해서, 타임아웃 유실을 막는다.
    max_items_arg = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].strip() else None
    translate_in_place(state_arg, max_items=max_items_arg)
