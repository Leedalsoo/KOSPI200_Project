"""Standard Strategy registry manifest."""
from __future__ import annotations

from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping
from core.strategy.track5_gap_divergence import Track5GapDivergence
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance

STANDARD_STRATEGY_TYPES = (
    Track1TailDefense,
    Track2AsymmetricTrap,
    Track3StatisticalArbitrage,
    Track4GammaScalping,
    Track5GapDivergence,
    Track6DailyTailInsurance,
    Track7VolatilitySkewWeeklyInsurance,
    Track8MacroRegimeMonthlyStrangle,
    Track9EventOvernightInsurance,
)

STANDARD_STRATEGY_KEYS = tuple(
    (strategy_type.strategy_id, strategy_type.version)
    for strategy_type in STANDARD_STRATEGY_TYPES
)

STANDARD_STRATEGY_IDS = tuple(
    strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
)


def build_standard_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy_type in STANDARD_STRATEGY_TYPES:
        registry.register(strategy_type())
    return registry
