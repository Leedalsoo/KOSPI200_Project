from datetime import date, timedelta
from decimal import Decimal

import pytest

from contracts.kis_option_product_spec import (
    KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
    KIS_MINI_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
    KIS_MONTHLY_OPTION_EXPIRY_RULE_ID,
    KIS_MONTHLY_OPTION_EXPIRY_SOURCE,
    KIS_OPTION_PRODUCT_SPEC_URL,
    calculate_kis_monthly_option_expiry,
    kis_option_contract_multiplier,
    kis_option_price_tick,
)
from core.option.option_master import parse_kis_fo_idx_mst_result


class _Calendar:
    def __init__(self, holidays=()):
        self.holidays = set(holidays)

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def prev_trading_day(self, value: date) -> date:
        candidate = value - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def trading_days_between(self, start: date, end: date) -> int:
        return sum(
            self.is_trading_day(date.fromordinal(n))
            for n in range(start.toordinal(), end.toordinal() + 1)
        )


def test_kis_standard_monthly_expiry_and_multiplier_come_from_official_product_spec():
    raw = "5|B01611887|KR4B016B8873|C 202611   887.5|3|00887.50| |2001|KOSPI200"
    result = parse_kis_fo_idx_mst_result(
        raw,
        _Calendar(),
        master_sha256="a" * 64,
    )
    identity = result.identities["B01611887"]

    assert identity.expiry == "20261112"
    assert identity.contract_multiplier == KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
    assert identity.contract_multiplier == Decimal("250000")
    assert identity.expiry_source == KIS_MONTHLY_OPTION_EXPIRY_SOURCE
    assert identity.expiry_endpoint == KIS_OPTION_PRODUCT_SPEC_URL
    assert identity.expiry_tr_id == KIS_MONTHLY_OPTION_EXPIRY_RULE_ID
    assert identity.expiry_master_sha256 == identity.master_sha256 == "a" * 64
    assert identity.expiry_response_sha256 is None


def test_kis_monthly_expiry_moves_to_previous_trading_day_when_second_thursday_is_holiday():
    calendar = _Calendar(holidays={date(2026, 11, 12)})
    assert calculate_kis_monthly_option_expiry("202611", calendar) == "20261111"


def test_kis_monthly_expiry_rejects_unbound_or_invalid_month_labels():
    with pytest.raises(ValueError, match="KIS_MONTHLY_OPTION_MONTH_LABEL_INVALID"):
        calculate_kis_monthly_option_expiry("2026-11", _Calendar())
    with pytest.raises(ValueError, match="KIS_MONTHLY_OPTION_MONTH_LABEL_INVALID"):
        calculate_kis_monthly_option_expiry("202613", _Calendar())


def test_kis_product_spec_separates_standard_and_mini_multipliers():
    assert kis_option_contract_multiplier("STANDARD") == Decimal("250000")
    assert kis_option_contract_multiplier("MINI") == Decimal("50000")
    assert KIS_MINI_KOSPI200_OPTION_CONTRACT_MULTIPLIER == Decimal("50000")
    with pytest.raises(ValueError, match="KIS_OPTION_INSTRUMENT_FAMILY_UNSUPPORTED"):
        kis_option_contract_multiplier("UNKNOWN")


def test_kis_option_premium_tick_uses_kis_thresholds():
    assert kis_option_price_tick("9.99") == Decimal("0.01")
    assert kis_option_price_tick("10.00") == Decimal("0.05")
    assert kis_option_price_tick("41.25") == Decimal("0.05")
    with pytest.raises(ValueError, match="KIS_OPTION_PREMIUM_INVALID"):
        kis_option_price_tick("-0.01")
