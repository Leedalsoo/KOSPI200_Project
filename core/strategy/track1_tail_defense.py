from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, Strategy, StrategyContext, StrategyPayload
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.instrument.strike_rules import round_to_strike_tick
from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


@dataclass(frozen=True)
class Track1Input(StrategyPayload):
    strategy_id: str = "TRACK1_TAIL_DEFENSE"
    momentum_confirmed: bool = False
    days_to_expiry: float | None = None
    current_time: datetime | None = None
    active_vol: float | None = None
    base_vol: float | None = None
    coverage_ratio: float | None = None
    short_option_net_delta: Decimal | None = None


@dataclass
class Track1State:
    base_price: float | None = None
    fence_distance: float = 7.5
    active_fence_type: str | None = None
    active_fence_strike: float | None = None
    active_fence_tag: int = 0
    futures_hedge_count: int = 0
    hedge_count_date: date | None = None
    active_hedge: str | None = None
    hedge_entry_price: float | None = None
    active_hedge_quantity: int = 0
    profit_buffer: float = 0.0
    market_opened: bool = False


class Track1TailDefense(Strategy):
    """Track 1 Tail Defense를 Standard Strategy Contract로 이식한 상태기계."""

    strategy_id = "TRACK1_TAIL_DEFENSE"
    version = "1.1.0"
    FENCE_QUANTITY = 1
    INITIAL_FENCE_DISTANCE = 7.5
    OUTER_FENCE_DISTANCE = 12.5
    VOLATILITY_EXPANSION_MULTIPLIER = 1.15
    FENCE_APPROACH_RATIO = 0.9
    HEDGE_REVERSION_POINTS = 1.5
    DTE_CUTOFF = 4.0
    CONFIGURABLE_PARAMETERS = (
        "FENCE_QUANTITY", "INITIAL_FENCE_DISTANCE", "OUTER_FENCE_DISTANCE",
        "VOLATILITY_EXPANSION_MULTIPLIER", "FENCE_APPROACH_RATIO",
        "HEDGE_REVERSION_POINTS", "DTE_CUTOFF",
    )

    def __init__(self, profit_target: float = 500_000.0, max_hedge_allowed: int = 20) -> None:
        self.profit_target = profit_target
        self.max_hedge_allowed = max_hedge_allowed
        self.state = Track1State(fence_distance=self.INITIAL_FENCE_DISTANCE)
        self._initialized = False
        self._hedge_exit_pending = False
        self._hedge_exit_pending = False
        self._hedge_exit_pending = False
        self._hedge_exit_pending = False

    def feature_requirements(self) -> tuple[()]:
        """Track1 consumes typed Track1Input; no Common Analytics metrics are mandatory."""
        return ()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        self._initialized = True

    def on_market_state(self, context: StrategyContext) -> None:
        self._initialized = True

    @staticmethod
    def _price(context: StrategyContext) -> float:
        tick = next(iter(context.market_state.ticks.values()))
        return float(tick.price)

    @staticmethod
    def _round_strike(price: float) -> float:
        return float(round_to_strike_tick(price))

    @staticmethod
    def _input(context: StrategyContext) -> Track1Input | None:
        payload = context.input.payload if context.input is not None else None
        return payload if isinstance(payload, Track1Input) else None

    def _build_fence_signal(self, fence_type: str, strike: float, tag: int, reason: str) -> Signal:
        # Legacy Track1 explicitly creates these fence legs as OPTION qty=1.
        # The side is the explicit side of this signal, not a generic direction→side conversion.
        side = "BUY" if fence_type == "CALL" else "SELL"
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.FENCE_QUANTITY,
            asset_type="OPTION",
            requested_price=None,
            side=side,
            track_id=self.strategy_id,
            tag_id=str(tag),
            option_type=fence_type,
            strike=Decimal(str(strike)),
        )
        return Signal(self.strategy_id, side, 1.0,
                      f"FENCE_BUILD:{fence_type}:{strike}:#{tag}:{reason}",
                      execution_proposal=proposal)

    def on_execution_result(self, purpose: str, result: object) -> None:
        if purpose != "FUTURES_UNWIND" or not self._hedge_exit_pending:
            return
        if bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
            self.state.active_hedge = None
            self.state.hedge_entry_price = None
            self.state.active_hedge_quantity = 0
            self._hedge_exit_pending = False

    def on_execution_result(self, purpose: str, result: object) -> None:
        if purpose != "FUTURES_UNWIND" or not self._hedge_exit_pending:
            return
        if bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
            self.state.active_hedge = None
            self.state.hedge_entry_price = None
            self.state.active_hedge_quantity = 0
            self._hedge_exit_pending = False

    def _build_hedge_unwind_signal(self) -> Signal:
        quantity = self.state.active_hedge_quantity
        if quantity <= 0 or self.state.active_hedge not in {"BUY", "SELL"}:
            raise ValueError("TRACK1_ACTIVE_HEDGE_PROVENANCE_REQUIRED")
        side = "BUY" if self.state.active_hedge == "SELL" else "SELL"
        return Signal(
            self.strategy_id, side, 1.0, f"FUTURES_UNWIND:{self.HEDGE_REVERSION_POINTS}PT_REVERSION",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=quantity, asset_type="FUTURES", requested_price=None,
                side=side, track_id=self.strategy_id, tag_id="FUTURES_UNWIND",
            ),
        )

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            raise ValueError("strategy context mismatch")
        # Missing authoritative market state must not produce an order proposal.
        if context.market_state is None or not context.market_state.ticks or self._hedge_exit_pending:
            return ()
        if not self._initialized:
            self.initialize(context)

        track_input = self._input(context)
        price = self._price(context)
        signals: list[Signal] = []

        if track_input is not None:
            if track_input.current_time is not None:
                current_date = track_input.current_time.date()
                if self.state.hedge_count_date != current_date:
                    self.state.futures_hedge_count = 0
                    self.state.hedge_count_date = current_date
            if track_input.days_to_expiry is not None and track_input.days_to_expiry <= self.DTE_CUTOFF:
                if self.state.active_fence_type is not None:
                    signals.append(Signal(
                        self.strategy_id,
                        "FLAT",
                        1.0,
                        f"FENCE_CLEAR:D4_CUTOFF:{self.state.active_fence_type}:{self.state.active_fence_strike}:#{self.state.active_fence_tag}",
                        execution_proposal=StrategyExecutionProposal(
                            proposed_quantity=self.FENCE_QUANTITY,
                            asset_type="OPTION",
                            requested_price=None,
                            side=("BUY" if self.state.active_fence_type == "PUT" else "SELL"),
                            track_id=self.strategy_id,
                            tag_id=str(self.state.active_fence_tag),
                            option_type=self.state.active_fence_type,
                            strike=Decimal(str(self.state.active_fence_strike)),
                        ),
                    ))
                    self.state.active_fence_type = None
                    self.state.active_fence_strike = None
                return signals
            if track_input.active_vol is not None and track_input.base_vol is not None:
                self.state.fence_distance = self.OUTER_FENCE_DISTANCE if track_input.active_vol > track_input.base_vol * self.VOLATILITY_EXPANSION_MULTIPLIER else self.INITIAL_FENCE_DISTANCE

        if not self.state.market_opened:
            self.state.base_price = price
            self.state.market_opened = True
            call_outer = self._round_strike(price + self.OUTER_FENCE_DISTANCE)
            put_outer = self._round_strike(price - self.OUTER_FENCE_DISTANCE)
            put_inner = self._round_strike(price - self.INITIAL_FENCE_DISTANCE)
            self.state.active_fence_type = "PUT"
            self.state.active_fence_strike = put_inner
            self.state.active_fence_tag = 1
            return (
                self._build_fence_signal("CALL", call_outer, 0, "TAIL_DEFENSE_BUILD_OUTER"),
                self._build_fence_signal("PUT", put_outer, 0, "TAIL_DEFENSE_BUILD_OUTER"),
                self._build_fence_signal("PUT", put_inner, 1, "INITIAL_INNER_FENCE"),
            )

        if self.state.active_fence_type is None or self.state.active_fence_strike is None:
            return signals

        base = self.state.base_price or price
        warning = self.state.fence_distance * self.FENCE_APPROACH_RATIO
        approaching = (price <= base - warning if self.state.active_fence_type == "PUT" else price >= base + warning)

        if approaching and self.state.active_hedge is None:
            momentum_confirmed = track_input.momentum_confirmed if track_input is not None else False
            if momentum_confirmed and self.state.futures_hedge_count < self.max_hedge_allowed:
                self.state.active_hedge = "SELL" if self.state.active_fence_type == "PUT" else "BUY"
                self.state.hedge_entry_price = price
                hedge_qty = 0
                if track_input.short_option_net_delta is not None:
                    hedge_qty = delta_to_mini_futures_qty(track_input.short_option_net_delta)
                if hedge_qty <= 0:
                    self.state.active_hedge = None
                    self.state.hedge_entry_price = None
                    return signals
                self.state.active_hedge_quantity = hedge_qty
                self.state.futures_hedge_count += 1
                signals.append(Signal(
                    self.strategy_id,
                    self.state.active_hedge,
                    1.0,
                    f"FUTURES_HEDGE_TRIGGER:#{self.state.futures_hedge_count}:price={price}:qty={hedge_qty}",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=hedge_qty,
                        asset_type="FUTURES",
                        requested_price=None,
                        side=self.state.active_hedge,
                        track_id=self.strategy_id,
                        tag_id="FUTURES_HEDGE",
                        option_type=None,
                        strike=None,
                    ),
                ))

        if self.state.active_hedge and self.state.hedge_entry_price is not None:
            reverted = ((self.state.active_hedge == "SELL" and price - self.state.hedge_entry_price >= self.HEDGE_REVERSION_POINTS) or
                        (self.state.active_hedge == "BUY" and self.state.hedge_entry_price - price >= self.HEDGE_REVERSION_POINTS))
            if reverted and not self._hedge_exit_pending:
                signals.append(self._build_hedge_unwind_signal())
                self._hedge_exit_pending = True

        return signals

    def reset(self) -> None:
        self.state = Track1State(fence_distance=self.INITIAL_FENCE_DISTANCE)
        self._initialized = False