"""
brand_db.py

브랜드 DB 조회 — 검색 없이 브랜드의 공식 채널 URL을 바로 가져온다.

[배경] 외부 AI 리뷰에서 "화장품 브랜드는 500개도 안 되니 한 번만
브랜드→공식채널 DB를 만들어두면 이후엔 검색이 아예 필요없다"는 제안을
받고 실제로 만들었다. 지금까지 이 프로젝트에서 실측으로 확인한 26개
브랜드의 공식몰 URL을 `data/brand_db.json`에 저장해뒀다.

큐텐 상품의 brand_name은 일본어 가타카나("イニスフリー")나 영문
("Dr.twentyproject") 등 표기가 제각각이라, 이 파일은 그 다양한 표기를
brand_db.json의 정규화된 key로 매핑하는 역할을 한다.
"""

import json
from pathlib import Path

BRAND_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "brand_db.json"
CAPABILITY_PATH = Path(__file__).resolve().parent.parent / "data" / "source_capability.json"

# 큐텐에서 실제로 관측된 brand_name 표기(일본어/영문/한글) -> brand_db.json의 key
BRAND_NAME_ALIASES = {
    "celimax": "celimax",
    "セリマックス": "celimax",
    "Sung Boon Editor": "sungboon",
    "GROWUS": "growus",
    "ヘアプラス": "hairplus",
    "HAIRPLUS": "hairplus",
    "ロベクチン": "rovectin",
    "ROVECTIN": "rovectin",
    "KAHI": "kahi",
    "イニスフリー": "innisfree",
    "innisfree": "innisfree",
    "ラネージュ": "laneige",
    "LANEIGE": "laneige",
    "COSRX": "cosrx",
    "バニラコ": "banilaco",
    "BANILACO": "banilaco",
    "VTコスメティックス": "vt-cosmetics",
    "VT코스메틱": "vt-cosmetics",
    "フィジオジェル": "physiogel",
    "PHYSIOGEL": "physiogel",
    "Dr.twentyproject": "dr20project",
    "ドクタートゥエンティプロジェクト": "dr20project",
    "サムバイミー": "somebymi",
    "SOME BY MI": "somebymi",
    "manyo": "manyo",
    "마녀공장": "manyo",
    "ティルティル": "tirtir",
    "TIRTIR": "tirtir",
    "メイクプレム": "makeprem",
    "make prem": "makeprem",
    "SISTER ANN": "sister-ann",
    "hince": "hince",
    "힌스": "hince",
    "Biodance": "biodance",
    "바이오던스": "biodance",
    "セルフュージョンC": "cellfusionc",
    "셀퓨전씨": "cellfusionc",
    "PIBUMI": "pibumi",
    "frankly": "frankly",
    "프랭클리": "frankly",
    "エイプリルスキン": "aprilskin",
    "에이프릴스킨": "aprilskin",
    "リジュラン": "pdrnmall",
    "리쥬란": "pdrnmall",
    "メディキューブ": "medicube",
    "메디큐브": "medicube",
}


def _load_db() -> dict:
    return json.loads(BRAND_DB_PATH.read_text(encoding="utf-8"))


def _load_capability() -> dict:
    return json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))


def lookup(qoo10_brand_name: str) -> dict | None:
    """큐텐 brand_name(일본어/영문 등)으로 brand_db.json 항목을 바로 찾는다.
    없으면 None을 반환 — 그러면 호출한 쪽에서 무신사/다나와 검색으로 넘어가면 된다."""
    if not qoo10_brand_name:
        return None
    key = BRAND_NAME_ALIASES.get(qoo10_brand_name.strip())
    if not key:
        return None
    db = _load_db()
    return db.get(key)


def searchable_channels(qoo10_brand_name: str) -> dict:
    """이 브랜드에 대해 '실제로 자동 조회 가능한' 채널만 골라서 반환한다.
    source_capability.json의 search=true인 채널의 URL만 포함되고,
    oliveyoung/naver_brand처럼 URL은 있지만 이 환경에서 403인 채널은
    'reference_only'로 따로 분류해서 사람 검수용 링크로만 넘긴다."""
    entry = lookup(qoo10_brand_name)
    if not entry:
        return {"searchable": {}, "reference_only": {}}

    cap = _load_capability()
    searchable = {}
    reference_only = {}

    if entry.get("official"):
        target = searchable if cap.get("official", {}).get("search") else reference_only
        target["official"] = entry["official"]

    if entry.get("musinsa"):
        target = searchable if cap.get("musinsa", {}).get("search") else reference_only
        target["musinsa"] = "musinsa_finder.py로 검색"

    naver = entry.get("naver_brand") or {}
    if naver.get("exists") and naver.get("url"):
        target = searchable if cap.get("naver_brand", {}).get("search") else reference_only
        target["naver_brand"] = naver["url"]

    oy = entry.get("oliveyoung") or {}
    if oy.get("exists") and oy.get("url"):
        target = searchable if cap.get("oliveyoung", {}).get("search") else reference_only
        target["oliveyoung"] = oy["url"]

    return {"searchable": searchable, "reference_only": reference_only}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python brand_db.py <큐텐 brand_name>")
        sys.exit(1)
    result = lookup(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2) if result else "DB에 없음 — 검색 필요")
