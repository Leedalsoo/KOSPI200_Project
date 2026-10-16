"""Pure S6 decision functions for the opt-in candidate implementation."""
from __future__ import annotations
from contracts.trading_date import format_trading_date

from dataclasses import dataclass, replace
from decimal import Decimal

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import NonExecutionEvent, Signal, SignalKind, StrategyContext
from core.strategy.multi_leg_plan import build_pair_plan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput, Track6State
from core.strategy.engine.phase_clock import at_or_after, in_window
from core.strategy.engine.s6_rules import S6_RULES, S6Rules

STRATEGY_ID = "track6_daily_tail_insurance"
STRATEGY_VERSION = "1.0"
INSURANCE_QTY = 1

@dataclass(frozen=True)
class S6Decision:
    signals: tuple[Signal, ...]
    state: Track6State
    exit_pending: bool

def _metric(snapshot: AnalyticsSnapshot, key: str):
    metric = snapshot.get(key)
    if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
        return None
    return metric.value

def _execution_input(context: StrategyContext) -> Track6ExecutionInput | None:
    payload = getattr(getattr(context, "input", None), "payload", None)
    return payload if isinstance(payload, Track6ExecutionInput) else None

def _as_time(snapshot: AnalyticsSnapshot) -> str:
    return snapshot.as_of.strftime("%H:%M:%S")

def _as_date(snapshot: AnalyticsSnapshot) -> str:
    return format_trading_date(snapshot.as_of.date())

def _close_proposal(state: Track6State, *, tag_id: str, insurance_qty: int) -> StrategyExecutionProposal:
    if state.long_put_strike <= 0 or state.long_call_strike <= 0:
        raise ValueError("TRACK6_OPTION_SELECTION_REQUIRED")
    return StrategyExecutionProposal(
        proposed_quantity=insurance_qty, asset_type="OPTION", side="SELL",
        track_id=STRATEGY_ID, tag_id=tag_id, option_type="PUT", strike=state.long_put_strike,
    )

def _buy(state: Track6State, context: StrategyContext, *, rules: S6Rules, insurance_qty: int) -> S6Decision:
    analytics = context.analytics
    data = _execution_input(context)
    if analytics is None or data is None or state.is_active:
        return S6Decision((), state, False)
    current_price = _metric(analytics, "price.last")
    active_vol = _metric(analytics, "volatility.active")
    base_vol = _metric(analytics, "volatility.base")
    if not all(isinstance(value, Decimal) for value in (current_price, active_vol, base_vol)):
        return S6Decision((), state, False)
    time_text = _as_time(analytics)
    if in_window(time_text, rules.market_cutoff, rules.pending_cancel_end):
        return S6Decision((Signal(STRATEGY_ID, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),), state, False)
    if data.contract_multiplier is None or data.contract_multiplier <= 0:
        return S6Decision((), state, False)
    if data.listed_put_strike is None or data.listed_call_strike is None:
        return S6Decision((), state, False)
    if base_vol <= 0 or active_vol < base_vol * rules.vol_trigger_multiplier:
        return S6Decision((), state, False)
    put_strike = data.listed_put_strike
    call_strike = data.listed_call_strike
    next_state = replace(
        state, is_active=True, bought_date=_as_date(analytics),
        long_put_strike=put_strike, long_call_strike=call_strike,
        high_watermark_intrinsic=Decimal("0"), trailing_stop_active=False,
    )
    signal = Signal(
        STRATEGY_ID, "BUY_INSURANCE", 1.0,
        f"VOL_SPIKE:{active_vol}>={base_vol * rules.vol_trigger_multiplier};PUT:{put_strike};CALL:{call_strike};QTY:{insurance_qty}",
        execution_proposal=StrategyExecutionProposal(
            proposed_quantity=insurance_qty, asset_type="OPTION", side="BUY",
            track_id=STRATEGY_ID, tag_id="DAILY_TAIL_INSURANCE_ENTRY",
            option_type="PUT", strike=put_strike,
        ),
    )
    return S6Decision((signal,), next_state, False)

def _take_profit(state: Track6State, exit_pending: bool, context: StrategyContext, *, rules: S6Rules, insurance_qty: int) -> S6Decision:
    analytics = context.analytics
    if analytics is None or not state.is_active or exit_pending:
        return S6Decision((), state, exit_pending)
    current_price = _metric(analytics, "price.last")
    active_vol = _metric(analytics, "volatility.active")
    premium_spent = _metric(analytics, "portfolio.premium_spent")
    if not all(isinstance(value, Decimal) for value in (current_price, active_vol, premium_spent)):
        return S6Decision((), state, exit_pending)
    if at_or_after(_as_time(analytics), rules.take_profit_suppression_time):
        return S6Decision((), state, exit_pending)
    if premium_spent <= 0 or insurance_qty <= 0:
        return S6Decision((), state, exit_pending)
    multiplier = premium_spent / Decimal(insurance_qty)
    put_intrinsic = max(Decimal("0"), state.long_put_strike - current_price) * multiplier * insurance_qty
    call_intrinsic = max(Decimal("0"), current_price - state.long_call_strike) * multiplier * insurance_qty
    total_intrinsic = put_intrinsic + call_intrinsic
    spent = premium_spent
    minimum_multiplier = rules.trailing_activation_below_boundary if active_vol < rules.trailing_volatility_boundary else rules.trailing_activation_at_or_above_boundary
    trailing_active = state.trailing_stop_active or total_intrinsic >= spent * minimum_multiplier
    if not trailing_active:
        return S6Decision((), state, exit_pending)
    previous_high = state.high_watermark_intrinsic
    current_high = max(previous_high, total_intrinsic)
    pnl_ratio = current_high / max(Decimal("1"), spent)
    trailing_ratio = rules.trailing_retain_ratio_high if pnl_ratio >= rules.trailing_ratio_high_boundary else rules.trailing_retain_ratio_middle if pnl_ratio >= rules.trailing_ratio_middle_boundary else rules.trailing_retain_ratio_low
    stop_trigger = current_high * trailing_ratio
    if current_high > 0 and total_intrinsic <= stop_trigger:
        proposal = _close_proposal(state, tag_id="DAILY_TAIL_INSURANCE_TRAILING_CLOSE", insurance_qty=insurance_qty)
        return S6Decision((Signal(
            STRATEGY_ID, "CLOSE", 1.0,
            f"TRAILING_STOP;REALIZED:{total_intrinsic};HIGH:{current_high};RATIO:{trailing_ratio}",
            execution_proposal=proposal,
        ),), state, True)
    if previous_high == 0 or current_high >= previous_high * rules.watermark_update_ratio:
        next_state = replace(state, trailing_stop_active=True, high_watermark_intrinsic=current_high)
        return S6Decision((Signal(
            STRATEGY_ID, "UPDATE_TRAILING", 0.9,
            f"HIGH_WATERMARK:{current_high};STOP_TRIGGER:{stop_trigger};OFFSET_TICKS:2",
            kind=SignalKind.NON_EXECUTION,
            non_execution_event=NonExecutionEvent(
                event_type="TRACK6_TRAILING_STATE_UPDATE", reason="TRAILING_WATERMARK_UPDATED",
                payload={"high_watermark": current_high, "stop_trigger": stop_trigger, "offset_ticks": 2},
            ),
        ),), next_state, exit_pending)
    return S6Decision((), replace(state, trailing_stop_active=trailing_active), exit_pending)

def evaluate_take_profit_s6(state: Track6State, exit_pending: bool, context: StrategyContext, *, rules: S6Rules = S6_RULES, insurance_qty: int = INSURANCE_QTY) -> S6Decision:
    return _take_profit(state, exit_pending, context, rules=rules, insurance_qty=insurance_qty)

def _expiry_cutoff(state: Track6State, exit_pending: bool, context: StrategyContext, *, rules: S6Rules, insurance_qty: int) -> S6Decision:
    if not state.is_active or context.analytics is None or exit_pending:
        return S6Decision((), state, exit_pending)
    time_text = _as_time(context.analytics)
    if in_window(time_text, rules.limit_cutoff, rules.market_cutoff):
        proposal = _close_proposal(state, tag_id="DAILY_TAIL_INSURANCE_LIMIT_CLOSE", insurance_qty=insurance_qty)
        return S6Decision((Signal(STRATEGY_ID, "CLOSE_LIMIT", 1.0, "DAILY_INSURANCE_15:00_CUTOFF", execution_proposal=proposal),), state, True)
    if at_or_after(time_text, rules.market_cutoff):
        proposal = _close_proposal(state, tag_id="DAILY_TAIL_INSURANCE_FALLBACK_CLOSE", insurance_qty=insurance_qty)
        return S6Decision((Signal(STRATEGY_ID, "CLOSE_FALLBACK", 1.0, "DAILY_INSURANCE_15:15_FALLBACK", execution_proposal=proposal),), state, True)
    return S6Decision((), state, exit_pending)

def evaluate_s6(state: Track6State, exit_pending: bool, context: StrategyContext, *, rules: S6Rules = S6_RULES, insurance_qty: int = INSURANCE_QTY) -> S6Decision:
    """Return the exact S6 decision and next state without mutating the supplied state."""
    if context.strategy_id != STRATEGY_ID or context.analytics is None:
        return S6Decision((), state, exit_pending)
    if state.is_active:
        cutoff = _expiry_cutoff(state, exit_pending, context, rules=rules, insurance_qty=insurance_qty)
        return cutoff if cutoff.signals else _take_profit(state, exit_pending, context, rules=rules, insurance_qty=insurance_qty)
    return _buy(state, context, rules=rules, insurance_qty=insurance_qty)

def execution_result_transition(state: Track6State, exit_pending: bool, purpose: str, result: object) -> tuple[Track6State, bool]:
    if purpose not in {
        "DAILY_TAIL_INSURANCE_TRAILING_CLOSE",
        "DAILY_TAIL_INSURANCE_LIMIT_CLOSE",
        "DAILY_TAIL_INSURANCE_FALLBACK_CLOSE",
    } or not exit_pending:
        return state, exit_pending
    if bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
        return Track6State(), False
    return state, exit_pending

def build_execution_plan(state: Track6State, group_id: str, *, insurance_qty: int = INSURANCE_QTY) -> MultiLegExecutionPlan | None:
    if not state.is_active or state.long_put_strike <= 0 or state.long_call_strike <= 0:
        return None
    return build_pair_plan(
        group_id=group_id, strategy_id=STRATEGY_ID, purpose="DAILY_TAIL_INSURANCE_ENTRY",
        put_strike=state.long_put_strike, call_strike=state.long_call_strike,
        put_quantity=insurance_qty, call_quantity=insurance_qty, side="BUY",
    )