from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7ExecutionInput,
    Track7State,
    Track7VolatilitySkewWeeklyInsurance,
)


def _metric(value):
    return SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)


def test_track7_default_provisional_config_blocks_entry() -> None:
    strategy = Track7VolatilitySkewWeeklyInsurance()
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 19, 9, 30)),
        input=SimpleNamespace(
            payload=Track7ExecutionInput(
                strategy_id=strategy.strategy_id,
                expiry="20261022",
                reference_price=Decimal("500"),
                put_strike=Decimal("487.5"),
                call_strike=Decimal("512.5"),
                contract_multiplier=Decimal("250000"),
            )
        ),
    )

    assert strategy.evaluate(context) == ()


def test_track7_entry_state_requires_authoritative_pair_fills() -> None:
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True, risk_limits_available=True
    )
    strategy.state = Track7State(
        entry_pending=True,
        expiry="20261022",
        put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
    )
    ts = datetime(2026, 10, 19, 9, 35)
    reports = [
        SimpleNamespace(leg_id="put", status="FILLED", filled_quantity=1,
                        remaining_quantity=0, execution_id="p1",
                        execution_timestamp=ts, execution_price=Decimal("1.2")),
        SimpleNamespace(leg_id="call", status="FILLED", filled_quantity=1,
                        remaining_quantity=0, execution_id="c1",
                        execution_timestamp=ts, execution_price=Decimal("1.1")),
    ]

    strategy.on_execution_result(
        "WEEKLY_INSURANCE_ENTRY",
        SimpleNamespace(reports=reports, group_complete=True, position_flat=False),
    )

    assert strategy.state.insurance_active is True
    assert strategy.state.entry_pending is False
    assert strategy.state.put_entry_fill_price == Decimal("1.2")
    assert strategy.state.call_entry_fill_price == Decimal("1.1")


def test_track7_per_leg_50pct_stop_creates_only_that_leg_close_plan() -> None:
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True, risk_limits_available=True
    )
    strategy.state = Track7State(
        insurance_active=True, expiry="20261022",
        put_strike=Decimal("487.5"), call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        put_entry_fill_price=Decimal("1.0"), call_entry_fill_price=Decimal("1.0"),
        put_peak_mark=Decimal("1.0"), call_peak_mark=Decimal("1.0"),
        put_open=True, call_open=True,
    )
    analytics = SimpleNamespace(
        as_of=datetime(2026, 10, 21, 13, 0),
        get=lambda key: _metric({
            "options.track7_put_mark_price": Decimal("0.5"),
            "options.track7_call_mark_price": Decimal("1.1"),
        }.get(key)),
    )
    signals = strategy.evaluate(
        SimpleNamespace(strategy_id=strategy.strategy_id, analytics=analytics)
    )

    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.tag_id == "WEEKLY_INSURANCE_CLOSE_PUT"
    plan = strategy.build_execution_plan(group_id="s7-put-close", proposal=proposal)
    assert plan.purpose == "WEEKLY_INSURANCE_CLOSE_PUT"
    assert len(plan.legs) == 1
    assert plan.legs[0].leg_id == "put"
    assert plan.legs[0].side == "SELL"


def test_track7_expiry_close_boundary_is_1510() -> None:
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.state = Track7State(
        insurance_active=True, expiry="20261021",
        put_strike=Decimal("487.5"), call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        put_entry_fill_price=Decimal("1.0"), call_entry_fill_price=Decimal("1.0"),
        put_peak_mark=Decimal("1.0"), call_peak_mark=Decimal("1.0"),
        put_open=True, call_open=True,
    )

    def context(at):
        analytics = SimpleNamespace(
            as_of=at,
            get=lambda key: _metric({
                "options.track7_put_mark_price": Decimal("1.1"),
                "options.track7_call_mark_price": Decimal("1.1"),
            }.get(key)),
        )
        return SimpleNamespace(strategy_id=strategy.strategy_id, analytics=analytics)

    assert strategy.evaluate(context(datetime(2026, 10, 21, 15, 9, 59))) == ()
    signals = strategy.evaluate(context(datetime(2026, 10, 21, 15, 10, 0)))
    assert len(signals) == 1
    assert signals[0].reason == "WEEKLY_EXACT_EXPIRY_15:10"
