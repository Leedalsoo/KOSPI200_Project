"""Fail-closed S9 policy primitives.

These pure decisions encode only the approved v0.5 scope. They are not wired
to StrategyHub, Runtime, OMS, or broker execution. Callers must supply
authoritative, reconciled inputs before treating a local policy result as
usable evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
ZERO = Decimal("0")
STOP_RATIO = Decimal("0.50")
TRAILING_ARM_MULTIPLE = Decimal("2.00")
TRAILING_DRAWDOWN = Decimal("0.10")
REBUY_MAX_RATIO = Decimal("1.30")
D4_SESSIONS_REMAINING = 4
D4_DECISION_TIME = time(11, 0, 0)


class LotExitAction(StrEnum):
    BLOCKED = "BLOCKED"
    HOLD = "HOLD"
    CLOSE_LOT_STOP = "CLOSE_LOT_STOP"
    CLOSE_LOT_TRAILING = "CLOSE_LOT_TRAILING"


class RebuyCheck(StrEnum):
    BLOCKED = "BLOCKED"
    PRICE_OR_IDENTITY_CHECK_PASSED = "PRICE_OR_IDENTITY_CHECK_PASSED"


class D4Action(StrEnum):
    BLOCKED_AUTHORITY = "BLOCKED_AUTHORITY"
    BLOCKED_MISSED_BOUNDARY = "BLOCKED_MISSED_BOUNDARY"
    WAIT = "WAIT"
    NO_TRIGGER = "NO_TRIGGER"
    BLOCK_NEW_ENTRIES_AND_START_LIQUIDATION = "BLOCK_NEW_ENTRIES_AND_START_LIQUIDATION"


@dataclass(frozen=True)
class LotPolicyState:
    lot_id: str
    exact_instrument_id: str
    entry_fill_premium: Decimal
    remaining_quantity: int
    high_water_mark: Decimal | None = None
    trailing_armed: bool = False


@dataclass(frozen=True)
class LotExitResult:
    action: LotExitAction
    updated_state: LotPolicyState | None
    reason: str


@dataclass(frozen=True)
class D4Result:
    action: D4Action
    reason: str


def _positive_decimal(value: Decimal | int | str | None) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite() or result <= ZERO:
        return None
    return result


def evaluate_lot_exit(
    state: LotPolicyState,
    current_premium: Decimal | int | str | None,
    *,
    quote_fresh: bool | None,
) -> LotExitResult:
    """Evaluate one filled lot only; never aggregate or infer another lot."""
    if (
        not state.lot_id
        or not state.exact_instrument_id
        or not isinstance(state.remaining_quantity, int)
        or isinstance(state.remaining_quantity, bool)
        or state.remaining_quantity <= 0
        or not isinstance(state.trailing_armed, bool)
        or _positive_decimal(state.entry_fill_premium) is None
        or quote_fresh is not True
    ):
        return LotExitResult(
            LotExitAction.BLOCKED, None, "LOT_OR_FRESH_QUOTE_EVIDENCE_UNAVAILABLE"
        )

    current = _positive_decimal(current_premium)
    if current is None:
        return LotExitResult(
            LotExitAction.BLOCKED, None, "CURRENT_PREMIUM_INVALID_OR_UNAVAILABLE"
        )

    entry = Decimal(state.entry_fill_premium)
    previous_peak = _positive_decimal(state.high_water_mark)
    if state.high_water_mark is not None and previous_peak is None:
        return LotExitResult(
            LotExitAction.BLOCKED, None, "PERSISTED_HIGH_WATER_MARK_INVALID"
        )
    if state.trailing_armed and (
        previous_peak is None or previous_peak < entry * TRAILING_ARM_MULTIPLE
    ):
        return LotExitResult(
            LotExitAction.BLOCKED, None, "TRAILING_STATE_REQUIRES_VALID_PERSISTED_HIGH_WATER"
        )

    peak = max(previous_peak or ZERO, current)
    armed = state.trailing_armed or peak >= entry * TRAILING_ARM_MULTIPLE
    updated = LotPolicyState(
        lot_id=state.lot_id,
        exact_instrument_id=state.exact_instrument_id,
        entry_fill_premium=entry,
        remaining_quantity=state.remaining_quantity,
        high_water_mark=peak,
        trailing_armed=armed,
    )

    if current <= entry * STOP_RATIO:
        return LotExitResult(
            LotExitAction.CLOSE_LOT_STOP, updated, "LOT_MARK_AT_OR_BELOW_50_PERCENT_OF_ENTRY"
        )

    if armed and current <= peak * (Decimal("1") - TRAILING_DRAWDOWN):
        return LotExitResult(
            LotExitAction.CLOSE_LOT_TRAILING, updated, "LOT_MARK_AT_OR_BELOW_90_PERCENT_OF_OWN_HIGH_WATER"
        )

    return LotExitResult(LotExitAction.HOLD, updated, "LOT_POLICY_HOLD")


def check_same_instrument_rebuy(
    *,
    previous_exact_instrument_id: str | None,
    candidate_exact_instrument_id: str | None,
    previous_actual_entry_fill: Decimal | int | str | None,
    candidate_premium: Decimal | int | str | None,
    prior_exit_flat_confirmed: bool | None,
    quote_fresh: bool | None,
) -> RebuyCheck:
    """Check only v0.5 same-contract/1.30x price conditions, not order readiness."""
    previous = _positive_decimal(previous_actual_entry_fill)
    candidate = _positive_decimal(candidate_premium)
    if (
        not previous_exact_instrument_id
        or not candidate_exact_instrument_id
        or previous_exact_instrument_id != candidate_exact_instrument_id
        or previous is None
        or candidate is None
        or prior_exit_flat_confirmed is not True
        or quote_fresh is not True
    ):
        return RebuyCheck.BLOCKED
    if candidate > previous * REBUY_MAX_RATIO:
        return RebuyCheck.BLOCKED
    return RebuyCheck.PRICE_OR_IDENTITY_CHECK_PASSED


def evaluate_d4_boundary(
    *,
    observed_at: datetime | None,
    valid_sessions_remaining: int | None,
    exact_expiry_authoritative: bool,
    calendar_authoritative: bool,
) -> D4Result:
    """Evaluate the exact D-4 11:00 KST boundary; never invent late recovery."""
    if (
        observed_at is None
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or exact_expiry_authoritative is not True
        or calendar_authoritative is not True
        or not isinstance(valid_sessions_remaining, int)
        or isinstance(valid_sessions_remaining, bool)
        or valid_sessions_remaining < 0
    ):
        return D4Result(D4Action.BLOCKED_AUTHORITY, "AUTHORITATIVE_EXPIRY_CALENDAR_OR_TIME_MISSING")

    local_time = observed_at.astimezone(KST).time().replace(tzinfo=None)
    if valid_sessions_remaining > D4_SESSIONS_REMAINING:
        return D4Result(D4Action.NO_TRIGGER, "MORE_THAN_FOUR_VALID_SESSIONS_REMAIN")
    if valid_sessions_remaining < D4_SESSIONS_REMAINING:
        return D4Result(D4Action.BLOCKED_MISSED_BOUNDARY, "D4_BOUNDARY_ALREADY_PASSED_RECOVERY_UNAPPROVED")
    if local_time < D4_DECISION_TIME:
        return D4Result(D4Action.WAIT, "BEFORE_EXACT_11_00_KST_BOUNDARY")
    if local_time > D4_DECISION_TIME:
        return D4Result(D4Action.BLOCKED_MISSED_BOUNDARY, "EXACT_11_00_KST_BOUNDARY_NOT_OBSERVED")
    return D4Result(
        D4Action.BLOCK_NEW_ENTRIES_AND_START_LIQUIDATION,
        "EXACT_D4_11_00_KST_BOUNDARY",
    )


def rank3_fallback_preconditions(
    *,
    rank4_terminal_cancel_confirmed: bool | None,
    rank4_leaves_quantity: int | None,
    late_fill_reconciled: bool | None,
    position_reconciled: bool | None,
    remaining_target_quantity: int | None,
) -> bool:
    """A cancel ACK is insufficient; all rank-4 and position reconciliation is mandatory."""
    if (
        rank4_terminal_cancel_confirmed is not True
        or not isinstance(rank4_leaves_quantity, int)
        or isinstance(rank4_leaves_quantity, bool)
        or rank4_leaves_quantity != 0
        or late_fill_reconciled is not True
        or position_reconciled is not True
        or not isinstance(remaining_target_quantity, int)
        or isinstance(remaining_target_quantity, bool)
    ):
        return False
    return remaining_target_quantity > 0
