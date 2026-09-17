from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

class OptionValuationInputInvalid(ValueError):
    """Authoritative valuation input is missing or invalid."""

@dataclass(frozen=True)
class Track4OptionValuationInput:
    """Minimal environment-neutral input contract for option valuation."""
    instrument_id: str
    observed_at: datetime
    underlying_price: Decimal
    option_price: Decimal
    strike: Decimal
    expiry: date
    time_to_expiry_years: Decimal
    implied_volatility: Decimal
    risk_free_rate: Decimal
    price_source: str
    iv_source: str
    risk_free_rate_source: str
    time_to_expiry_source: str

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise OptionValuationInputInvalid("instrument_id is required")
        if self.underlying_price <= 0:
            raise OptionValuationInputInvalid("underlying_price must be positive")
        if self.option_price < 0:
            raise OptionValuationInputInvalid("option_price must be non-negative")
        if self.strike <= 0:
            raise OptionValuationInputInvalid("strike must be positive")
        if self.time_to_expiry_years <= 0:
            raise OptionValuationInputInvalid("time_to_expiry_years must be positive")
        if self.implied_volatility <= 0:
            raise OptionValuationInputInvalid("implied_volatility must be positive")
        if not self.price_source:
            raise OptionValuationInputInvalid("price_source is required")
        if not self.iv_source:
            raise OptionValuationInputInvalid("iv_source is required")
        if not self.risk_free_rate_source:
            raise OptionValuationInputInvalid("risk_free_rate_source is required")
        if not self.time_to_expiry_source:
            raise OptionValuationInputInvalid("time_to_expiry_source is required")
