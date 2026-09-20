from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan
from contracts.analytics import AnalyticsStatus

@dataclass(frozen=True)
class Track8State:
    is_active: bool = False
    premium_spent: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    qty_call: int = 0
    qty_put: int = 0
    entry_date: str | None = None
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False
    hysteresis_hold_counter: int = 0

class Track8MacroRegimeMonthlyStrangle:
    strategy_id = "track8_macro_regime_monthly_strangle"
    version = "2.0"
    DTE_ENTRY = Decimal("15")
    MIN_BUDGET = Decimal("200000")
    PROFIT_TARGET = Decimal("300000")

    def __init__(self, profit_target: Decimal = PROFIT_TARGET):
        self.profit_target = profit_target
        self.state = Track8State()

    def initialize(self, context: StrategyContext) -> None: self.reset()
    def on_market_state(self, context: StrategyContext) -> None: return None
    def reset(self) -> None: self.state = Track8State()

    @staticmethod
    def _m(snapshot, key):
        metric = snapshot.get(key)
        return None if metric is None or metric.status is not AnalyticsStatus.AVAILABLE else metric.value

    def feature_requirements(self):
        return tuple(self._requirement(k) for k in (
            "options.dte", "options.call_iv", "options.put_iv", "options.atm_iv",
            "options.call_strike", "options.put_strike", "options.call_contract_multiplier",
            "options.put_contract_multiplier", "options.moneyness", "market.current_regime",
            "volatility.active", "portfolio.current_pnl", "portfolio.total_fees",
            "portfolio.net_pnl", "portfolio.margin_ratio", "risk.guard_active"))

    @staticmethod
    def _requirement(key):
        from core.strategy.contracts import StrategyFeatureRequirement
        return StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))

    def _analytics(self, context):
        return context.analytics

    def evaluate_entry(self, context: StrategyContext) -> Sequence[Signal]:
        a = self._analytics(context)
        if a is None or self.state.is_active: return ()
        dte, budget, regime = self._m(a, "options.dte"), context.input.common.budget if context.input.common else None, self._m(a, "market.current_regime")
        call, put = self._m(a, "options.call_strike"), self._m(a, "options.put_strike")
        qcall, qput = self._m(a, "options.call_contract_multiplier"), self._m(a, "options.put_contract_multiplier")
        if not all(v is not None for v in (dte, budget, call, put, qcall, qput)) or dte < self.DTE_ENTRY or budget < self.MIN_BUDGET: return ()
        if qcall <= 0 or qput <= 0 or qcall != qput: return ()
        skew_qty = 2 if regime == "HIGH_VOL" else 1.5
        qty_call = 1
        qty_put = int(Decimal(str(qty_call)) * Decimal(str(skew_qty)))
        self.state = replace(self.state, is_active=True, premium_spent=Decimal("0"), call_strike=call, put_strike=put, qty_call=qty_call, qty_put=qty_put, entry_date=context.input.common.date_str)
        return (Signal(self.strategy_id, "BUY_LIMIT_TRANCHE", 1.0, f"DTE:{dte};CALL:{call};PUT:{put};QTY_CALL:{qty_call};QTY_PUT:{qty_put};PRICING:MID_PRICE_OFFSET"),)

    def evaluate_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.is_active: return ()
        a = self._analytics(context); price = self._m(a, "price.last") if a else None
        if price is None: return ()
        m = a.get("options.moneyness")
        intrinsic = (abs(m.value["call_distance"]) + abs(m.value["put_distance"])) if m and m.status is AnalyticsStatus.AVAILABLE else None
        if intrinsic is None: return ()
        high = max(self.state.high_watermark_intrinsic, intrinsic)
        if high > 0 and intrinsic <= high * Decimal("0.85"):
            self.reset(); return (Signal(self.strategy_id, "TAKE_PROFIT_HYBRID_TRAILING_STOP", 1.0, f"INTRINSIC_PROXY:{intrinsic};HIGH:{high}"),)
        self.state = replace(self.state, high_watermark_intrinsic=high, trailing_stop_active=True)
        return (Signal(self.strategy_id, "UPDATE_TRAILING", 0.9, f"HIGH:{high}"),) if high > self.state.high_watermark_intrinsic else ()

    def evaluate_macro_regime_protection(self, context: StrategyContext) -> Sequence[Signal]:
        a = self._analytics(context); regime = self._m(a, "market.current_regime") if a else None
        return (Signal(self.strategy_id, "MACRO_HEDGE_SCALE_UP", 1.0, f"REGIME:{regime};HEDGE_MULTIPLIER:1.5"),) if regime in {"HIGH_VOL", "CIRCUIT_BREAKER", "CRASH"} else ()

    def evaluate_profit_rebuild(self, context: StrategyContext) -> Sequence[Signal]:
        a = self._analytics(context)
        if a is None or not self.state.is_active or self._m(a, "risk.guard_active") is True or (self._m(a, "portfolio.margin_ratio") or Decimal("1")) > Decimal("0.85"): return ()
        if (self._m(a, "portfolio.net_pnl") or Decimal("0")) < self.profit_target: return ()
        return (Signal(self.strategy_id, "DYNAMIC_PROFIT_TAKE", 1.0, f"NET_PNL:{self._m(a,'portfolio.net_pnl')}"), Signal(self.strategy_id, "DYNAMIC_REBUILD_FENCE", 1.0, "REBUILD_REQUIRES_AUTHORITATIVE_OPTION_SELECTION"))

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.is_active: return ()
        a = self._analytics(context); dte = self._m(a, "options.dte") if a else None
        time_str = a.as_of.strftime("%H:%M:%S")
        if "15:15" <= time_str < "15:20": return (Signal(self.strategy_id, "CANCEL_PENDING_TRANCHES", 1.0, "15:15_CANCEL_PENDING_TRANCHES"),)
        if dte is None or dte > Decimal("4"): return ()
        return (Signal(self.strategy_id, "HOLD_LONG_ATTACK", 0.9, "D4_D0_MONEYNESS_OR_IV_EXPANSION"),)

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.call_strike <= 0 or self.state.put_strike <= 0: return None
        return build_pair_plan(group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_ENTRY", put_strike=self.state.put_strike, call_strike=self.state.call_strike, put_quantity=self.state.qty_put, call_quantity=self.state.qty_call, side="BUY")

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None: return ()
        return self.evaluate_entry(context) + self.evaluate_macro_regime_protection(context) + self.evaluate_take_profit(context) + self.evaluate_profit_rebuild(context) + self.evaluate_expiry_cutoff(context)
