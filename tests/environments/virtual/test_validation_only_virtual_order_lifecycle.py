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
    assert runtime.query_order(command.client_order_id).status == "NEW"

    clock.sleep_policy(599)
    runtime.process_market_data(_tick(clock))
    assert runtime.query_order(command.client_order_id).status == "NEW"

    clock.sleep_policy(1)
    runtime.process_market_data(_tick(clock))
    confirmed = runtime.query_order(command.client_order_id)
    assert confirmed.status == "CANCELLED"
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

    clock.sleep_policy(600)
    runtime.process_timeouts()
    cancelled = adapter.cancel(command.client_order_id)
    assert cancelled.status == "CANCELLED"
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
