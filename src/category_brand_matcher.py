"""
category_brand_matcher.py

자동화 영역: EditItemList 업로드에 필요한 category_number / brand_number를
참조 데이터(data/brand_list.csv, data/qoo10_category_info.csv)에서 조회한다.

이 모듈은 "정확히 일치하는 이름"에 대해서만 자동 매칭한다. 일치하는 항목이
없거나 여러 개인 경우 후보 목록을 반환하며, 최종 선택은 AI/사람이 판단해야 한다
(README의 "AI가 봐야 하는 영역" 참고).

사용법:
    from category_brand_matcher import BrandCategoryMatcher

    m = BrandCategoryMatcher("data/brand_list.csv", "data/qoo10_category_info.csv")
    m.find_brand("ROUND LAB")          # -> [{"brand_no": ..., "title": ...}, ...]
    m.find_category("스킨케어", "크림")  # -> [{"code": ..., "path": ...}, ...]
"""

import csv
from pathlib import Path


class BrandCategoryMatcher:
    def __init__(self, brand_csv: str, category_csv: str):
        self.brands = self._load_brands(brand_csv)
        self.categories = self._load_categories(category_csv)

    @staticmethod
    def _load_brands(path: str) -> list[dict]:
        rows = []
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    {
                        "brand_no": row.get("Brand No.", "").strip(),
                        "title": row.get("Brand Title", "").strip(),
                        "english": row.get("English", "").strip(),
                        "japanese": row.get("Japanese", "").strip(),
                    }
                )
        return rows

    @staticmethod
    def _load_categories(path: str) -> list[dict]:
        rows = []
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    {
                        "대카테고리_코드": row.get("대카테고리 코드", "").strip(),
                        "대카테고리_명": row.get("대카테고리 명", "").strip(),
                        "중카테고리_코드": row.get("중카테고리 코드", "").strip(),
                        "중카테고리_명": row.get("중카테고리 명", "").strip(),
                        "소카테고리_코드": row.get("소카테고리 코드", "").strip(),
                        "소카테고리_명": row.get("소카테고리 명", "").strip(),
                    }
                )
        return rows

    @staticmethod
    def _normalize(s: str) -> str:
        return s.strip().lower().replace(" ", "")

    def find_brand(self, name: str) -> list[dict]:
        """영문/일문/한글 브랜드명 중 하나라도 정확히 일치하면 후보로 반환한다."""
        target = self._normalize(name)
        matches = []
        for b in self.brands:
            candidates = [b["title"], b["english"], b["japanese"]]
            if any(self._normalize(c) == target for c in candidates if c):
                matches.append(b)
        return matches

    def find_category(self, *keywords: str) -> list[dict]:
        """대/중/소카테고리 명에 주어진 키워드가 모두 포함되는 소카테고리를 반환한다."""
        norm_keywords = [self._normalize(k) for k in keywords if k]
        matches = []
        for c in self.categories:
            haystack = self._normalize(
                c["대카테고리_명"] + c["중카테고리_명"] + c["소카테고리_명"]
            )
            if all(k in haystack for k in norm_keywords):
                matches.append(c)
        return matches


if __name__ == "__main__":
    import sys

    data_dir = Path(__file__).resolve().parent.parent / "data"
    m = BrandCategoryMatcher(
        str(data_dir / "brand_list.csv"), str(data_dir / "qoo10_category_info.csv")
    )

    if len(sys.argv) < 2:
        print("사용법: python category_brand_matcher.py brand <이름> | category <키워드...>")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "brand":
        for r in m.find_brand(sys.argv[2]):
            print(r)
    elif mode == "category":
        for r in m.find_category(*sys.argv[2:]):
            print(r)
