from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9State
from core.strategy.track9_independent_policy import (
    Track9OpenLot, Track9OptionCandidate, Track9RuntimeInput, Track9SyntheticQuote,
)

KST = timezone(timedelta(hours=9))

def runtime_input(opening: str) -> Track9RuntimeInput:
    expiry = date(2026, 11, 12)
    put_id = "SYNTHETIC_CONTRACT:S9-20261112-PUT-500"
    call_id = "SYNTHETIC_CONTRACT:S9-20261112-CALL-500"
    observed = datetime(2026, 11, 9, 9, 0, tzinfo=KST)
    opened = datetime(2026, 11, 6, 15, 0, tzinfo=KST)
    return Track9RuntimeInput(
        contract_candidates=(
            Track9OptionCandidate(put_id, expiry, "PUT", Decimal("500"), "STANDARD", Decimal("100000"), True),
            Track9OptionCandidate(call_id, expiry, "CALL", Decimal("500"), "STANDARD", Decimal("100000"), True),
        ),
        underlying_price=Decimal("506"), as_of=observed,
        previous_official_close=Decimal("500"), next_session_official_open=Decimal(opening),
        option_quotes=(
            Track9SyntheticQuote(put_id, "PUT", Decimal("500"), expiry, Decimal("10"), Decimal("10.2"), Decimal("10.1"), observed, "SYNTHETIC:DERIVED_SCENARIO"),
            Track9SyntheticQuote(call_id, "CALL", Decimal("500"), expiry, Decimal("11"), Decimal("11.2"), Decimal("11.1"), observed, "SYNTHETIC:DERIVED_SCENARIO"),
        ),
        open_lots=(
            Track9OpenLot("track9_event_overnight_insurance", put_id, expiry, "PUT", Decimal("500"), 1, "BUY", None, Decimal("100000"), opened),
            Track9OpenLot("track9_event_overnight_insurance", call_id, expiry, "CALL", Decimal("500"), 1, "BUY", None, Decimal("100000"), opened),
        ),
        provenance="SYNTHETIC", source_provenance=tuple((key, "SYNTHETIC") for key in (
            "contract_identity", "contract_multiplier", "tradability", "option_quotes",
            "previous_official_close", "next_session_official_open", "trading_calendar",
            "account", "position", "risk_limits",)),
        scenario_id="S9_RECOVERY_TEST", manifest_sha256="a"*64, dataset_sha256="b"*64,
        contract_profile_sha256="c"*64, risk_profile_sha256="d"*64,
        max_quote_age_seconds=Decimal("5"),
    )

def test_fresh_strategy_restores_open_virtual_lots_and_closes_on_next_session_open() -> None:
    payload=runtime_input("506")
    strategy=Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    assert strategy.state.state == "OVERNIGHT_INSURANCE_ACTIVE"
    assert strategy.state.entry_date == date(2026, 11, 6)
    signals=strategy._opening_exit_signal(payload)
    assert len(signals)==1
    assert "OPENING_MOVE_AT_OR_ABOVE_1PCT_CLOSE_INSURANCE" in signals[0].reason


def test_fresh_strategy_restores_open_lots_and_uses_stop_loss_below_one_percent() -> None:
    payload=runtime_input("502.5")
    strategy=Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    signals=strategy._opening_exit_signal(payload)
    assert len(signals)==1
    assert "OPENING_MOVE_BELOW_1PCT_STOP_LOSS" in signals[0].reason


def test_completed_exit_preserves_the_approved_exit_reason_for_audit() -> None:
    strategy = Track9EventOvernightInsurance()
    reason = "OPENING_MOVE_BELOW_1PCT_STOP_LOSS"
    strategy.state = Track9State(exit_reason=reason, state="EXIT_PENDING")
    strategy._exit_pending = True
    strategy.on_execution_result(
        "OVERNIGHT_INSURANCE_CLOSE",
        SimpleNamespace(group_complete=True, position_flat=True, reports=()),
    )
    assert strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"
    assert strategy.state.exit_reason == reason


def test_entry_partial_put_and_rejected_call_stays_reconciliation_required() -> None:
    strategy = Track9EventOvernightInsurance()
    reports = (
        SimpleNamespace(leg_id="put", status="PARTIALLY_FILLED", filled_quantity=0),
        SimpleNamespace(leg_id="call", status="REJECTED", filled_quantity=0),
    )
    strategy.on_execution_result(
        "OVERNIGHT_INSURANCE",
        SimpleNamespace(group_complete=False, position_flat=False, reports=reports),
    )
    assert strategy.state.state == "RECONCILIATION_REQUIRED"
    assert strategy.state.put_entry_fill_price is None
    assert strategy.state.call_entry_fill_price is None
    assert strategy._exit_pending is False


def test_entry_one_leg_filled_other_rejected_is_held_as_partial_overnight_insurance() -> None:
    strategy = Track9EventOvernightInsurance()
    reports = (
        SimpleNamespace(leg_id="put", status="FILLED", filled_quantity=1, execution_price=Decimal("10")),
        SimpleNamespace(leg_id="call", status="REJECTED", filled_quantity=0),
    )
    strategy.on_execution_result(
        "OVERNIGHT_INSURANCE",
        SimpleNamespace(group_complete=False, position_flat=False, reports=reports),
    )
    assert strategy.state.state == "OVERNIGHT_INSURANCE_PARTIAL"
    assert strategy.state.put_entry_fill_price == Decimal("10")
    assert strategy.state.call_entry_fill_price is None


def test_close_with_one_leg_unresolved_remains_exit_pending_until_flat_confirmation() -> None:
    strategy = Track9EventOvernightInsurance()
    reason = "OPENING_MOVE_BELOW_1PCT_STOP_LOSS"
    strategy.state = Track9State(exit_reason=reason, state="EXIT_PENDING")
    strategy._exit_pending = True
    reports = (
        SimpleNamespace(leg_id="put", status="FILLED", filled_quantity=1),
        SimpleNamespace(leg_id="call", status="CANCELLED", filled_quantity=0),
    )
    strategy.on_execution_result(
        "OVERNIGHT_INSURANCE_CLOSE",
        SimpleNamespace(group_complete=False, position_flat=False, reports=reports),
    )
    assert strategy.state.state == "EXIT_PENDING"
    assert strategy.state.exit_reason == reason
    assert strategy._exit_pending is True


def test_initialize_with_single_open_s9_leg_restores_partial_overnight_insurance() -> None:
    from dataclasses import replace

    payload = replace(runtime_input("502.5"), open_lots=runtime_input("502.5").open_lots[:1])
    strategy = Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    assert strategy.state.state == "OVERNIGHT_INSURANCE_PARTIAL"
    assert strategy.state.entry_qty == 1
    assert len(strategy.state.partial_open_lots) == 1


def test_partial_one_leg_is_closed_on_next_session_using_existing_opening_rule() -> None:
    from dataclasses import replace
    base = runtime_input("506")
    partial_lot = base.open_lots[:1]
    entry_time = datetime(2026, 11, 6, 15, 0, tzinfo=KST)
    payload = replace(base, as_of=entry_time, open_lots=partial_lot,
                      option_quotes=(replace(base.option_quotes[0], observed_at=entry_time),))
    strategy = Track9EventOvernightInsurance()
    strategy.initialize(SimpleNamespace(input=SimpleNamespace(payload=payload)))
    signal = strategy._partial_opening_exit_signal(payload)
    # Same-day input is not eligible for overnight exit.
    assert signal == ()
    next_day = replace(
        payload,
        as_of=datetime(2026, 11, 9, 9, 0, tzinfo=KST),
        option_quotes=(replace(base.option_quotes[0],
                               observed_at=datetime(2026, 11, 9, 9, 0, tzinfo=KST)),),
    )
    signal = strategy._partial_opening_exit_signal(next_day)
    assert len(signal) == 1
    assert signal[0].execution_proposal.side == "SELL"
    assert signal[0].execution_proposal.option_type == "PUT"


def test_s9_entry_plan_is_strictly_buy_buy_and_sell_entry_is_rejected() -> None:
    from dataclasses import replace

    base = runtime_input("506")
    entry_time = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    payload = replace(
        base, as_of=entry_time,
        option_quotes=tuple(replace(item, observed_at=entry_time) for item in base.option_quotes),
    )
    strategy = Track9EventOvernightInsurance()
    signals = strategy._entry_signal(payload)
    assert len(signals) == 1
    plan = strategy.build_execution_plan("S9-BUY-BUY", proposal=signals[0].execution_proposal)
    assert [leg.side for leg in plan.legs] == ["BUY", "BUY"]
    sell_proposal = replace(signals[0].execution_proposal, side="SELL")
    with pytest.raises(ValueError, match="TRACK9_ENTRY_MUST_BE_BUY_BUY"):
        strategy.build_execution_plan("S9-SELL-ENTRY-BLOCKED", proposal=sell_proposal)
