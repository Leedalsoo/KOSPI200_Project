from datetime import datetime, timedelta, timezone

import pytest

from core.strategy.track2_u16_repair_lifecycle import (
    U16Fill,
    U16QuotePolicy,
    U16RepairInput,
    U16RepairState,
    evaluate_u16_group_activation,
    evaluate_u16_repair,
)


T0 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)


def base(**overrides):
    values = dict(
        group_id="g1",
        leg_id="inner_put",
        target_quantity=3,
        original_order_terminal=True,
        original_order_cancelled_or_closed=True,
        original_order_status="CANCELLED",
        fills=(U16Fill("f1", 1),),
        position_quantity=1,
        now=T0,
    )
    values.update(overrides)
    return U16RepairInput(**values)


def resolved_policy():
    return U16QuotePolicy(
        validated=True,
        side_to_book_rule="EXPLICIT_VALIDATION_ONLY_RULE",
        max_quote_age_seconds=5,
        max_spread="0.1",
        spread_unit="PRICE",
        fallback_formula="EXPLICIT_VALIDATION_ONLY_FORMULA",
        fallback_priority="EXPLICIT_VALIDATION_ONLY_PRIORITY",
        tick_rounding_rule="EXPLICIT_VALIDATION_ONLY_TICK",
    )


def valid_quote(**overrides):
    values = dict(
        quote_policy=resolved_policy(),
        quote_present=True,
        quote_fresh=True,
        quote_spread_within_policy=True,
    )
    values.update(overrides)
    return values


def test_zero_fill_uses_full_target_as_shortfall():
    result = evaluate_u16_repair(base(fills=(), position_quantity=0))
    assert result.state == U16RepairState.POLICY_INPUT_BLOCKED
    assert result.confirmed_filled_quantity == 0
    assert result.missing_quantity == 3


def test_partial_fill_calculates_only_unfilled_quantity():
    result = evaluate_u16_repair(base())
    assert result.missing_quantity == 2
    assert result.confirmed_filled_quantity == 1


def test_full_fill_completes_only_after_position_reconciliation():
    result = evaluate_u16_repair(base(fills=(U16Fill("f1", 3),), position_quantity=3))
    assert result.state == U16RepairState.REPAIR_COMPLETE


@pytest.mark.parametrize(
    "overrides",
    [
        {"original_order_terminal": False},
        {"original_order_cancelled_or_closed": False},
        {"position_quantity": None},
        {"position_quantity": 0},
        {"fills": (U16Fill("dup", 1), U16Fill("dup", 1)), "position_quantity": 2},
        {"fills": (U16Fill("", 1),), "position_quantity": 1},
        {"fills": (U16Fill("f1", 4),), "position_quantity": 4},
    ],
)
def test_unknown_or_mismatched_reconciliation_fails_closed(overrides):
    result = evaluate_u16_repair(base(**overrides))
    assert result.state == U16RepairState.RECONCILIATION_REQUIRED
    assert not result.order_submission_enabled


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED"])
def test_rejected_or_cancelled_original_requires_confirmed_terminal_reconciliation(status):
    result = evaluate_u16_repair(base(
        original_order_status=status,
        fills=(),
        position_quantity=0,
    ))
    assert result.state == U16RepairState.POLICY_INPUT_BLOCKED
    assert result.missing_quantity == 3


def test_cancel_fill_race_mismatch_blocks_before_any_repair():
    result = evaluate_u16_repair(base(
        original_order_status="CANCELLED",
        fills=(U16Fill("late-fill", 2),),
        position_quantity=1,
    ))
    assert result.state == U16RepairState.RECONCILIATION_REQUIRED
    assert result.reason == "FILL_POSITION_OR_TARGET_MISMATCH"


def test_unknown_original_terminal_status_blocks():
    result = evaluate_u16_repair(base(original_order_status="UNKNOWN"))
    assert result.state == U16RepairState.RECONCILIATION_REQUIRED


def test_unresolved_policy_null_default_blocks_order_creation():
    result = evaluate_u16_repair(base())
    assert result.state == U16RepairState.POLICY_INPUT_BLOCKED
    assert result.reason == "QUOTE_POLICY_UNRESOLVED_NULL_DEFAULT"
    assert result.order_submission_enabled is False


@pytest.mark.parametrize(
    "quote_fields",
    [
        {"quote_present": False},
        {"quote_fresh": False},
        {"quote_spread_within_policy": False},
    ],
)
def test_missing_stale_or_wide_quote_blocks(quote_fields):
    result = evaluate_u16_repair(base(**valid_quote(**quote_fields)))
    assert result.state == U16RepairState.POLICY_INPUT_BLOCKED


def test_resolved_validation_inputs_yield_ready_but_never_submit():
    result = evaluate_u16_repair(base(**valid_quote()))
    assert result.state == U16RepairState.REPAIR_READY
    assert result.missing_quantity == 2
    assert result.order_submission_enabled is False
    assert result.client_order_id.startswith("u16r-")


def test_first_repair_deadline_is_fixed_from_t0():
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=120),
    ))
    assert result.state == U16RepairState.FLATTEN_REQUIRED_BLOCKED
    assert result.reason == "T0_120S_DEADLINE_EXCEEDED"
    assert result.flatten_order_submission_enabled is False


@pytest.mark.parametrize(
    ("elapsed", "retry_count", "expected"),
    [
        (29, 0, U16RepairState.REPAIR_WAITING),
        (30, 0, U16RepairState.POLICY_INPUT_BLOCKED),
        (59, 1, U16RepairState.REPAIR_WAITING),
        (60, 1, U16RepairState.POLICY_INPUT_BLOCKED),
        (90, 2, U16RepairState.POLICY_INPUT_BLOCKED),
    ],
)
def test_retry_schedule_is_fixed_at_t0(elapsed, retry_count, expected):
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=elapsed),
        additional_retry_count=retry_count,
    ))
    assert result.state == expected


def test_missed_retry_slot_is_not_deferred():
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=60),
        additional_retry_count=0,
    ))
    assert result.state == U16RepairState.REPAIR_WAITING
    assert result.reason == "MISSED_RETRY_SLOT_NOT_DEFERRED"


def test_retry_slot_is_skipped_if_previous_order_not_reconciled():
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=30),
        previous_repair_terminal=False,
        **valid_quote(),
    ))
    assert result.state == U16RepairState.REPAIR_WAITING
    assert result.reason == "RETRY_SLOT_SKIPPED_PREVIOUS_ORDER_NOT_RECONCILED"


def test_retry_count_limit_blocks_after_three_additional_attempts():
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=91),
        additional_retry_count=3,
    ))
    assert result.state == U16RepairState.FLATTEN_REQUIRED_BLOCKED
    assert result.flatten_order_submission_enabled is False


def test_group_activation_requires_all_four_fills_and_positions():
    targets = {"inner_put": 1, "inner_call": 1, "outer_put": 1, "outer_call": 1}
    assert evaluate_u16_group_activation(targets, targets, targets) == (
        True, "ALL_FOUR_LEGS_FILLED_AND_RECONCILED"
    )
    partial = dict(targets, outer_call=0)
    assert evaluate_u16_group_activation(targets, partial, partial)[0] is False


def test_group_activation_rejects_missing_leg_evidence():
    assert evaluate_u16_group_activation({"a": 1}, {"a": 1}, {"a": 1}) == (
        False, "FOUR_LEG_EVIDENCE_REQUIRED"
    )




def test_repair_submit_timeout_or_unknown_previous_order_is_not_retried_blindly():
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=30),
        previous_repair_terminal=False,
        previous_repair_reconciled=False,
        **valid_quote(),
    ))
    assert result.state == U16RepairState.REPAIR_WAITING
    assert result.reason == "RETRY_SLOT_SKIPPED_PREVIOUS_ORDER_NOT_RECONCILED"
    assert result.order_submission_enabled is False


@pytest.mark.parametrize("elapsed", [119, 119.999])
def test_deadline_is_not_extended_before_120_second_boundary(elapsed):
    result = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=elapsed),
        additional_retry_count=3,
    ))
    assert result.state == U16RepairState.FLATTEN_REQUIRED_BLOCKED
    assert result.reason == "THREE_ADDITIONAL_RETRIES_EXHAUSTED"


def test_fourth_additional_retry_is_rejected():
    result = evaluate_u16_repair(base(additional_retry_count=4))
    assert result.state == U16RepairState.REPAIR_FAILED_GROUP_BLOCKED
    assert result.reason == "ADDITIONAL_RETRY_LIMIT_EXCEEDED"



def test_original_order_pending_state_is_explicitly_reconciling():
    result = evaluate_u16_repair(base(
        original_order_terminal=False,
        original_order_cancelled_or_closed=False,
        original_order_status="CANCEL_PENDING",
    ))
    assert result.state == U16RepairState.ORIGINAL_ORDER_RECONCILING


def test_client_order_id_is_deterministic_and_attempt_scoped_without_submission():
    first = evaluate_u16_repair(base(**valid_quote()))
    same = evaluate_u16_repair(base(**valid_quote()))
    retry = evaluate_u16_repair(base(
        first_repair_submitted_at=T0,
        now=T0 + timedelta(seconds=30),
        additional_retry_count=0,
        **valid_quote(),
    ))
    assert first.client_order_id == same.client_order_id
    assert first.client_order_id != retry.client_order_id
    assert first.order_submission_enabled is False
    assert retry.order_submission_enabled is False
