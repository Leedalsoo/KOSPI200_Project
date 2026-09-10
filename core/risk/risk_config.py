"""Standard risk threshold configuration."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Any


@dataclass(frozen=True)
class RiskConfig:
    """Standard risk threshold configuration.

    Decision thresholds use Decimal as the authoritative configuration
    contract. Constructor compatibility is preserved for valid int/float/string
    inputs by normalizing them once at the configuration boundary.

    Invalid numeric configuration is rejected at construction time so it cannot
    reach runtime risk decisions.
    """

    max_order_qty: int = 50
    max_daily_loss_krw: Decimal = Decimal("10000000")
    max_margin_utilization_ratio: Decimal = Decimal("0.85")
    max_position_per_instrument: int = 100
    vol_spike_threshold_multiplier: Decimal = Decimal("1.30")
    margin_diet_active: bool = False
    account_stale_timeout_sec: float = 30.0
    position_stale_timeout_sec: float = 30.0

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if value is None or isinstance(value, bool):
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_REQUIRED")
        try:
            normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_INVALID") from exc
        if not normalized.is_finite():
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED")
        return normalized

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field}_POSITIVE_INT_REQUIRED")
        return value

    @staticmethod
    def _nonnegative_timeout(value: Any, field: str) -> float:
        if value is None or isinstance(value, bool):
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED")
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED") from exc
        if not math.isfinite(normalized) or normalized < 0:
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED")
        return normalized

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_order_qty",
            self._positive_int(self.max_order_qty, "MAX_ORDER_QTY"),
        )
        object.__setattr__(
            self,
            "max_position_per_instrument",
            self._positive_int(
                self.max_position_per_instrument,
                "MAX_POSITION_PER_INSTRUMENT",
            ),
        )

        daily_loss = self._decimal(self.max_daily_loss_krw)
        margin_ratio = self._decimal(self.max_margin_utilization_ratio)
        vol_multiplier = self._decimal(self.vol_spike_threshold_multiplier)

        if daily_loss <= 0:
            raise ValueError("MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED")
        if not Decimal("0") < margin_ratio <= Decimal("1"):
            raise ValueError("MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED")
        if vol_multiplier <= 0:
            raise ValueError("VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED")
        if not isinstance(self.margin_diet_active, bool):
            raise ValueError("MARGIN_DIET_ACTIVE_BOOL_REQUIRED")

        object.__setattr__(self, "max_daily_loss_krw", daily_loss)
        object.__setattr__(
            self,
            "max_margin_utilization_ratio",
            margin_ratio,
        )
        object.__setattr__(
            self,
            "vol_spike_threshold_multiplier",
            vol_multiplier,
        )
        object.__setattr__(
            self,
            "account_stale_timeout_sec",
            self._nonnegative_timeout(
                self.account_stale_timeout_sec,
                "ACCOUNT_STALE_TIMEOUT_SEC",
            ),
        )
        object.__setattr__(
            self,
            "position_stale_timeout_sec",
            self._nonnegative_timeout(
                self.position_stale_timeout_sec,
                "POSITION_STALE_TIMEOUT_SEC",
            ),
        )
