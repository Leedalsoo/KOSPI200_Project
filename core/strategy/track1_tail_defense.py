from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from core.instrument.strike_rules import round_to_strike_tick
from core.strategy.contracts import Signal, Strategy, StrategyContext, StrategyPayload
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


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
    reference_point: Decimal | None = None
    reference_point_verified: bool = False
    open_short_quantity: int | None = None
    pending_short_quantity: int | None = None
    exposure_snapshot_verified: bool = False
    dte_basis_verified: bool = False


@dataclass
class Track1State:
    reference_point: Decimal | None = None
    last_crossing_index: int = 0


class Track1TailDefense(Strategy):
    """Strategy 1 short-accumulation rules with fail-closed runtime admission."""

    strategy_id = "TRACK1_TAIL_DEFENSE"
    version = "1.2.0"

    SHORT_STEP_POINTS = Decimal("2.5")
    SHORT_OFFSET_POINTS = Decimal("7.5")
    MAX_OPEN_SHORT_CONTRACTS = 10
    SHORT_QUANTITY_PER_CROSSING = 1
    DTE_CUTOFF = 4.0
    CONFIGURABLE_PARAMETERS = (
        "SHORT_STEP_POINTS",
        "SHORT_OFFSET_POINTS",
        "MAX_OPEN_SHORT_CONTRACTS",
        "SHORT_QUANTITY_PER_CROSSING",
        "DTE_CUTOFF",
    )

    def __init__(
        self,
        profit_target: float = 500_000.0,
        max_hedge_allowed: int = 20,
        *,
        runtime_config_verified: bool = False,
        risk_limits_available: bool = False,
    ) -> None:
        # Legacy constructor arguments are retained for registry compatibility only.
        # They do not enable profit-taking or futures hedging.
        self.runtime_config_verified = runtime_config_verified
        self.risk_limits_available = risk_limits_available
        self.state = Track1State()

    def feature_requirements(self) -> tuple[()]:
        return ()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    @staticmethod
    def _price(context: StrategyContext) -> Decimal | None:
        market_state = context.market_state
        if market_state is None or not market_state.ticks:
            return None
        tick = next(iter(market_state.ticks.values()))
        return Decimal(str(tick.price))

    @staticmethod
    def _input(context: StrategyContext) -> Track1Input | None:
        payload = context.input.payload if context.input is not None else None
        return payload if isinstance(payload, Track1Input) else None

    def _build_fence_signal(
        self, fence_type: str, strike: float, tag: int, reason: str, *, side: str
    ) -> Signal:
        """Explicit side helper retained for compatible callers and regression tests."""
        if side not in {"BUY", "SELL"}:
            raise ValueError("TRACK1_OPTION_SIDE_INVALID")
        if fence_type not in {"CALL", "PUT"}:
            raise ValueError("TRACK1_OPTION_TYPE_INVALID")
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.SHORT_QUANTITY_PER_CROSSING,
            asset_type="OPTION",
            requested_price=None,
            side=side,
            track_id=self.strategy_id,
            tag_id=str(tag),
            option_type=fence_type,
            strike=Decimal(str(strike)),
        )
        return Signal(
            self.strategy_id,
            side,
            1.0,
            f"FENCE_BUILD:{fence_type}:{strike}:#{tag}:{reason}",
            execution_proposal=proposal,
        )

    def _build_short_accumulation_signal(
        self, *, option_type: str, strike: Decimal, crossing_index: int
    ) -> Signal:
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.SHORT_QUANTITY_PER_CROSSING,
            asset_type="OPTION",
            requested_price=None,
            side="SELL",
            track_id=self.strategy_id,
            tag_id=f"S1_SHORT_ACCUMULATION_{option_type}_{crossing_index:06d}",
            option_type=option_type,
            strike=strike,
        )
        return Signal(
            self.strategy_id,
            "SELL",
            1.0,
            f"S1_SHORT_ACCUMULATION:{option_type}:{strike}:CROSSING_{crossing_index}",
            execution_proposal=proposal,
        )

    @staticmethod
    def _valid_non_negative_quantity(value: int | None) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            raise ValueError("strategy context mismatch")

        price = self._price(context)
        track_input = self._input(context)
        if price is None or track_input is None:
            return ()
        if not self.runtime_config_verified or not self.risk_limits_available:
            return ()
        if not track_input.reference_point_verified or not track_input.exposure_snapshot_verified:
            return ()
        if not track_input.dte_basis_verified or track_input.days_to_expiry is None:
            return ()
        # DTE4 is a terminal-close rule, not permission to create another short.
        # Until authoritative expiry semantics and grouped close/recovery are wired,
        # fail closed at and inside the threshold.
        if track_input.days_to_expiry <= self.DTE_CUTOFF:
            return ()
        if (
            not self._valid_non_negative_quantity(track_input.open_short_quantity)
            or not self._valid_non_negative_quantity(track_input.pending_short_quantity)
            or track_input.reference_point is None
            or track_input.reference_point <= 0
        ):
            return ()

        if self.state.reference_point is None:
            self.state.reference_point = Decimal(track_input.reference_point)

        reference = self.state.reference_point
        open_and_pending = (
            track_input.open_short_quantity + track_input.pending_short_quantity
        )
        if open_and_pending > self.MAX_OPEN_SHORT_CONTRACTS:
            return ()

        signals: list[Signal] = []
        pending_worst_case = open_and_pending

        # Consume every crossed 2.5-point step in order. Strike calculation always
        # uses the previous reference; the reference advances only after that
        # crossing's strike has been derived.
        while price - reference >= self.SHORT_STEP_POINTS:
            reached = reference + self.SHORT_STEP_POINTS
            strike = Decimal(str(round_to_strike_tick(
                reference - self.SHORT_OFFSET_POINTS
            )))
            self.state.last_crossing_index += 1
            if pending_worst_case < self.MAX_OPEN_SHORT_CONTRACTS:
                signals.append(self._build_short_accumulation_signal(
                    option_type="PUT",
                    strike=strike,
                    crossing_index=self.state.last_crossing_index,
                ))
                pending_worst_case += self.SHORT_QUANTITY_PER_CROSSING
            reference = reached

        while reference - price >= self.SHORT_STEP_POINTS:
            reached = reference - self.SHORT_STEP_POINTS
            strike = Decimal(str(round_to_strike_tick(
                reference + self.SHORT_OFFSET_POINTS
            )))
            self.state.last_crossing_index += 1
            if pending_worst_case < self.MAX_OPEN_SHORT_CONTRACTS:
                signals.append(self._build_short_accumulation_signal(
                    option_type="CALL",
                    strike=strike,
                    crossing_index=self.state.last_crossing_index,
                ))
                pending_worst_case += self.SHORT_QUANTITY_PER_CROSSING
            reference = reached

        self.state.reference_point = reference
        return tuple(signals)

    def reset(self) -> None:
        self.state = Track1State()
