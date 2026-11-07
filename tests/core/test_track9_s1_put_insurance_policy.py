from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from core.strategy.track9_s1_put_insurance_policy import (
    D4Action,
    LotExitAction,
    LotPolicyState,
    RebuyCheck,
    check_same_instrument_rebuy,
    evaluate_d4_boundary,
    evaluate_lot_exit,
    rank3_fallback_preconditions,
)


def lot(**changes):
    values = {
        "lot_id": "lot-a",
        "exact_instrument_id": "KOSPI200-202612-P-400",
        "entry_fill_premium": Decimal("100"),
        "remaining_quantity": 2,
    }
    values.update(changes)
    return LotPolicyState(**values)


def test_lot_stop_is_inclusive_and_only_returns_that_lot():
    result = evaluate_lot_exit(lot(), Decimal("50"), quote_fresh=True)
    assert result.action is LotExitAction.CLOSE_LOT_STOP
    assert result.updated_state.lot_id == "lot-a"
    assert result.updated_state.remaining_quantity == 2


def test_trailing_arms_at_two_times_without_immediate_fixed_take_profit():
    result = evaluate_lot_exit(lot(), Decimal("200"), quote_fresh=True)
    assert result.action is LotExitAction.HOLD
    assert result.updated_state.trailing_armed is True
    assert result.updated_state.high_water_mark == Decimal("200")


def test_trailing_closes_at_inclusive_ten_percent_drawdown_from_own_peak():
    state = lot(high_water_mark=Decimal("250"), trailing_armed=True)
    result = evaluate_lot_exit(state, Decimal("225"), quote_fresh=True)
    assert result.action is LotExitAction.CLOSE_LOT_TRAILING
    assert result.updated_state.high_water_mark == Decimal("250")


def test_lot_high_water_is_independent_and_advances():
    state = lot(high_water_mark=Decimal("210"), trailing_armed=True)
    result = evaluate_lot_exit(state, Decimal("240"), quote_fresh=True)
    assert result.action is LotExitAction.HOLD
    assert result.updated_state.high_water_mark == Decimal("240")


@pytest.mark.parametrize("fresh", [None, False])
def test_missing_or_stale_quote_blocks_lot_exit_evaluation(fresh):
    result = evaluate_lot_exit(lot(), Decimal("40"), quote_fresh=fresh)
    assert result.action is LotExitAction.BLOCKED
    assert result.updated_state is None


def test_invalid_persisted_high_water_blocks():
    result = evaluate_lot_exit(lot(high_water_mark=Decimal("0")), 40, quote_fresh=True)
    assert result.action is LotExitAction.BLOCKED


def test_trailing_armed_without_persisted_high_water_blocks():
    result = evaluate_lot_exit(lot(trailing_armed=True), 220, quote_fresh=True)
    assert result.action is LotExitAction.BLOCKED


def test_rebuy_price_boundary_is_inclusive_for_same_exact_contract():
    result = check_same_instrument_rebuy(
        previous_exact_instrument_id="KOSPI200-202612-P-400",
        candidate_exact_instrument_id="KOSPI200-202612-P-400",
        previous_actual_entry_fill=100,
        candidate_premium=130,
        prior_exit_flat_confirmed=True,
        quote_fresh=True,
    )
    assert result is RebuyCheck.PRICE_OR_IDENTITY_CHECK_PASSED


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate_exact_instrument_id": "KOSPI200-202612-P-402.5"},
        {"candidate_premium": 130.01},
        {"prior_exit_flat_confirmed": False},
        {"quote_fresh": False},
        {"previous_actual_entry_fill": None},
    ],
)
def test_rebuy_blocks_wrong_contract_unreconciled_or_unverified_inputs(changes):
    values = {
        "previous_exact_instrument_id": "KOSPI200-202612-P-400",
        "candidate_exact_instrument_id": "KOSPI200-202612-P-400",
        "previous_actual_entry_fill": 100,
        "candidate_premium": 100,
        "prior_exit_flat_confirmed": True,
        "quote_fresh": True,
    }
    values.update(changes)
    assert check_same_instrument_rebuy(**values) is RebuyCheck.BLOCKED


def test_d4_triggers_only_at_exact_four_sessions_and_exact_1100_kst():
    result = evaluate_d4_boundary(
        observed_at=datetime(2026, 11, 2, 11, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        valid_sessions_remaining=4,
        exact_expiry_authoritative=True,
        calendar_authoritative=True,
    )
    assert result.action is D4Action.BLOCK_NEW_ENTRIES_AND_START_LIQUIDATION


def test_d4_before_1100_waits():
    result = evaluate_d4_boundary(
        observed_at=datetime(2026, 11, 2, 10, 59, 59, tzinfo=ZoneInfo("Asia/Seoul")),
        valid_sessions_remaining=4,
        exact_expiry_authoritative=True,
        calendar_authoritative=True,
    )
    assert result.action is D4Action.WAIT


@pytest.mark.parametrize(
    "sessions,clock,expected",
    [
        (5, datetime(2026, 11, 2, 11, 0, tzinfo=ZoneInfo("Asia/Seoul")), D4Action.NO_TRIGGER),
        (4, datetime(2026, 11, 2, 11, 0, 1, tzinfo=ZoneInfo("Asia/Seoul")), D4Action.BLOCKED_MISSED_BOUNDARY),
        (3, datetime(2026, 11, 3, 11, 0, tzinfo=ZoneInfo("Asia/Seoul")), D4Action.BLOCKED_MISSED_BOUNDARY),
    ],
)
def test_d4_does_not_invent_late_or_missed_boundary_recovery(sessions, clock, expected):
    result = evaluate_d4_boundary(
        observed_at=clock,
        valid_sessions_remaining=sessions,
        exact_expiry_authoritative=True,
        calendar_authoritative=True,
    )
    assert result.action is expected


def test_d4_missing_authoritative_expiry_or_calendar_blocks():
    result = evaluate_d4_boundary(
        observed_at=datetime(2026, 11, 2, 11, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        valid_sessions_remaining=4,
        exact_expiry_authoritative=False,
        calendar_authoritative=True,
    )
    assert result.action is D4Action.BLOCKED_AUTHORITY


@pytest.mark.parametrize(
    "changes",
    [
        {"rank4_terminal_cancel_confirmed": False},
        {"rank4_leaves_quantity": 1},
        {"rank4_leaves_quantity": True},
        {"late_fill_reconciled": False},
        {"position_reconciled": False},
        {"remaining_target_quantity": 0},
        {"remaining_target_quantity": None},
    ],
)
def test_rank3_fallback_requires_all_terminal_and_position_preconditions(changes):
    values = {
        "rank4_terminal_cancel_confirmed": True,
        "rank4_leaves_quantity": 0,
        "late_fill_reconciled": True,
        "position_reconciled": True,
        "remaining_target_quantity": 1,
    }
    values.update(changes)
    assert rank3_fallback_preconditions(**values) is False


def test_rank3_fallback_allowed_only_after_complete_reconciliation():
    assert rank3_fallback_preconditions(
        rank4_terminal_cancel_confirmed=True,
        rank4_leaves_quantity=0,
        late_fill_reconciled=True,
        position_reconciled=True,
        remaining_target_quantity=2,
    ) is True
