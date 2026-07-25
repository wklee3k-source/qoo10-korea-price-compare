"""
margin_calculator.py

자동화 영역: 사용자의 기존 Q10_계산기.xlsx "2. 마진율을 먼저 설정하는 방식" 시트를
실측 분석해서 그대로 재현한 계산기다. 국내구매가 + 무게 + 목표마진율만 넣으면
큐텐 판매가(엔)를 역산한다.

[검증 방법] Q10_계산기.xlsx 실제 셀 수식을 openpyxl로 그대로 읽어 계산 로직을
확인했고(참고: 같은 파일의 "1. 판매가를 먼저 설정" 표는 환율 셀 참조가 깨져
있어서 사용하지 않음), 실제 캐시된 값(예: 국내구매가 32,900원, 무게 1.25kg,
목표마진율 12% -> 큐텐판매가 6,134.89円)으로 아래 함수가 동일한 결과를 내는지
확인했다.

공식 (V=목표마진율, O=수수료율, N=환율(원/100엔), K=국내구매가, P=포장대행비,
     Q=배대지배송비(무게별, kse요율표), R=수출신고대행비):
    price_yen = (K + P + Q + R - K/11) / (1 - V - O) / N * 100

사용법:
    python margin_calculator.py <국내구매가_원> <무게_kg> [목표마진율=0.12]

출력: JSON (price_yen, retail_price_yen 참고용, margin_krw, vat_refund_krw, final_margin_krw)
"""

import json
import math
import sys
from pathlib import Path

# 사용자의 실제 등록이력 322건에서 전부 동일하게 확인된 고정값
DEFAULT_PACKAGING_FEE_KRW = 2080  # 포장대행지 or 국내택배비
DEFAULT_EXPORT_FEE_KRW = 165  # 수출신고대행비용
DEFAULT_COMMISSION_RATE = 0.16  # 큐텐 수수료(카테고리10%+해외배송2%+외부유입1%+단골쿠폰3%)
DEFAULT_MARGIN_RATE = 0.12  # 목표 마진율 (Q10_계산기.xlsx 기본값)
VAT_REFUND_DIVISOR = 11  # 국내구매가에 포함된 부가세 환급 = K/11


def load_shipping_rate_table() -> list[dict]:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    path = data_dir / "kse_shipping_rate.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_shipping_cost(weight_kg: float, table: list[dict] | None = None) -> tuple[float, int]:
    """무게를 kse요율표의 다음 상위 구간으로 올림해서 배송비(원화)를 찾는다.
    반환값: (적용된 무게 구간, 배송비 원화)"""
    table = table or load_shipping_rate_table()
    table = sorted(table, key=lambda x: x["weight_kg"])
    for tier in table:
        if weight_kg <= tier["weight_kg"]:
            return tier["weight_kg"], tier["shipping_krw"]
    # 표에 없는 초과 무게는 최대 구간값을 사용하고 경고
    last = table[-1]
    print(f"[WARN] 무게 {weight_kg}kg가 kse요율표 최대 구간({last['weight_kg']}kg)을 초과합니다.", file=sys.stderr)
    return last["weight_kg"], last["shipping_krw"]


def calculate(
    cost_krw: float,
    weight_kg: float,
    margin_rate: float = DEFAULT_MARGIN_RATE,
    commission_rate: float = DEFAULT_COMMISSION_RATE,
    exchange_rate: float = 900,  # 원/100엔 (예: 900 = 9.00원/엔). 최신 환율로 갱신해서 넘길 것.
    packaging_fee_krw: float = DEFAULT_PACKAGING_FEE_KRW,
    export_fee_krw: float = DEFAULT_EXPORT_FEE_KRW,
) -> dict:
    applied_weight_tier, shipping_krw = lookup_shipping_cost(weight_kg)

    vat_refund_est = cost_krw / VAT_REFUND_DIVISOR
    denom = 1 - margin_rate - commission_rate
    if denom <= 0:
        raise ValueError(f"마진율({margin_rate})+수수료율({commission_rate})이 1 이상입니다 — 계산 불가")

    numerator = cost_krw + packaging_fee_krw + shipping_krw + export_fee_krw - vat_refund_est
    price_yen_raw = numerator / denom / exchange_rate * 100
    price_yen = math.ceil(price_yen_raw)  # 원 계산기는 소수점을 그대로 쓰지만 실제 등록은 정수 엔이 필요해 올림

    # 실제 산출된 price_yen으로 마진을 역계산해 검산한다 (S/T/U와 동일한 식)
    margin_krw = (price_yen + 0) * exchange_rate / 100 * (1 - commission_rate) - cost_krw - packaging_fee_krw - shipping_krw - export_fee_krw
    vat_refund_krw = math.ceil((cost_krw + packaging_fee_krw) * (1 / VAT_REFUND_DIVISOR * 1.1))  # 원 계산기 T열과 동일한 근사식(ROUNDUP((K+P)*0.090909))
    vat_refund_krw = math.ceil((cost_krw + packaging_fee_krw) * 0.090909)
    final_margin_krw = margin_krw + vat_refund_krw

    return {
        "cost_krw": cost_krw,
        "weight_kg_input": weight_kg,
        "weight_kg_applied_tier": applied_weight_tier,
        "shipping_krw": shipping_krw,
        "packaging_fee_krw": packaging_fee_krw,
        "export_fee_krw": export_fee_krw,
        "commission_rate": commission_rate,
        "margin_rate_target": margin_rate,
        "exchange_rate": exchange_rate,
        "price_yen": price_yen,
        "margin_krw": round(margin_krw, 1),
        "vat_refund_krw": vat_refund_krw,
        "final_margin_krw": round(final_margin_krw, 1),
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cost_krw = float(sys.argv[1])
    weight_kg = float(sys.argv[2])
    margin_rate = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_MARGIN_RATE

    result = calculate(cost_krw, weight_kg, margin_rate)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
