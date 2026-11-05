from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.contracts import AnalyticsStatus
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle


def _metric(value):
    return SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)


def _context(values, *, date_str="20261102"):
    return SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        analytics=SimpleNamespace(
            as_of=datetime(2026, 11, 2, 9, 0),
            get=lambda key: _metric(values.get(key)),
        ),
        input=SimpleNamespace(common=SimpleNamespace(budget=None, date_str=date_str)),
    )


def _result(group_id, leg_id, price, *, status="FILLED", quantity=1, remaining=0):
    report = SimpleNamespace(
        leg_id=leg_id,
        status=status,
        filled_quantity=quantity,
        remaining_quantity=remaining,
        execution_price=Decimal(str(price)) if price is not None else None,
        rejected_reason=None,
    )
    return SimpleNamespace(group_id=group_id, reports=(report,), group_complete=status == "FILLED")


def _values():
    return {
        "options.dte": Decimal("10"),
        "market.current_regime": "NORMAL",
        "options.call_strike": Decimal("515"),
        "options.put_strike": Decimal("485"),
        "options.call_contract_multiplier": Decimal("250000"),
        "options.put_contract_multiplier": Decimal("250000"),
        "options.expiry_date": "20261119",
    }


def test_track8_entry_submits_call_then_put_only_after_call_fill():
    strategy = Track8MacroRegimeMonthlyStrangle(
        runtime_config_verified=True, risk_limits_available=True
    )
    context = _context(_values())

    first_signal = strategy.evaluate_entry(context)[0]
    assert first_signal.execution_proposal.option_type == "CALL"
    call_plan = strategy.build_execution_plan(
        "S8-GROUP-1", proposal=first_signal.execution_proposal
    )
    assert call_plan.group_id == "S8-GROUP-1"
    assert call_plan.purpose == "MONTHLY_STRANGLE_ENTRY_CALL"
    assert len(call_plan.legs) == 1
    assert call_plan.legs[0].option_type == "CALL"
    assert strategy.state.entry_stage == "CALL_PENDING"

    strategy.on_execution_result(
        "MONTHLY_STRANGLE_ENTRY_CALL",
        _result("S8-GROUP-1", "call", "1.35"),
    )
    assert strategy.state.entry_stage == "PUT_READY"
    assert strategy.state.call_open is True
    assert strategy.state.is_active is False

    second_signal = strategy.evaluate(context)[0]
    assert second_signal.execution_proposal.option_type == "PUT"
    put_plan = strategy.build_execution_plan(
        "S8-SECOND-SIGNAL-ID", proposal=second_signal.execution_proposal
    )
    assert put_plan.group_id == "S8-GROUP-1"
    assert put_plan.purpose == "MONTHLY_STRANGLE_ENTRY_PUT"
    assert len(put_plan.legs) == 1
    assert put_plan.legs[0].option_type == "PUT"
    assert strategy.state.entry_stage == "PUT_PENDING"

    strategy.on_execution_result(
        "MONTHLY_STRANGLE_ENTRY_PUT",
        _result("S8-GROUP-1", "put", "1.20"),
    )
    assert strategy.state.is_active is True
    assert strategy.state.entry_pending is False
    assert strategy.state.entry_stage == "COMPLETE"
    assert strategy.state.put_open is True
    assert strategy.state.premium_spent == Decimal("637500.00")


def test_track8_partial_or_rejected_first_leg_fails_closed_without_second_leg():
    strategy = Track8MacroRegimeMonthlyStrangle(
        runtime_config_verified=True, risk_limits_available=True
    )
    signal = strategy.evaluate_entry(_context(_values()))[0]
    strategy.build_execution_plan("S8-GROUP-2", proposal=signal.execution_proposal)

    strategy.on_execution_result(
        "MONTHLY_STRANGLE_ENTRY_CALL",
        _result("S8-GROUP-2", "call", "1.35", status="PARTIALLY_FILLED", quantity=0, remaining=1),
    )

    assert strategy.state.entry_stage == "CALL_PENDING"
    assert strategy.state.is_active is False
    assert strategy.state.entry_pending is True
    assert strategy._put_entry_signal() == ()


def test_track8_entry_result_group_mismatch_blocks_second_leg():
    strategy = Track8MacroRegimeMonthlyStrangle(
        runtime_config_verified=True, risk_limits_available=True
    )
    signal = strategy.evaluate_entry(_context(_values()))[0]
    strategy.build_execution_plan("S8-GROUP-3", proposal=signal.execution_proposal)

    strategy.on_execution_result(
        "MONTHLY_STRANGLE_ENTRY_CALL",
        _result("WRONG-GROUP", "call", "1.35"),
    )

    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "TRACK8_ENTRY_RESULT_GROUP_ID_MISMATCH"
    assert strategy._put_entry_signal() == ()
