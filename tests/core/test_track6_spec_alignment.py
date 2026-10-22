from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track6_daily_tail_insurance import (
    Track6DailyTailInsurance,
    Track6State,
    Track6ExecutionInput,
)


def test_track6_default_provisional_config_blocks_entry() -> None:
    strategy = Track6DailyTailInsurance()
    context = SimpleNamespace(
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 10, 0)),
        input=SimpleNamespace(
            payload=Track6ExecutionInput(
                strategy_id=strategy.strategy_id,
                date_str="20261021",
                listed_put_strike=Decimal("490"),
                listed_call_strike=Decimal("510"),
                contract_multiplier=Decimal("250000"),
            )
        ),
    )

    assert strategy.evaluate_buy(context) == ()


def test_track6_entry_becomes_active_only_after_authoritative_pair_fills() -> None:
    strategy = Track6DailyTailInsurance()
    strategy.state = Track6State(
        is_active=False,
        entry_pending=True,
        bought_date="20261021",
        long_put_strike=Decimal("490"),
        long_call_strike=Decimal("510"),
    )
    ts = datetime(2026, 10, 21, 10, 5)
    reports = [
        SimpleNamespace(
            leg_id="put", status="FILLED", filled_quantity=1, remaining_quantity=0,
            execution_id="put-fill", execution_timestamp=ts, execution_price=Decimal("2.0"),
        ),
        SimpleNamespace(
            leg_id="call", status="FILLED", filled_quantity=1, remaining_quantity=0,
            execution_id="call-fill", execution_timestamp=ts, execution_price=Decimal("2.1"),
        ),
    ]

    strategy.on_execution_result(
        "DAILY_TAIL_INSURANCE_ENTRY",
        SimpleNamespace(reports=reports, group_complete=True, position_flat=False),
    )

    assert strategy.state.is_active is True
    assert strategy.state.entry_pending is False


def test_track6_force_close_boundary_is_1510_and_not_1500_or_1515() -> None:
    strategy = Track6DailyTailInsurance()
    strategy.state = Track6State(
        is_active=True,
        bought_date="20261021",
        long_put_strike=Decimal("490"),
        long_call_strike=Decimal("510"),
    )

    before = SimpleNamespace(
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 15, 9, 59))
    )
    at_cutoff = SimpleNamespace(
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 15, 10, 0))
    )

    assert strategy.evaluate_expiry_cutoff(before) == ()
    signals = strategy.evaluate_expiry_cutoff(at_cutoff)
    assert len(signals) == 1
    assert signals[0].reason == "DAILY_INSURANCE_15:10_FORCE_CLOSE"


def test_track6_underlying_intrinsic_proxy_does_not_trigger_option_trailing() -> None:
    strategy = Track6DailyTailInsurance()
    strategy.state = Track6State(
        is_active=True,
        bought_date="20261021",
        long_put_strike=Decimal("490"),
        long_call_strike=Decimal("510"),
    )
    context = SimpleNamespace(
        analytics=SimpleNamespace(
            as_of=datetime(2026, 10, 21, 14, 0),
            get=lambda key: SimpleNamespace(status="AVAILABLE", value=Decimal("1000")),
        )
    )

    assert strategy.evaluate_take_profit(context) == ()
