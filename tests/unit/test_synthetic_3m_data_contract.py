from datetime import date, datetime
from decimal import Decimal

import pytest

from scripts.generate_authoritative_option_synthetic_3m import (
    Calendar,
    add_calendar_months,
    contract_multiplier_from_master_row,
    MULTIPLIER_SPEC_SOURCE,
    option_valuation,
    round_option_price,
    session_bar_count,
    trading_days_between,
)


def test_three_calendar_month_horizon_clamps_short_months():
    assert add_calendar_months(date(2026, 9, 18), 3) == date(2026, 12, 18)
    assert add_calendar_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_krx_regular_and_last_trading_day_sessions():
    assert session_bar_count(date(2026, 9, 18), monthly_last_trading_day=False) == 84
    assert session_bar_count(date(2026, 10, 8), monthly_last_trading_day=True) == 79


def test_horizon_uses_krx_calendar_and_excludes_weekends_and_holidays():
    calendar = Calendar({date(2026, 10, 5), date(2026, 10, 9)})
    days = trading_days_between(calendar, date(2026, 10, 2), date(2026, 10, 13))
    assert days == [
        date(2026, 10, 2),
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
        date(2026, 10, 12),
    ]


def test_option_theoretical_value_and_time_value_decay_with_fixed_market_inputs():
    expiry = date(2026, 10, 8)
    morning = option_valuation(1100.0, 1100.0, expiry, datetime(2026, 10, 7, 10, 0), 0.20, "CALL")
    afternoon = option_valuation(1100.0, 1100.0, expiry, datetime(2026, 10, 7, 14, 0), 0.20, "CALL")
    assert morning[3] > afternoon[3] > 0
    assert morning[0] >= afternoon[0]
    assert morning[2] >= afternoon[2]


def test_option_valuation_rejects_quotes_after_last_trading_cutoff():
    with pytest.raises(RuntimeError, match="OPTION_QUOTE_AFTER_LAST_TRADING_CUTOFF"):
        option_valuation(1100.0, 1100.0, date(2026, 10, 8), datetime(2026, 10, 8, 15, 21), 0.20, "CALL")


@pytest.mark.parametrize("price", [0.01, 0.09, 9.99, 10.0, 10.02, 10.07, 21.24])
def test_option_quote_prices_align_to_krx_tick_size(price):
    rounded = round_option_price(price)
    assert rounded > 0
    step = Decimal("0.05") if Decimal(str(rounded)) >= Decimal("10") else Decimal("0.01")
    assert (Decimal(str(rounded)) / step) == (Decimal(str(rounded)) / step).to_integral_value()


def test_contract_multiplier_uses_explicit_master_field_and_records_provenance():
    multiplier, source = contract_multiplier_from_master_row({"ISU_CD": "REGULAR", "CONTRACT_MULTIPLIER": "250000"})
    assert multiplier == Decimal("250000")
    assert source == "KRX_OPTION_MASTER_FIELD:CONTRACT_MULTIPLIER"


def test_contract_multiplier_blocks_master_spec_mismatch():
    with pytest.raises(RuntimeError, match="OPTION_MASTER_MULTIPLIER_SPEC_MISMATCH"):
        contract_multiplier_from_master_row({"CONTRACT_MULTIPLIER": "50000"})


def test_contract_multiplier_blocks_invalid_and_conflicting_master_fields():
    with pytest.raises(RuntimeError, match="OPTION_MASTER_MULTIPLIER_INVALID"):
        contract_multiplier_from_master_row({"CONTRACT_MULTIPLIER": "0"})
    with pytest.raises(RuntimeError, match="OPTION_MASTER_MULTIPLIER_FIELDS_CONFLICT"):
        contract_multiplier_from_master_row({"CONTRACT_MULTIPLIER": "250000", "MULTIPLIER": "50000"})


def test_missing_daily_snapshot_multiplier_uses_named_exchange_spec_source():
    multiplier, source = contract_multiplier_from_master_row({"ISU_CD": "REGULAR", "PROD_NM": "KOSPI200"})
    assert multiplier == Decimal("250000")
    assert source == MULTIPLIER_SPEC_SOURCE
