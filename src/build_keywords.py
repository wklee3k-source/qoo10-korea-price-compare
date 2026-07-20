"""
build_keywords.py

큐텐 일본어 상품명을 한글 검색어로 자동 변환한다(100개 규모를 사람이
일일이 수동번역하는 건 비현실적이라 만든 헬퍼).

[방식] 완벽한 번역은 아니고, 화장품 카테고리에서 흔한 가타카나 외래어
("セラム"→세럼, "クリーム"→크림 등)를 사전으로 치환 + 브랜드명은
brand_db.py의 별칭 테이블로 치환 + 대괄호/프로모션 문구/단위 표기 등
잡음 제거. 완전 자동 번역이 아니라 "검색이 될 만큼만" 정리하는 게 목적.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brand_db

# 가타카나 화장품 용어 → 한글 (자주 나오는 것 위주)
JP_TO_KR = {
    "セラム": "세럼", "クリーム": "크림", "トナー": "토너", "マスク": "마스크",
    "エッセンス": "에센스", "アンプル": "앰플", "ローション": "로션",
    "クレンジング": "클렌징", "フォーム": "폼", "オイル": "오일",
    "パック": "팩", "スティック": "스틱", "パウダー": "파우더",
    "ファンデーション": "파운데이션", "クッション": "쿠션", "リップ": "립",
    "ティント": "틴트", "アイシャドウ": "아이섀도우", "アイライナー": "아이라이너",
    "サンクリーム": "선크림", "日焼け止め": "선크림", "ミスト": "미스트",
    "スプレー": "스프레이", "バーム": "밤", "ジェル": "젤",
    "シャンプー": "샴푸", "トリートメント": "트리트먼트", "ボディウォッシュ": "바디워시",
    "パッド": "패드", "シート": "시트", "ゲル": "젤",
    "美容液": "에센스", "化粧水": "스킨", "乳液": "로션",
    "洗顔": "클렌저", "日本公式": "", "国内発送": "", "公式": "",
}

BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")
SLASH_TAIL_RE = re.compile(r"\s*/.*$")  # 첫 슬래시(/) 이후는 보통 부가설명이라 제거


def translate_item_name(item_name: str) -> str:
    text = BRACKET_RE.sub(" ", item_name)  # 【】/[]/() 프로모션 문구 제거
    text = SLASH_TAIL_RE.sub("", text)  # 슬래시 이후 부가설명 제거
    for jp, kr in JP_TO_KR.items():
        text = text.replace(jp, kr)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_keyword(brand_name: str, item_name: str) -> str:
    entry = brand_db.lookup(brand_name)
    brand_kr = None
    if entry:
        # brand_db.py의 BRAND_KOREAN_NAME 없이도, fuzzy_match.py에 있는
        # 매핑을 재사용(모듈 임포트로 접근)
        try:
            import fuzzy_match
            canonical = brand_db.BRAND_NAME_ALIASES.get(brand_name.strip())
            brand_kr = fuzzy_match.BRAND_KOREAN_NAME.get(canonical)
        except Exception:  # noqa: BLE001
            pass
    brand_part = brand_kr or brand_name or ""
    name_part = translate_item_name(item_name)
    return f"{brand_part} {name_part}"[:60].strip()


def build_all(items_dir: str, out_path: str, limit: int | None = None):
    items = sorted(Path(items_dir).glob("*.json"))
    if limit:
        items = items[:limit]
    keywords = {}
    for p in items:
        d = json.loads(p.read_text(encoding="utf-8"))
        goods_no = d.get("goods_no")
        keywords[goods_no] = build_keyword(d.get("brand_name", ""), d.get("item_name", ""))
    Path(out_path).write_text(json.dumps(keywords, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] {len(keywords)}건 검색어 생성 -> {out_path}")
    return keywords


if __name__ == "__main__":
    items_dir = sys.argv[1] if len(sys.argv) > 1 else "../output/items"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "../output/keywords_100.json"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    build_all(items_dir, out_path, limit)
