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
from auto_translate import translate_batch  # noqa: E402


def translate_in_place(state_path: str, brand_dict_path: str = "../data/brand_translations_learned.json"):
    path = Path(state_path)
    if not path.exists():
        print(f"[SKIP] {path} 없음")
        return

    state = json.loads(path.read_text(encoding="utf-8"))
    products = state.get("all_products", [])

    to_translate = [p for p in products if not p.get("translated_kr")]
    if not to_translate:
        print("[INFO] 새로 번역할 상품 없음")
        return

    print(f"[INFO] {len(to_translate)}건 신규 번역 시작")

    try:
        brand_dict = json.loads(Path(brand_dict_path).read_text(encoding="utf-8"))
        brand_dict.pop("_설명", None)
        brand_dict.pop("_아도르_참고", None)
    except Exception:  # noqa: BLE001
        brand_dict = {}

    titles = [p["title"] for p in to_translate]
    translated = translate_batch(titles, batch_size=15)

    for p, t in zip(to_translate, translated):
        p["translated_kr"] = t
        p["known_brand"] = brand_dict.get(p.get("brand", ""), "")

    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] {len(to_translate)}건 번역 완료 -> {path}")


if __name__ == "__main__":
    translate_in_place(sys.argv[1] if len(sys.argv) > 1 else "../output/discovery_state.json")
