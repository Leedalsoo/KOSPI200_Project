"""S6-specific immutable rule data; values intentionally mirror the current implementation."""
from dataclasses import dataclass
from decimal import Decimal

from core.market.session_policy import MarketSessionPolicy


@dataclass(frozen=True)
class S6Rules:
    vol_trigger_multiplier: Decimal = Decimal("1.3")
    trailing_volatility_boundary: Decimal = Decimal("1.3")
    trailing_activation_below_boundary: Decimal = Decimal("1.5")
    trailing_activation_at_or_above_boundary: Decimal = Decimal("2.0")
    trailing_retain_ratio_high: Decimal = Decimal("0.90")
    trailing_retain_ratio_middle: Decimal = Decimal("0.88")
    trailing_retain_ratio_low: Decimal = Decimal("0.85")
    trailing_ratio_high_boundary: Decimal = Decimal("2")
    trailing_ratio_middle_boundary: Decimal = Decimal("1.3")
    watermark_update_ratio: Decimal = Decimal("1.01")
    take_profit_suppression_time: str = "15:12:00"
    limit_cutoff: str = MarketSessionPolicy.text(MarketSessionPolicy.LIMIT_CUTOFF)
    market_cutoff: str = MarketSessionPolicy.text(MarketSessionPolicy.MARKET_CUTOFF)
    pending_cancel_end: str = MarketSessionPolicy.text(MarketSessionPolicy.PENDING_CANCEL_END)


S6_RULES = S6Rules()