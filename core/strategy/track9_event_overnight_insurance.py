"""Strategy 9: end-of-day overnight strangle insurance.

The strategy is deliberately independent of macro/event/IV indicators. It buys an
ATM-ish PUT/CALL pair near the end of the session and uses the next session's
opening move as the only market-condition trigger for closing the insurance.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsStatus
from core.market.session_policy import MarketSessionPolicy
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track9State:
    entry_date: str | None = None
    entry_price: Decimal | None = None
    put_entry_price: Decimal | None = None
    call_entry_price: Decimal | None = None
    entry_premium: Decimal | None = None
    peak_profit: Decimal | None = None
    trailing_active: bool = False
    entry_qty: int = 0
    put_strike: Decimal | None = None
    call_strike: Decimal | None = None
    entered_today: bool = False
    closed_next_open: bool = False
    state: str = "WAITING_ENTRY"


class Track9EventOvernightInsurance:
    """Buy a PUT/CALL pair before close to insure the next session open."""

    strategy_id = "track9_event_overnight_insurance"
    version = "3.0"

    # KOSPI200 cash-session policy currently defines 15:30 as the close.
    # Strategy9 establishes its option-entry reference point 20 minutes before close: 15:10.
    ENTRY_TIME = time(15, 10)
    OPENING_WINDOW_END = MarketSessionPolicy.STABILIZATION_END

    # This is intentionally a strategy parameter, not an external indicator.
    # It can be tuned from REAL_VTS evidence without changing the strategy
    # dependency boundary.
    OPENING_SHOCK_THRESHOLD = Decimal("0.01")
    TRAILING_PROFIT_GIVEBACK = Decimal("0.30")

    def __init__(
        self,
        pair_quantity: int = 1,
        opening_shock_threshold: Decimal = OPENING_SHOCK_THRESHOLD,
    ) -> None:
        if pair_quantity <= 0:
            raise ValueError("PAIR_QUANTITY_MUST_BE_POSITIVE")
        if opening_shock_threshold <= 0:
            raise ValueError("OPENING_SHOCK_THRESHOLD_MUST_BE_POSITIVE")
        self.pair_quantity = pair_quantity
        self.opening_shock_threshold = opening_shock_threshold
        self.state = Track9State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track9State()

    @staticmethod
    def _requirement(key: str) -> StrategyFeatureRequirement:
        return StrategyFeatureRequirement(
            key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE})
        )

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        # Strategy9 intentionally depends only on the underlying price/time
        # needed to execute its own overnight insurance lifecycle.
        return (
            self._requirement("price.last"),
            self._requirement("options.atm_call_strike"),
            self._requirement("options.atm_put_strike"),
            self._requirement("options.contract_multiplier"),
            self._requirement("options.track9_put_mark_price"),
            self._requirement("options.track9_call_mark_price"),
        )

    @staticmethod
    def _metric(context: StrategyContext, key: str):
        if context.analytics is None:
            return None
        metric = context.analytics.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    def _sync_date(self, date_str: str) -> None:
        if self.state.entry_date is not None and self.state.entry_date != date_str:
            # A new trading day starts with the previous overnight position
            # still eligible for the opening insurance exit.
            self.state = replace(self.state, closed_next_open=False)

    def _sync_filled_entry(self, context: StrategyContext) -> None:
        """Promote only same-day VSSF FILLED prices into the strategy state."""
        if self.state.entry_date is None or self.state.entry_premium is not None:
            return
        put_entry = self._metric(context, "options.track9_put_entry_price")
        call_entry = self._metric(context, "options.track9_call_entry_price")
        multiplier = self._metric(context, "options.contract_multiplier")
        if put_entry is None or call_entry is None or multiplier is None:
            return
        if put_entry <= 0 or call_entry <= 0 or multiplier <= 0:
            return
        entry_premium = (
            (Decimal(str(put_entry)) + Decimal(str(call_entry)))
            * Decimal(self.state.entry_qty)
            * Decimal(str(multiplier))
        )
        self.state = replace(
            self.state,
            put_entry_price=Decimal(str(put_entry)),
            call_entry_price=Decimal(str(call_entry)),
            entry_premium=entry_premium,
            state="OVERNIGHT_INSURANCE_ACTIVE",
        )

    def _enter_signal(self, context: StrategyContext) -> Sequence[Signal]:
        common = context.input.common if context.input else None
        if common is None or common.time_str is None or common.date_str is None:
            return ()
        if self.state.entered_today:
            return ()
        if common.time_str < MarketSessionPolicy.text(self.ENTRY_TIME):
            return ()

        price = self._metric(context, "price.last")
        put = self._metric(context, "options.atm_put_strike")
        call = self._metric(context, "options.atm_call_strike")
        multiplier = self._metric(context, "options.contract_multiplier")
        if price is None or put is None or call is None or multiplier is None:
            return ()
        if multiplier <= 0 or put <= 0 or call <= 0:
            return ()

        qty = self.pair_quantity
        self.state = Track9State(
            entry_date=common.date_str,
            entry_price=Decimal(str(price)),
            put_entry_price=None,
            call_entry_price=None,
            entry_premium=None,
            peak_profit=Decimal("0"),
            trailing_active=False,
            entry_qty=qty,
            put_strike=Decimal(str(put)),
            call_strike=Decimal(str(call)),
            entered_today=True,
            closed_next_open=False,
            state="OVERNIGHT_INSURANCE_AWAITING_FILLS",
        )

        return (
            Signal(
                self.strategy_id,
                "ENTER_OVERNIGHT_STRANGLE_PUT",
                1.0,
                f"ENTRY:15:10;PUT:{put};CALL:{call};QTY:{qty};MULTIPLIER:{multiplier}",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=qty,
                    asset_type="OPTION",
                    side="BUY",
                    track_id=self.strategy_id,
                    tag_id="OVERNIGHT_INSURANCE_PUT",
                    option_type="PUT",
                    strike=put,
                ),
            ),
            Signal(
                self.strategy_id,
                "ENTER_OVERNIGHT_STRANGLE_CALL",
                1.0,
                f"ENTRY:15:10;PUT:{put};CALL:{call};QTY:{qty};MULTIPLIER:{multiplier}",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=qty,
                    asset_type="OPTION",
                    side="BUY",
                    track_id=self.strategy_id,
                    tag_id="OVERNIGHT_INSURANCE_CALL",
                    option_type="CALL",
                    strike=call,
                ),
            ),
        )

    def _close_pair_signals(self, *, reason: str, action: str = "CLOSE_OVERNIGHT_INSURANCE") -> Sequence[Signal]:
        if self.state.put_strike is None or self.state.call_strike is None or self.state.entry_qty <= 0:
            return ()
        return (
            Signal(self.strategy_id, f"{action}_PUT", 1.0, reason,
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.state.entry_qty, asset_type="OPTION", requested_price=None, side="SELL",
                    track_id=self.strategy_id, tag_id=f"{action}_PUT", option_type="PUT", strike=self.state.put_strike)),
            Signal(self.strategy_id, f"{action}_CALL", 1.0, reason,
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.state.entry_qty, asset_type="OPTION", requested_price=None, side="SELL",
                    track_id=self.strategy_id, tag_id=f"{action}_CALL", option_type="CALL", strike=self.state.call_strike)),
        )

    def _close_next_open(self, context: StrategyContext) -> Sequence[Signal]:
        common = context.input.common if context.input else None
        if common is None or common.time_str is None or common.date_str is None:
            return ()
        if (
            self.state.entry_date is None
            or self.state.entry_price is None
            or self.state.entry_premium is None
            or self.state.peak_profit is None
        ):
            return ()
        if common.date_str == self.state.entry_date or self.state.closed_next_open:
            return ()
        if common.time_str > MarketSessionPolicy.text(self.OPENING_WINDOW_END):
            return ()

        price = self._metric(context, "price.last")
        put_mark = self._metric(context, "options.track9_put_mark_price")
        call_mark = self._metric(context, "options.track9_call_mark_price")
        multiplier = self._metric(context, "options.contract_multiplier")
        if price is None or price <= 0 or put_mark is None or call_mark is None or multiplier is None:
            return ()
        if put_mark <= 0 or call_mark <= 0 or multiplier <= 0:
            return ()

        opening_move = (
            Decimal(str(price)) - self.state.entry_price
        ) / self.state.entry_price
        shock = abs(opening_move) >= self.opening_shock_threshold

        current_value = (
            (Decimal(str(put_mark)) + Decimal(str(call_mark)))
            * Decimal(self.state.entry_qty)
            * Decimal(str(multiplier))
        )
        current_profit = current_value - self.state.entry_premium

        if not self.state.trailing_active and shock and current_profit > 0:
            self.state = replace(
                self.state,
                peak_profit=current_profit,
                trailing_active=True,
                state="OPENING_INSURANCE_TRAILING",
            )
        elif self.state.trailing_active:
            peak_profit = max(self.state.peak_profit, current_profit)
            self.state = replace(self.state, peak_profit=peak_profit)

            trailing_floor = peak_profit * (Decimal("1") - self.TRAILING_PROFIT_GIVEBACK)
            if current_profit <= trailing_floor:
                close_signals = self._close_pair_signals(
                    reason=f"OPENING_SHOCK:{opening_move};CURRENT_PROFIT:{current_profit};PEAK_PROFIT:{peak_profit};TRAILING_FLOOR:{trailing_floor};GIVEBACK:{self.TRAILING_PROFIT_GIVEBACK};REASON:OPTION_PAIR_TRAILING_PROFIT"
                )
                self.state = replace(
                    self.state,
                    entry_date=common.date_str,
                    entry_price=None,
                    put_entry_price=None,
                    call_entry_price=None,
                    entry_premium=None,
                    peak_profit=None,
                    trailing_active=False,
                    entry_qty=0,
                    put_strike=None,
                    call_strike=None,
                    entered_today=False,
                    closed_next_open=True,
                    state="OPENING_INSURANCE_TRAILING_CLOSED",
                )
                return close_signals

        if not shock and not self.state.trailing_active:
            close_signals = self._close_pair_signals(
                reason=f"OPENING_MOVE:{opening_move};THRESHOLD:{self.opening_shock_threshold};REASON:NO_OPENING_SHOCK",
                action="STOP_LOSS_OVERNIGHT_INSURANCE",
            )
            self.state = replace(
                self.state,
                entry_date=common.date_str,
                entry_price=None,
                put_entry_price=None,
                call_entry_price=None,
                entry_premium=None,
                peak_profit=None,
                trailing_active=False,
                entry_qty=0,
                entered_today=False,
                closed_next_open=True,
                state="OPENING_NO_SHOCK_STOPPED",
            )
            return close_signals

        if common.time_str == MarketSessionPolicy.text(self.OPENING_WINDOW_END) and not self.state.trailing_active:
            close_signals = self._close_pair_signals(
                reason=f"OPENING_SHOCK:{opening_move};CURRENT_PROFIT:{current_profit};REASON:TRAILING_PROFIT_NOT_ACTIVATED",
                action="STOP_LOSS_OVERNIGHT_INSURANCE",
            )
            self.state = replace(
                self.state,
                entry_date=common.date_str,
                entry_price=None,
                put_entry_price=None,
                call_entry_price=None,
                entry_premium=None,
                peak_profit=None,
                trailing_active=False,
                entry_qty=0,
                entered_today=False,
                closed_next_open=True,
                state="OPENING_INSURANCE_TRAILING_UNACTIVATED_STOPPED",
            )
            return close_signals

        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        self._sync_filled_entry(context)
        return self._close_next_open(context) + self._enter_signal(context)


__all__ = ("Track9EventOvernightInsurance", "Track9State")
