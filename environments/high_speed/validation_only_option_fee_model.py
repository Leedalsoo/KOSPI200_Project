"""Validation-only KOSPI200 option fee reference model.

Reference: KIS standard branch-account online domestic derivatives schedule.
This is a synthetic benchmark, not an assertion about a user's negotiated account rate.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

MODEL_ID = "KIS_STANDARD_BRANCH_ONLINE_KOSPI200_OPTION_2025_10_27"
SOURCE_URL = "https://securities.koreainvestment.com/main/customer/guide/_static/TF04ae010000.jsp?tab=1"
TAX_SOURCE_URL = "https://securities.koreainvestment.com/main/customer/guide/_static/TF04ae050000.shtm"

BROKER_RATE_BELOW_10M = Decimal("0.00382900")
BROKER_RATE_AT_LEAST_10M = Decimal("0.00282900")
EXCHANGE_RATE = Decimal("0.00012654")
LOW_PRICE_THRESHOLD = Decimal("0.42")
HIGH_PRICE_THRESHOLD = Decimal("2.47")
LOW_PRICE_FIXED_EXCHANGE_FEE_KRW = Decimal("13")
HIGH_PRICE_FIXED_EXCHANGE_FEE_KRW = Decimal("78")
TEN_MILLION_KRW = Decimal("10000000")


def calculate_option_fee(premium_points, contract_multiplier_krw, quantity=1) -> dict[str, Decimal | int | str]:
    premium = Decimal(str(premium_points))
    multiplier = Decimal(str(contract_multiplier_krw))
    qty = int(quantity)
    if premium <= 0 or multiplier <= 0 or qty <= 0:
        raise ValueError("SYNTHETIC_OPTION_FEE_INPUT_MUST_BE_POSITIVE")

    notional = premium * multiplier * qty
    broker_rate = BROKER_RATE_BELOW_10M if notional < TEN_MILLION_KRW else BROKER_RATE_AT_LEAST_10M
    broker_fee = notional * broker_rate

    if premium < LOW_PRICE_THRESHOLD:
        tier = "BELOW_0_42_POINT"
        exchange_fee = LOW_PRICE_FIXED_EXCHANGE_FEE_KRW * qty
    elif premium < HIGH_PRICE_THRESHOLD:
        tier = "0_42_TO_BELOW_2_47_POINT"
        exchange_fee = notional * EXCHANGE_RATE
    else:
        tier = "2_47_POINT_AND_ABOVE"
        exchange_fee = HIGH_PRICE_FIXED_EXCHANGE_FEE_KRW * qty

    raw_total = broker_fee + exchange_fee
    total_rounded = int(raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {
        "model_id": MODEL_ID,
        "tier": tier,
        "notional_krw": notional,
        "broker_rate": broker_rate,
        "brokerage_fee_raw_krw": broker_fee,
        "exchange_fee_raw_krw": exchange_fee,
        "total_fee_raw_krw": raw_total,
        "total_fee_krw": total_rounded,
        "rounding": "ROUND_HALF_UP_PER_EXECUTION",
        "tax_krw": 0,
    }
