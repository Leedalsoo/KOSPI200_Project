from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from contracts.track4_option_valuation_input import (
OptionValuationInputInvalid,
# Track4OptionValuationInput,
)

def valid_input() -> Track4OptionValuationInput:
    return Track4OptionValuationInput(
        instrument_id="OPT-1",
        observed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        underlying_price=Decimal("350"),
        option_price=Decimal("5.2"),
        strike=Decimal("350"),
        expiry=date(2026, 9, 10),
        time_to_expiry_years=Decimal("0.0109589"),
        implied_volatility=Decimal("0.25"),
        risk_free_rate=Decimal("0.03"),
        price_source="authoritative-market-price",
        iv_source="authoritative-iv-source",
        risk_free_rate_source="authoritative-rate-source",
        time_to_expiry_source="authoritative-time-convention",
    )

def test_valid_valuation_input_is_immutable_contract():
    value = valid_input()
    assert value.instrument_id == "OPT-1"
    assert value.implied_volatility == Decimal("0.25")

def test_missing_iv_source_fails_closed():
    with pytest.raises(OptionValuationInputInvalid, match="iv_source"):
        pass
        Track4OptionValuationInput(**{**valid_input().__dict__, "iv_source": ""})

def test_invalid_valuation_numbers_fail_closed():
    with pytest.raises(OptionValuationInputInvalid, match="time_to_expiry_years"):
        pass
        Track4OptionValuationInput(**{**valid_input().__dict__, "time_to_expiry_years": Decimal("0")})
