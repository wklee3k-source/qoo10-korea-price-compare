"""
jp_kr_translator.py

일본어 상품명을 한글로 "대충 추측 번역"한다. 완벽한 번역이 목적이 아니라
hwahae_name_corrector.py가 검색해서 정답을 찾아낼 수 있을 만큼만
근접하면 된다(실측 확인: 화해는 추측이 조금 틀려도 검색만 되면 정확한
정식명칭을 알려준다 — "퐁퐁"이라고 잘못 추측해도 "뽀용"이 검색결과에
나옴).

가타카나 화장품 공통어휘 사전 치환 + 브랜드명 사전 매핑을 사용한다.
"""

import re

# 가타카나 화장품 용어 → 한글
JP_TERM_TO_KR = {
    "セラム": "세럼", "クリーム": "크림", "トナー": "토너", "マスク": "마스크",
    "エッセンス": "에센스", "アンプル": "앰플", "ローション": "로션",
    "クレンジング": "클렌징", "フォーム": "폼", "オイル": "오일",
    "パック": "팩", "スティック": "스틱", "パウダー": "파우더",
    "ファンデーション": "파운데이션", "クッション": "쿠션", "リップ": "립",
    "ティント": "틴트", "アイシャドウ": "아이섀도우", "アイライナー": "아이라이너",
    "サンクリーム": "선크림", "ミスト": "미스트", "スプレー": "스프레이",
    "バーム": "밤", "ジェル": "젤", "シャンプー": "샴푸",
    "トリートメント": "트리트먼트", "ボディウォッシュ": "바디워시",
    "パッド": "패드", "シート": "시트", "洗顔": "클렌저",
    "毛穴": "모공", "保湿": "보습", "美容液": "에센스", "化粧水": "스킨",
    "乳液": "로션", "弾力": "탄력", "水分": "수분", "低刺激": "저자극",
    "大容量": "대용량", "正規品": "정품", "韓国コスメ": "한국화장품",
    "ニキビケア": "여드름케어", "ヘアケア": "헤어케어", "頭皮": "두피",
    "抜け毛": "탈모", "乾燥肌": "건성피부",
}

# 가타카나 브랜드명 → 한글 정식 표기(이 프로젝트에서 실제 확인한 것들)
JP_BRAND_TO_KR = {
    "リジュラン": "리쥬란", "ダルバ": "달바", "バイオヒールボ": "바이오힐보",
    "VTコスメティックス": "VT코스메틱", "セルフュージョンC": "셀퓨전씨",
    "ヘラ": "헤라", "ミジャンセン": "미장센", "アヌア": "아누아",
    "セリマックス": "셀리맥스", "イージーデュー": "이지듀",
    "アトラス": "아틀라스", "エステラ": "에스트라", "ヘトラス": "헤트라스",
}

VOLUME_RE = re.compile(r"[\d.]+\s*(?:ml|g|枚|個|本)(?:[×xX+][\d.]+\s*(?:ml|g|個|箱|セット))*")
BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")


def guess_translate(brand_ja: str, title_ja: str) -> dict:
    """일본어 브랜드명+상품명을 한글로 대충 추측 번역한다.
    반환값: {"brand_kr": ..., "core_kr": ..., "volume": ...}"""
    brand_kr = JP_BRAND_TO_KR.get(brand_ja, brand_ja)  # 사전에 없으면 원문 그대로(영문 브랜드 등)

    text = BRACKET_RE.sub(" ", title_ja)
    text = re.split(r"\s*/", text)[0]

    vol_match = VOLUME_RE.search(text)
    volume = vol_match.group() if vol_match else ""
    if vol_match:
        text = text[: vol_match.start()] + " " + text[vol_match.end():]

    for jp, kr in JP_TERM_TO_KR.items():
        text = text.replace(jp, kr)

    text = re.sub(r"\s+", " ", text).strip()
    return {"brand_kr": brand_kr, "core_kr": text, "volume": volume}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python jp_kr_translator.py "<브랜드 일본어>" "<상품명 일본어>"')
        sys.exit(1)
    result = guess_translate(sys.argv[1], sys.argv[2])
    print(result)
