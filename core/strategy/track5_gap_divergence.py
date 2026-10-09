from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from core.strategy.contracts import Signal, SignalKind, StrategyContext, StrategyFeatureRequirement
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track5ExecutionInput:
    expiry: str
    atm_strike: Decimal
    selected_strike: Decimal
    option_type: str
    strike_rank: int
    liquidity_score: Decimal
    option_quantity: int = 1
    mini_futures_quantity: int = 5


@dataclass(frozen=True)
class Track5State:
    is_active: bool = False
    direction: str | None = None
    entry_price: Decimal = Decimal("0")
    target_price: Decimal = Decimal("0")
    stop_loss_price: Decimal = Decimal("0")
    open_ticks: int = 0
    peak_pnl: Decimal = Decimal("0")
    trailing_active: bool = False
    expected_move_pts: Decimal = Decimal("0")
    session_start_price: Decimal | None = None
    session_start_at: object | None = None
    gap_source: str | None = None
    gap_extreme_price: Decimal | None = None
    option_type: str | None = None
    selected_strike: Decimal | None = None
    futures_side: str | None = None
    futures_close_requested: bool = False
    futures_closed: bool = False
    futures_close_error: str | None = None


class Track5GapDivergence:
    strategy_id = "track5_gap_divergence"
    version = "2.0"
    ENTRY_QUANTITY = 1
    MINI_FUTURES_QUANTITY = 5
    # Counts evaluate_mean_reversion calls while a position is open, not elapsed minutes or bars.
    MAX_OPEN_EVALUATIONS = 30

    def __init__(self, z_threshold: Decimal = Decimal("1.5")) -> None:
        self.z_threshold = z_threshold
        self.state = Track5State()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.open", "price.gap", "price.last", "price.previous_close",
                "volatility.expected_move", "stats.z_score", "regime.market",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track5State()

    def effective_z_threshold(self, regime: str) -> Decimal:
        if regime in {"HIGH_VOL", "NOISE_CHOPPY", "CIRCUIT_BREAKER"}:
            return Decimal("1.8")
        if regime in {"NORMAL", "NEUTRAL"}:
            return Decimal("1.1")
        return self.z_threshold

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        metric = snapshot.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    def _required(self, snapshot: AnalyticsSnapshot):
        values = tuple(self._metric(snapshot, key) for key in (
            "price.open", "price.last", "price.previous_close",
            "volatility.expected_move", "stats.z_score", "regime.market",
        ))
        open_price, last, previous_close, expected_move, z_score, regime = values
        if not all(isinstance(value, Decimal) for value in (open_price, last, previous_close, expected_move, z_score)):
            return None
        if not isinstance(regime, str) or previous_close <= 0 or expected_move <= 0:
            return None
        return open_price, last, previous_close, expected_move, z_score, regime

    def _session_minutes(self, snapshot: AnalyticsSnapshot) -> Decimal | None:
        observed_at = getattr(snapshot, "as_of", None)
        if observed_at is None or self.state.session_start_at is None:
            return None
        try:
            return Decimal(str((observed_at - self.state.session_start_at).total_seconds())) / Decimal("60")
        except (AttributeError, TypeError):
            return None

    def _intraday_gap_candidate(self, last, session_start_price, expected_move, regime, elapsed_minutes):
        if elapsed_minutes is None or elapsed_minutes > Decimal("30"):
            return None
        move = last - session_start_price
        if abs(move) < max(Decimal("1.0"), expected_move * Decimal("1.1")):
            return None
        z_score = move / max(Decimal("0.1"), expected_move)
        effective_z = self.effective_z_threshold(regime)
        if abs(z_score) < effective_z or abs(z_score) >= Decimal("4.0"):
            return None
        return ("OPENING_WINDOW_INTRADAY_GAP", last, session_start_price, z_score)

    def _proposal(self, *, asset_type: str, side: str, quantity: int, tag_id: str,
                  option_type: str | None = None, strike: Decimal | None = None):
        return StrategyExecutionProposal(
            proposed_quantity=quantity,
            asset_type=asset_type,
            side=side,
            track_id=self.strategy_id,
            tag_id=tag_id,
            option_type=option_type,
            strike=strike,
        )

    def evaluate_gap(self, snapshot: AnalyticsSnapshot, execution_input: Track5ExecutionInput | None = None) -> Sequence[Signal]:
        if self.state.is_active:
            return ()
        required = self._required(snapshot)
        if required is None or execution_input is None:
            return ()
        open_price, last, previous_close, expected_move, z_score, regime = required
        gap = self._metric(snapshot, "price.gap")
        if not isinstance(gap, Decimal):
            return ()

        observed_at = getattr(snapshot, "as_of", None)
        if self.state.session_start_price is None:
            self.state = replace(self.state, session_start_price=last, session_start_at=observed_at)
        elapsed_minutes = self._session_minutes(snapshot)
        effective_z = self.effective_z_threshold(regime)

        if abs(z_score) >= effective_z and abs(z_score) < Decimal("4.0"):
            source = "OPENING_GAP"
            entry_price = open_price
            target_price = previous_close
            candidate_z = z_score
        else:
            candidate = self._intraday_gap_candidate(
                last, self.state.session_start_price, expected_move, regime, elapsed_minutes
            )
            if candidate is None:
                return ()
            source, entry_price, target_price, candidate_z = candidate

        direction = "SHORT" if candidate_z > 0 else "LONG"
        option_type = "CALL" if direction == "SHORT" else "PUT"
        futures_side = "SELL" if direction == "SHORT" else "BUY"
        stop_distance = max(Decimal("1.0"), expected_move * Decimal("0.8"))
        stop = entry_price + stop_distance if direction == "SHORT" else entry_price - stop_distance
        self.state = replace(
            self.state, is_active=True, direction=direction,
            entry_price=entry_price, target_price=target_price,
            stop_loss_price=stop, open_ticks=0, peak_pnl=Decimal("0"),
            trailing_active=False,
            expected_move_pts=expected_move, gap_source=source,
            gap_extreme_price=entry_price, option_type=option_type,
            selected_strike=execution_input.selected_strike,
            futures_side=futures_side, futures_closed=False,
        )
        return (Signal(
            strategy_id=self.strategy_id,
            direction=direction,
            confidence=float(min(Decimal("1"), abs(candidate_z) / Decimal("4"))),
            reason=(
                f"GAP_SOURCE:{source};GAP:{gap};GAP_Z_SCORE:{candidate_z:.4f};"
                f"ENTRY:{entry_price};TARGET:{target_price};STOP:{stop};"
                f"WINDOW_MINUTES:{elapsed_minutes};OPTION:{option_type};"
                f"STRIKE:{execution_input.selected_strike};STRIKE_RANK:{execution_input.strike_rank};"
                f"MINI_FUTURES_QTY:{self.MINI_FUTURES_QUANTITY}"
            ),
            kind=SignalKind.EXECUTION,
            execution_proposal=self._proposal(
                asset_type="OPTION", side="BUY", quantity=self.ENTRY_QUANTITY,
                tag_id="GAP_DIVERGENCE_ENTRY_OPTION",
                option_type=option_type, strike=execution_input.selected_strike,
            ),
        ),)

    def _request_futures_exit(self, state: Track5State, current_price: Decimal, reason: str) -> Sequence[Signal]:
        """Request the hedge close; only a confirmed full fill closes the hedge state."""
        if state.futures_side not in {"BUY", "SELL"}:
            # Preserve the active option state and surface the unknown hedge leg; never
            # infer a successful futures close from missing/corrupt side metadata.
            self.state = replace(
                state,
                futures_closed=False,
                futures_close_requested=False,
                futures_close_error="INVALID_FUTURES_SIDE;POSITION_RECONCILIATION_REQUIRED",
            )
            return ()
        if state.futures_closed or state.futures_close_requested:
            self.state = state
            return ()
        self.state = replace(
            state, futures_close_requested=True, futures_closed=False, futures_close_error=None
        )
        futures_close_side = "BUY" if state.futures_side == "SELL" else "SELL"
        return (Signal(
            self.strategy_id,
            "CLOSE_FUTURES",
            1.0,
            f"{reason};PRICE:{current_price};ENTRY:{state.entry_price};MINI_FUTURES_QTY:{self.MINI_FUTURES_QUANTITY}",
            kind=SignalKind.EXECUTION,
            execution_proposal=self._proposal(
                asset_type="FUTURES", side=futures_close_side,
                quantity=self.MINI_FUTURES_QUANTITY,
                tag_id="GAP_DIVERGENCE_FUTURES_FIRST_EXIT",
            ),
        ),)

    def on_execution_result(self, purpose: str, result: object) -> None:
        """Advance the hedge lifecycle only from its correlated execution report."""
        if purpose != "TRACK5_GAP_HEDGE_FUTURES_EXIT":
            return
        if not self.state.is_active or not self.state.futures_close_requested:
            return

        reports = tuple(getattr(result, "reports", ()) or ())
        if not reports:
            if (
                int(getattr(result, "pending_legs", 0) or 0) == 0
                and int(getattr(result, "routed_legs", 0) or 0) == 0
            ):
                self.state = replace(self.state, futures_close_requested=False)
            return

        for report in reports:
            if getattr(report, "leg_id", None) != "MINI_FUTURES_EXIT":
                continue
            status = str(getattr(report, "status", "")).strip().upper()
            if status in {"REJECTED", "FAILED", "CANCELLED", "EXPIRED"}:
                self.state = replace(
                    self.state, futures_close_requested=False, futures_closed=False
                )
                return
            if (
                status == "FILLED"
                and int(getattr(report, "filled_quantity", 0) or 0) == self.MINI_FUTURES_QUANTITY
                and int(getattr(report, "remaining_quantity", -1)) == 0
                and bool(getattr(report, "execution_id", None))
                and getattr(report, "execution_timestamp", None) is not None
                and getattr(report, "execution_price", None) is not None
            ):
                self.state = replace(
                    self.state, futures_close_requested=False, futures_closed=True
                )
                return

    def evaluate_mean_reversion(self, current_price: Decimal) -> Sequence[Signal]:
        if not self.state.is_active or self.state.direction is None:
            return ()
        state = replace(self.state, open_ticks=self.state.open_ticks + 1)
        direction = state.direction
        pnl = state.entry_price - current_price if direction == "SHORT" else current_price - state.entry_price
        state = replace(state, peak_pnl=max(state.peak_pnl, pnl))
        if state.gap_extreme_price is None:
            state = replace(state, gap_extreme_price=state.entry_price)
        if direction == "SHORT":
            state = replace(state, gap_extreme_price=max(state.gap_extreme_price, current_price))
        else:
            state = replace(state, gap_extreme_price=min(state.gap_extreme_price, current_price))

        # The first leg to be released is always the MINI futures hedge.
        # It is closed when the opening gap starts to fill from the entry side.
        gap_started_filling = (
            direction == "SHORT" and current_price < state.entry_price
        ) or (
            direction == "LONG" and current_price > state.entry_price
        )
        if not state.futures_closed and gap_started_filling:
            return self._request_futures_exit(state, current_price, "GAP_FILL_STARTED")

        trail_threshold = max(Decimal("0.3"), state.expected_move_pts * Decimal("0.3"))
        trail_reversal = max(Decimal("0.1"), state.expected_move_pts * Decimal("0.1"))
        pnl_ratio = pnl / max(Decimal("0.1"), state.expected_move_pts)
        scale = Decimal("0.67") if pnl_ratio >= 1 else Decimal("0.80") if pnl_ratio >= Decimal("0.3") else Decimal("1")
        effective_reversal = trail_reversal * scale

        # The option is the second leg. It remains open through the gap expansion
        # and closes only after an extreme has been established and the price
        # returns toward the previous close, or a trailing reversal is confirmed.
        reached_target = (
            (direction == "SHORT" and current_price <= state.target_price) or
            (direction == "LONG" and current_price >= state.target_price)
        )
        had_expansion = (
            (direction == "SHORT" and state.gap_extreme_price > state.entry_price) or
            (direction == "LONG" and state.gap_extreme_price < state.entry_price)
        )
        if state.futures_closed and reached_target and (had_expansion or state.open_ticks > 1):
            self.reset()
            return (Signal(
                self.strategy_id,
                "CLOSE_OPTION",
                1.0,
                f"MEAN_REVERSION_TARGET:{state.target_price};EXTREME:{state.gap_extreme_price};PNL:{pnl}",
                kind=SignalKind.EXECUTION,
                execution_proposal=self._proposal(
                    asset_type="OPTION", side="SELL", quantity=self.ENTRY_QUANTITY,
                    tag_id="GAP_DIVERGENCE_OPTION_SECOND_EXIT",
                    option_type=state.option_type, strike=state.selected_strike,
                ),
            ),)

        stop_triggered = (
            direction == "SHORT" and current_price >= state.stop_loss_price
        ) or (
            direction == "LONG" and current_price <= state.stop_loss_price
        )
        if stop_triggered:
            if not state.futures_closed:
                return self._request_futures_exit(state, current_price, "OPTION_STOP_REQUIRES_HEDGE_CLOSE")
            self.reset()
            return (Signal(
                self.strategy_id, "CLOSE_OPTION", 1.0,
                f"DYNAMIC_STOP:{state.stop_loss_price};PNL:{pnl}",
                kind=SignalKind.EXECUTION,
                execution_proposal=self._proposal(
                    asset_type="OPTION", side="SELL", quantity=self.ENTRY_QUANTITY,
                    tag_id="GAP_DIVERGENCE_OPTION_STOP_EXIT",
                    option_type=state.option_type, strike=state.selected_strike,
                ),
            ),)

        if state.open_ticks >= self.MAX_OPEN_EVALUATIONS:
            if not state.futures_closed:
                return self._request_futures_exit(state, current_price, "TIMEOUT_REQUIRES_HEDGE_CLOSE")
            self.reset()
            return (Signal(
                self.strategy_id, "CLOSE_OPTION", 1.0,
                f"TIMEOUT_{self.MAX_OPEN_EVALUATIONS}_EVALUATIONS;PNL:{pnl}",
                kind=SignalKind.EXECUTION,
                execution_proposal=self._proposal(
                    asset_type="OPTION", side="SELL", quantity=self.ENTRY_QUANTITY,
                    tag_id="GAP_DIVERGENCE_OPTION_TIMEOUT_EXIT",
                    option_type=state.option_type, strike=state.selected_strike,
                ),
            ),)

        trailing_active = state.trailing_active or pnl >= trail_threshold
        state = replace(state, trailing_active=trailing_active)
        if trailing_active and state.peak_pnl - pnl >= effective_reversal:
            if not state.futures_closed:
                return self._request_futures_exit(state, current_price, "TRAILING_EXIT_REQUIRES_HEDGE_CLOSE")
            self.reset()
            return (Signal(
                self.strategy_id, "CLOSE_OPTION", 1.0,
                f"TRAILING_LOCK;PEAK:{state.peak_pnl};REVERSAL:{effective_reversal};PNL:{pnl}",
                kind=SignalKind.EXECUTION,
                execution_proposal=self._proposal(
                    asset_type="OPTION", side="SELL", quantity=self.ENTRY_QUANTITY,
                    tag_id="GAP_DIVERGENCE_OPTION_TRAILING_EXIT",
                    option_type=state.option_type, strike=state.selected_strike,
                ),
            ),)

        self.state = state
        return ()

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal, futures_identity) -> MultiLegExecutionPlan:
        if proposal.track_id != self.strategy_id:
            raise ValueError("TRACK5_STRATEGY_REQUIRED")
        if proposal.asset_type == "OPTION" and proposal.side == "BUY":
            if proposal.option_type not in {"CALL", "PUT"} or proposal.strike is None:
                raise ValueError("TRACK5_OPTION_ENTRY_PROPOSAL_REQUIRED")
            futures_side = "SELL" if proposal.option_type == "CALL" else "BUY"
            return MultiLegExecutionPlan(
                group_id=group_id,
                strategy_id=self.strategy_id,
                purpose="TRACK5_GAP_HEDGE_ENTRY",
                legs=(
                    ExecutionLeg("OPTION", "BUY", self.ENTRY_QUANTITY, proposal.option_type, proposal.strike, position_role="NONE"),
                    ExecutionLeg("MINI_FUTURES", futures_side, self.MINI_FUTURES_QUANTITY, position_role="NONE"),
                ),
            )
        if proposal.asset_type == "FUTURES":
            return MultiLegExecutionPlan(
                group_id=group_id,
                strategy_id=self.strategy_id,
                purpose="TRACK5_GAP_HEDGE_FUTURES_EXIT",
                legs=(ExecutionLeg("MINI_FUTURES_EXIT", proposal.side or "", self.MINI_FUTURES_QUANTITY, position_role="NONE"),),
            )
        if proposal.asset_type == "OPTION" and proposal.side == "SELL":
            if proposal.option_type not in {"CALL", "PUT"} or proposal.strike is None:
                raise ValueError("TRACK5_OPTION_EXIT_PROPOSAL_REQUIRED")
            return MultiLegExecutionPlan(
                group_id=group_id,
                strategy_id=self.strategy_id,
                purpose="TRACK5_GAP_HEDGE_OPTION_EXIT",
                legs=(ExecutionLeg("OPTION_EXIT", "SELL", self.ENTRY_QUANTITY, proposal.option_type, proposal.strike, position_role="NONE"),),
            )
        raise ValueError("TRACK5_EXECUTION_PROPOSAL_UNSUPPORTED")

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if self.state.is_active:
            current_price = self._metric(context.analytics, "price.last")
            if not isinstance(current_price, Decimal):
                return ()
            return self.evaluate_mean_reversion(current_price)
        execution_input = context.input.payload if context.input is not None else None
        if not isinstance(execution_input, Track5ExecutionInput):
            return ()
        return self.evaluate_gap(context.analytics, execution_input)


__all__ = ("Track5GapDivergence", "Track5State", "Track5ExecutionInput")
