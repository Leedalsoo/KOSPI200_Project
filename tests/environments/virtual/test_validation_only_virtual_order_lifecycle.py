from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.clock import VirtualClock
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter


class CommandContext:
    def build_command(self, order):
        return order


def _command(client_order_id="order-1"):
    return SimpleNamespace(
        client_order_id=client_order_id,
        track_id="track7",
        asset_type="OPTION",
        side="BUY",
        qty=1,
        price=Decimal("10"),
        requested_price=Decimal("10"),
        symbol="SYNTHETIC-CALL",
        option_type="CALL",
        strike=Decimal("500"),
        expiry="20261105",
        strategy_id="track7_volatility_skew_weekly_insurance",
        group_id="group-1",
        leg_id="call",
        instrument_id="SYNTHETIC-CALL",
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC_VALIDATION_ONLY",
    )


def _runtime():
    clock = VirtualClock(datetime(2026, 11, 3, 9, 0, 0))
    runtime = VirtualSecuritiesFirmRuntime(initial_capital=50_000_000, clock=clock)
    timeout = Track7OrderTimeoutRuntimeSource(
        clock,
        Track7OrderTimeoutPolicy(Decimal("600"), "VALIDATION_ONLY_10M"),
    )
    runtime.attach_timeout_source(timeout)
    return clock, runtime


def _tick(clock):
    return SimpleNamespace(
        timestamp=clock.now().isoformat(),
        bid_price=0.0,
        ask_price=0.0,
        last_price=None,
        instrument_id="UNRELATED",
        symbol="UNRELATED",
    )


def test_unfilled_order_waits_until_timeout_then_is_cancelled_and_confirmed():
    clock, runtime = _runtime()
    command = _command()
    submitted = runtime.process_order(command)
    assert submitted.status == "NEW"
    assert (submitted.group_id, submitted.leg_id) == (command.group_id, command.leg_id)
    pending = runtime.query_order(command.client_order_id)
    assert pending.status == "NEW"
    assert (pending.group_id, pending.leg_id) == (command.group_id, command.leg_id)

    clock.sleep_policy(599)
    runtime.process_market_data(_tick(clock))
    assert runtime.query_order(command.client_order_id).status == "NEW"

    clock.sleep_policy(1)
    runtime.process_market_data(_tick(clock))
    confirmed = runtime.query_order(command.client_order_id)
    assert confirmed.status == "CANCELLED"
    assert (confirmed.group_id, confirmed.leg_id) == (command.group_id, command.leg_id)
    assert confirmed.remaining_qty == 1
    assert runtime.order_book.get_pending_order(command.client_order_id) is None


def test_order_fills_when_quote_arrives_before_timeout():
    clock, runtime = _runtime()
    command = _command("order-fill")
    submitted = runtime.process_order(command)
    assert submitted.status == "NEW"

    runtime.order_book.update_bid_ask(9.9, 10.0, instrument_id=command.instrument_id)
    runtime.process_pending_orders()
    confirmed = runtime.query_order(command.client_order_id)

    assert confirmed.status == "FILLED"
    assert confirmed.executed_qty == 1
    assert confirmed.exec_id
    assert confirmed.executed_price == 10.0
    assert confirmed.fee == 0.0
    assert command.instrument_id in runtime.account.positions


def test_cancel_race_returns_filled_terminal_state_instead_of_false_cancel():
    _clock, runtime = _runtime()
    command = _command("order-race")
    runtime.process_order(command)
    runtime.order_book.update_bid_ask(9.9, 10.0, instrument_id=command.instrument_id)
    runtime.process_pending_orders()

    result = runtime.cancel_order(command.client_order_id)
    assert result.status == "FILLED"
    assert runtime.query_order(command.client_order_id).status == "FILLED"


def test_execution_adapter_requeries_after_cancel_and_maps_confirmed_status():
    clock, runtime = _runtime()
    adapter = VSSFExecutionAdapter(CommandContext(), runtime)
    command = _command("order-adapter")
    submitted = adapter.execute(command)
    assert submitted.status == "NEW"
    assert (submitted.group_id, submitted.leg_id) == (command.group_id, command.leg_id)
    adapter = VSSFExecutionAdapter(CommandContext(), runtime)

    clock.sleep_policy(600)
    runtime.process_timeouts()
    cancelled = adapter.cancel(command.client_order_id)
    assert cancelled.status == "CANCELLED"
    assert (cancelled.group_id, cancelled.leg_id) == (command.group_id, command.leg_id)
    assert adapter.query(command.client_order_id).status == "CANCELLED"


def test_execution_adapter_cancel_reconciles_fill_winning_race():
    _clock, runtime = _runtime()
    adapter = VSSFExecutionAdapter(CommandContext(), runtime)
    command = _command("order-adapter-race")
    adapter.execute(command)
    runtime.order_book.update_bid_ask(9.9, 10.0, instrument_id=command.instrument_id)
    runtime.process_pending_orders()

    result = adapter.cancel(command.client_order_id)
    assert result.status == "FILLED"
    assert result.filled_quantity == 1
    assert result.execution_id
    assert result.fee == Decimal("0.0")

def test_virtual_execution_cancel_and_query_preserve_prior_group_leg_metadata():
    from contracts.types import DataQuality, ExecutionReport
    from environments.virtual.execution.virtual_execution import VirtualExecutionEngine

    engine = VirtualExecutionEngine(position=None, account=None)
    prior = ExecutionReport(
        client_order_id="virtual-lineage-order",
        broker_order_id="virtual-broker-order",
        execution_id="virtual-execution-1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10"),
        execution_timestamp=datetime(2026, 11, 3, 9, 0),
        fee=Decimal("0"),
        source_freshness=DataQuality(
            is_fresh=True,
            is_complete=False,
            source_available=True,
            reason="synthetic test",
        ),
        group_id="SYNTHETIC:GROUP-1",
        leg_id="SYNTHETIC:LEG-1",
    )
    engine._reports[prior.client_order_id] = prior

    cancelled = engine.cancel(prior.client_order_id)
    queried = engine.query(prior.client_order_id)

    assert (cancelled.group_id, cancelled.leg_id) == (
        "SYNTHETIC:GROUP-1",
        "SYNTHETIC:LEG-1",
    )
    assert queried is not None
    assert (queried.group_id, queried.leg_id) == (
        "SYNTHETIC:GROUP-1",
        "SYNTHETIC:LEG-1",
    )

def test_virtual_query_cancel_keep_prior_group_leg_when_report_omits_them():
    from contracts.types import DataQuality, ExecutionReport
    from environments.virtual.execution.virtual_execution import VirtualExecutionEngine

    prior = ExecutionReport(
        client_order_id="virtual-authoritative-lineage-order",
        broker_order_id="virtual-broker-order",
        execution_id="virtual-execution-1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10"),
        execution_timestamp=datetime(2026, 11, 3, 9, 0),
        fee=Decimal("0"),
        group_id="SYNTHETIC:GROUP-2",
        leg_id="SYNTHETIC:LEG-2",
    )

    def lifecycle_report(status):
        return ExecutionReport(
            client_order_id=prior.client_order_id,
            broker_order_id=prior.broker_order_id,
            execution_id=None,
            status=status,
            filled_quantity=prior.filled_quantity,
            remaining_quantity=prior.remaining_quantity,
            execution_price=None,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="synthetic lifecycle projection",
            ),
        )

    engine = VirtualExecutionEngine(
        position=None,
        account=None,
        authoritative_query=lambda _client_order_id: lifecycle_report("CANCELLED"),
        authoritative_cancel=lambda _client_order_id: lifecycle_report("CANCELLED"),
    )
    engine._reports[prior.client_order_id] = prior

    queried = engine.query(prior.client_order_id)
    engine._reports[prior.client_order_id] = prior
    cancelled = engine.cancel(prior.client_order_id)

    assert queried is not None
    assert (queried.group_id, queried.leg_id) == (
        "SYNTHETIC:GROUP-2",
        "SYNTHETIC:LEG-2",
    )
    assert (cancelled.group_id, cancelled.leg_id) == (
        "SYNTHETIC:GROUP-2",
        "SYNTHETIC:LEG-2",
    )
