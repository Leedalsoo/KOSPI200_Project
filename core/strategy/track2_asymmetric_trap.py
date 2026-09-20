"""Track2 asymmetric trap strategy.

Track2 consumes canonical Common Analytics features through StrategyContext.analytics.
Missing authoritative analytics remain unavailable and fail closed; strategy code owns
only Trap-specific rules, state transitions, and execution proposal construction.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import ClassVar, Sequence

from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_trap_plan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal



class Track2AsymmetricTrap:
    strategy_id: ClassVar[str] = "track2_asymmetric_trap"
    version: ClassVar[str] = "1.0"
    ENTRY_QUANTITY: ClassVar[int] = 1
    MAX_DAILY_ENTRIES = 2
    COOLDOWN = timedelta(minutes=15)
    MARKET_CUTOFF = time(15, 15)
    STOP_LOSS_RATIO = Decimal("-0.30")

    def __init__(self) -> None:
        self._trap_active = False
        self._entry_price: Decimal | None = None
        self._entry_instrument: str | None = None
        self._last_loss_at: datetime | None = None
        self._daily_entry_count = 0
        self._session_date: date | None = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at: datetime | None = None
        self._short_switched = False

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        if context.market_state is not None:
            self._session_date = context.market_state.as_of.date()

    def on_market_state(self, context: StrategyContext) -> None:
        if context.market_state is None:
            return
        current_date = context.market_state.as_of.date()
        if self._session_date != current_date:
            self._session_date = current_date
            self._daily_entry_count = 0

    def reset(self) -> None:
        self._trap_active = False
        self._entry_price = None
        self._entry_instrument = None
        self._last_loss_at = None
        self._daily_entry_count = 0
        self._session_date = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at = None
        self._short_switched = False

    def build_asymmetric_trap(
        self, current_atm: Decimal, active_vol: float, base_vol: float
    ) -> dict[str, object]:
        if active_vol <= base_vol * 0.85:
            return {
                "status": "ZERO_COST_WIDE_TRAP_SUCCESS",
                "trap_type": "ZERO_COST_10PT_WIDE",
                "pricing_mode": "MID_PRICE_OFFSET",
                "limit_offset_ticks": 1,
                "signals": [
                    {
                        "action": "EXECUTE_SHORT_LEG",
                        "strikes": {
                            "call": current_atm + Decimal("10.0"),
                            "put": current_atm - Decimal("10.0"),
                        },
                    },
                    {
                        "action": "EXECUTE_LONG_TRAP_LEG",
                        "strikes": {
                            "call": current_atm + Decimal("5.0"),
                            "put": current_atm - Decimal("5.0"),
                        },
                    },
                ],
            }
        return {
            "status": "GAMMA_PEAK_NARROW_TRAP_SUCCESS",
            "trap_type": "GAMMA_5PT_NARROW",
            "pricing_mode": "MID_PRICE_OFFSET",
            "limit_offset_ticks": 1,
            "signals": [
                {
                    "action": "EXECUTE_SHORT_LEG",
                    "strikes": {
                        "call": current_atm + Decimal("7.5"),
                        "put": current_atm - Decimal("7.5"),
                    },
                },
                {
                    "action": "EXECUTE_LONG_TRAP_LEG",
                    "strikes": {
                        "call": current_atm + Decimal("2.5"),
                        "put": current_atm - Decimal("2.5"),
                    },
                },
            ],
        }

    def build_execution_plan(
        self,
        group_id: str,
        current_atm: Decimal,
        active_vol: float,
        base_vol: float,
    ) -> MultiLegExecutionPlan:
        trap = self.build_asymmetric_trap(current_atm, active_vol, base_vol)
        short = trap["signals"][0]["strikes"]
        long = trap["signals"][1]["strikes"]
        return build_trap_plan(
            group_id=group_id,
            strategy_id=self.strategy_id,
            purpose=str(trap["trap_type"]),
            short_put=short["put"],
            short_call=short["call"],
            long_put=long["put"],
            long_call=long["call"],
            quantity=1,
        )

    def evaluate_trap(self, current_price: Decimal, now: datetime) -> Sequence[Signal]:
        if (
            self._short_switch_at is not None
            and now - self._short_switch_at >= self.COOLDOWN
        ):
            self._short_switch_at = None
            self._short_switched = False
            return (
                Signal(
                    self.strategy_id,
                    "FLAT",
                    1.0,
                    "SHORT_SWITCH_TIMEOUT_EXIT",
                ),
            )
        if (
            not self._trap_active
            or self._entry_price is None
            or self._entry_price <= 0
        ):
            return ()
        pnl = (current_price - self._entry_price) / self._entry_price
        if pnl <= self.STOP_LOSS_RATIO:
            self._last_loss_at = now
            self._trap_active = False
            self._entry_price = None
            self._high_pnl_ratio = Decimal("0")
            return (
                Signal(
                    self.strategy_id,
                    "FLAT",
                    1.0,
                    f"STOP_LOSS {pnl * 100:.1f}%",
                ),
            )
        self._high_pnl_ratio = max(self._high_pnl_ratio, pnl)
        if self._high_pnl_ratio >= Decimal("0.30"):
            trailing = (
                Decimal("0.90")
                if self._high_pnl_ratio >= Decimal("1.0")
                else Decimal("0.88")
                if self._high_pnl_ratio >= Decimal("0.50")
                else Decimal("0.85")
            )
            if pnl <= self._high_pnl_ratio * trailing:
                self._trap_active = False
                self._entry_price = None
                self._high_pnl_ratio = Decimal("0")
                self._short_switch_at = now
                self._short_switched = True
                return (
                    Signal(
                        self.strategy_id,
                        "SHORT",
                        1.0,
                        "TAKE_PROFIT_TRAILING_STOP",
                    ),
                )
        return ()

    def feature_requirements(self):
        from contracts.analytics import AnalyticsStatus
        from core.strategy.contracts import StrategyFeatureRequirement

        keys = (
            "volatility.bbw", "volume.z_score", "microstructure.obi",
            "futures.basis", "options.put_iv", "options.call_iv",
            "volume_profile.poc", "volatility.active", "volatility.base",
        )
        return tuple(
            StrategyFeatureRequirement(k, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for k in keys
        )

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        from contracts.analytics import AnalyticsStatus
        from core.strategy.contracts import validate_strategy_features

        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        metrics = validate_strategy_features(self.feature_requirements(), context.analytics)
        if any(m.status is not AnalyticsStatus.AVAILABLE or m.value is None for m in metrics):
            return ()
        values = {m.metric_key: m.value for m in metrics}
        now = context.market_state.as_of if context.market_state is not None else context.analytics.as_of
        tick = next(iter(context.market_state.ticks.values()), None) if context.market_state else None
        if tick is None:
            return ()
        if now.time() >= self.MARKET_CUTOFF or self._daily_entry_count >= self.MAX_DAILY_ENTRIES:
            return self.evaluate_trap(tick.price, now)
        if self._last_loss_at is not None and now - self._last_loss_at < self.COOLDOWN:
            return ()
        if not bool(values["volatility.bbw"]) or float(values["volume.z_score"]) <= 3.0:
            return ()
        obi = Decimal(str(values["microstructure.obi"]))
        basis = Decimal(str(values["futures.basis"]))
        put_iv = Decimal(str(values["options.put_iv"]))
        call_iv = Decimal(str(values["options.call_iv"]))
        poc_price = Decimal(str(values["volume_profile.poc"]))
        if abs(obi) <= Decimal("0.5") or basis <= Decimal("0.3"):
            return ()
        is_upward = tick.price > poc_price
        if (is_upward and put_iv >= call_iv) or (not is_upward and call_iv >= put_iv):
            return ()
        if abs(tick.price - poc_price) <= Decimal("1.0"):
            return ()
        active_vol = float(values["volatility.active"])
        base_vol = float(values["volatility.base"])
        self._trap_active = True
        self._entry_price = tick.price
        self._entry_instrument = tick.instrument_id
        self._high_pnl_ratio = Decimal("0")
        self._daily_entry_count += 1
        trap = self.build_asymmetric_trap(tick.price, active_vol, base_vol)
        short_put = trap["signals"][0]["strikes"]["put"]
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.ENTRY_QUANTITY,
            asset_type="OPTION",
            requested_price=None,
            side="SELL",
            track_id=self.strategy_id,
            tag_id="TRAP_PLAN",
            option_type="PUT",
            strike=short_put,
        )
        return (Signal(
            self.strategy_id,
            "LONG",
            1.0,
            "ASYMMETRIC_TRAP_ENTRY",
            execution_proposal=proposal,
        ),)
