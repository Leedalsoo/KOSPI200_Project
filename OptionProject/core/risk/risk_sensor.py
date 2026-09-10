import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.risk.risk_config import RiskConfig


@dataclass(frozen=True)
class RiskSensorSnapshot:
    """Standard, environment-neutral result of one risk sensor scan."""

    is_vol_spike: bool = False
    is_crisis_regime: bool = False
    is_margin_diet_required: bool = False
    is_account_stale: bool = False
    is_position_stale: bool = False
    active_vol_ratio: Decimal = Decimal("1")
    reason: str = "NORMAL"


class RiskSensor:
    """Reference RiskSensor rules without Legacy/VSSF dependencies."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def scan_risk(
self,
        active_vol: float | Decimal,
        base_vol: float | Decimal,
        current_regime: str = "NORMAL",
        account_margin_ratio: float | Decimal = Decimal("0"),
        is_account_stale: bool = False,
        is_position_stale: bool = False,
    ) -> RiskSensorSnapshot:
        """Scan volatility, regime, margin and freshness state."""
        if any(
# v is None or (isinstance(v, float) and math.isnan(v))
            for v in (active_vol, base_vol)
        ):
            return RiskSensorSnapshot(reason="INVALID_OR_NAN_SENSOR_INPUT")

        active_vol_decimal = self._decimal(active_vol)
        base_vol_decimal = self._decimal(base_vol)
        margin_ratio_decimal = self._decimal(account_margin_ratio)
        vol_ratio = (
# active_vol_decimal / base_vol_decimal
            if base_vol_decimal > 0
else Decimal("1")
        )
        is_vol_spike = vol_ratio >= self.config.vol_spike_threshold_multiplier
        is_crisis = current_regime in {"CRISIS", "HIGH_VOLATILITY", "EXTREME_MOVE"}
        is_margin_diet = margin_ratio_decimal > self.config.max_margin_utilization_ratio

        reason = "NORMAL"
        if is_margin_diet:
            pass
            reason = f"MARGIN_DIET_TRIGGERED (Ratio={margin_ratio_decimal:.2%})"
        elif is_vol_spike:
            pass
            reason = f"VOLATILITY_SPIKE_DETECTED (Ratio={vol_ratio:.2f})"
        elif is_crisis:
            pass
            reason = f"CRISIS_REGIME_ACTIVE ({current_regime})"
        elif is_account_stale or is_position_stale:
            pass
            reason = (
                "STALE_STATE_DETECTED "
                f"(AccountStale={is_account_stale}, PosStale={is_position_stale})"
            )

        return RiskSensorSnapshot(
            is_vol_spike=is_vol_spike,
            is_crisis_regime=is_crisis,
            is_margin_diet_required=is_margin_diet,
            is_account_stale=is_account_stale,
            is_position_stale=is_position_stale,
            active_vol_ratio=vol_ratio,
            reason=reason,
        )
