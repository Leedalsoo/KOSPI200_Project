from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Iterable


class U16RepairState(str, Enum):
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    ORIGINAL_ORDER_RECONCILING = "ORIGINAL_ORDER_RECONCILING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    POLICY_INPUT_BLOCKED = "POLICY_INPUT_BLOCKED"
    REPAIR_READY = "REPAIR_READY"
    REPAIR_SUBMITTED = "REPAIR_SUBMITTED"
    REPAIR_RECONCILING = "REPAIR_RECONCILING"
    REPAIR_WAITING = "REPAIR_WAITING"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"
    REPAIR_FAILED_GROUP_BLOCKED = "REPAIR_FAILED_GROUP_BLOCKED"
    FLATTEN_REQUIRED_BLOCKED = "FLATTEN_REQUIRED_BLOCKED"


@dataclass(frozen=True)
class U16Fill:
    execution_id: str
    quantity: int


@dataclass(frozen=True)
class U16QuotePolicy:
    """All fields require an explicitly approved, validated policy; no defaults."""
    validated: bool = False
    side_to_book_rule: str | None = None
    max_quote_age_seconds: int | None = None
    max_spread: str | None = None
    spread_unit: str | None = None
    fallback_formula: str | None = None
    fallback_priority: str | None = None
    tick_rounding_rule: str | None = None

    def is_resolved(self) -> bool:
        return bool(
            self.validated
            and self.side_to_book_rule
            and self.max_quote_age_seconds is not None
            and self.max_quote_age_seconds > 0
            and self.max_spread
            and self.spread_unit
            and self.fallback_formula
            and self.fallback_priority
            and self.tick_rounding_rule
        )


@dataclass(frozen=True)
class U16RepairInput:
    group_id: str
    leg_id: str
    target_quantity: int
    original_order_terminal: bool
    original_order_cancelled_or_closed: bool
    fills: tuple[U16Fill, ...]
    position_quantity: int | None
    now: datetime
    original_order_status: str = "CANCELLED"
    first_repair_submitted_at: datetime | None = None
    additional_retry_count: int = 0
    previous_repair_terminal: bool = True
    previous_repair_reconciled: bool = True
    quote_policy: U16QuotePolicy = U16QuotePolicy()
    quote_present: bool = False
    quote_fresh: bool = False
    quote_spread_within_policy: bool = False


@dataclass(frozen=True)
class U16RepairEvaluation:
    state: U16RepairState
    reason: str
    confirmed_filled_quantity: int
    missing_quantity: int
    additional_retry_count: int
    next_retry_at: datetime | None
    client_order_id: str | None = None
    order_submission_enabled: bool = False
    flatten_order_submission_enabled: bool = False


def _blocked(
    state: U16RepairState,
    reason: str,
    filled: int = 0,
    missing: int = 0,
    retries: int = 0,
    next_retry_at: datetime | None = None,
    client_order_id: str | None = None,
) -> U16RepairEvaluation:
    return U16RepairEvaluation(
        state, reason, filled, missing, retries, next_retry_at,
        client_order_id=client_order_id,
        order_submission_enabled=False,
        flatten_order_submission_enabled=False,
    )


def evaluate_u16_repair(data: U16RepairInput) -> U16RepairEvaluation:
    """Validation-only U16 lifecycle evaluator. It never submits repair/flatten orders."""
    if not data.group_id.strip() or not data.leg_id.strip() or data.target_quantity <= 0:
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "IDENTITY_OR_TARGET_INVALID")
    if data.additional_retry_count < 0 or data.additional_retry_count > 3:
        return _blocked(
            U16RepairState.REPAIR_FAILED_GROUP_BLOCKED,
            "ADDITIONAL_RETRY_LIMIT_EXCEEDED",
            retries=max(data.additional_retry_count, 0),
        )
    terminal_status = str(data.original_order_status or "").upper()
    if data.position_quantity is None:
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "ORIGINAL_POSITION_UNCONFIRMED")
    if not data.original_order_terminal or not data.original_order_cancelled_or_closed:
        if terminal_status in {"NEW", "WORKING", "PARTIALLY_FILLED", "CANCEL_REQUESTED", "CANCEL_PENDING"}:
            return _blocked(U16RepairState.ORIGINAL_ORDER_RECONCILING, "ORIGINAL_ORDER_NOT_TERMINAL")
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "ORIGINAL_ORDER_OR_POSITION_UNCONFIRMED")
    if terminal_status not in {"CANCELLED", "REJECTED", "FILLED", "EXPIRED"}:
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "ORIGINAL_ORDER_STATUS_UNKNOWN")
    execution_ids = [fill.execution_id for fill in data.fills]
    if any(not item.strip() for item in execution_ids) or len(execution_ids) != len(set(execution_ids)):
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "MISSING_OR_DUPLICATE_EXECUTION_ID")
    if any(fill.quantity <= 0 for fill in data.fills):
        return _blocked(U16RepairState.RECONCILIATION_REQUIRED, "FILL_QUANTITY_INVALID")
    filled = sum(fill.quantity for fill in data.fills)
    if filled > data.target_quantity or data.position_quantity != filled:
        return _blocked(
            U16RepairState.RECONCILIATION_REQUIRED,
            "FILL_POSITION_OR_TARGET_MISMATCH",
            filled=filled,
            missing=max(data.target_quantity - filled, 0),
            retries=data.additional_retry_count,
        )
    missing = data.target_quantity - filled
    if missing == 0:
        return _blocked(
            U16RepairState.REPAIR_COMPLETE,
            "LEG_TARGET_FILLED_AND_POSITION_RECONCILED",
            filled=filled,
            retries=data.additional_retry_count,
        )
    if data.first_repair_submitted_at is not None:
        elapsed = (data.now - data.first_repair_submitted_at).total_seconds()
        if elapsed < 0:
            return _blocked(
                U16RepairState.RECONCILIATION_REQUIRED,
                "REPAIR_CLOCK_BEFORE_T0",
                filled, missing, data.additional_retry_count,
            )
        if elapsed >= 120:
            return _blocked(
                U16RepairState.FLATTEN_REQUIRED_BLOCKED,
                "T0_120S_DEADLINE_EXCEEDED",
                filled, missing, data.additional_retry_count,
            )
        if data.additional_retry_count >= 3:
            return _blocked(
                U16RepairState.FLATTEN_REQUIRED_BLOCKED,
                "THREE_ADDITIONAL_RETRIES_EXHAUSTED",
                filled, missing, data.additional_retry_count,
            )
        due_slot = max(0, int(elapsed // 30) - 1)
        if due_slot > data.additional_retry_count:
            next_at = data.first_repair_submitted_at + timedelta(seconds=30 * (data.additional_retry_count + 1))
            return _blocked(
                U16RepairState.REPAIR_WAITING,
                "MISSED_RETRY_SLOT_NOT_DEFERRED",
                filled, missing, data.additional_retry_count, next_at,
            )
        if elapsed < 30 * (data.additional_retry_count + 1):
            next_at = data.first_repair_submitted_at + timedelta(seconds=30 * (data.additional_retry_count + 1))
            return _blocked(
                U16RepairState.REPAIR_WAITING,
                "FIXED_T0_RETRY_SCHEDULE",
                filled, missing, data.additional_retry_count, next_at,
            )
        if not data.previous_repair_terminal or not data.previous_repair_reconciled:
            return _blocked(
                U16RepairState.REPAIR_WAITING,
                "RETRY_SLOT_SKIPPED_PREVIOUS_ORDER_NOT_RECONCILED",
                filled, missing, data.additional_retry_count,
            )
    if not data.quote_policy.is_resolved():
        return _blocked(
            U16RepairState.POLICY_INPUT_BLOCKED,
            "QUOTE_POLICY_UNRESOLVED_NULL_DEFAULT",
            filled, missing, data.additional_retry_count,
        )
    if not data.quote_present or not data.quote_fresh or not data.quote_spread_within_policy:
        return _blocked(
            U16RepairState.POLICY_INPUT_BLOCKED,
            "QUOTE_MISSING_STALE_OR_SPREAD_INVALID",
            filled, missing, data.additional_retry_count,
        )
    # No order command is emitted. This READY verdict is a validation result only.
    attempt_number = data.additional_retry_count + (
        1 if data.first_repair_submitted_at is not None else 0
    )
    identity = f"{data.group_id}|{data.leg_id}|U16|{attempt_number}"
    client_order_id = "u16r-" + sha256(identity.encode("utf-8")).hexdigest()[:24]
    return _blocked(
        U16RepairState.REPAIR_READY,
        "RECONCILED_SHORTFALL_AND_VALIDATION_INPUTS_READY_NO_SUBMISSION",
        filled, missing, data.additional_retry_count,
        client_order_id=client_order_id,
    )


def evaluate_u16_group_activation(
    target_quantities: dict[str, int],
    reconciled_fills: dict[str, int],
    position_quantities: dict[str, int],
) -> tuple[bool, str]:
    """A group is complete only when all four legs match fills and positions."""
    if len(target_quantities) != 4 or set(target_quantities) != set(reconciled_fills) or set(target_quantities) != set(position_quantities):
        return False, "FOUR_LEG_EVIDENCE_REQUIRED"
    for leg_id, target in target_quantities.items():
        if target <= 0 or reconciled_fills[leg_id] != target or position_quantities[leg_id] != target:
            return False, "ALL_FOUR_LEGS_NOT_FILLED_AND_RECONCILED"
    return True, "ALL_FOUR_LEGS_FILLED_AND_RECONCILED"
