from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
from environments.virtual.clock import VirtualClock


def test_timeout_uses_runtime_clock_and_explicit_policy():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    source.observe_submission("O1", "track7_volatility_skew_weekly_insurance", clock.now())
    clock.sleep_policy(4)
    assert source.is_timed_out("O1", clock.now(), "NEW") is False
    clock.sleep_policy(1)
    assert source.is_timed_out("O1", clock.now(), "NEW") is True


def test_terminal_order_never_times_out():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    source.observe_submission("O2", "track7_volatility_skew_weekly_insurance", clock.now())
    clock.sleep_policy(10)
    assert source.is_timed_out("O2", clock.now(), "FILLED") is False


def test_missing_lifecycle_submission_fails_closed():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    with pytest.raises(KeyError, match="TRACK7_ORDER_LIFECYCLE_SUBMISSION_UNAVAILABLE"):
        source.is_timed_out("MISSING", clock.now(), "NEW")


from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter


def _pending_command(order_id="TIMEOUT-1"):
    return BrokerOrderCommand(
        client_order_id=order_id, instrument_id="TIMEOUT-OPT", side="BUY", quantity=1,
        order_type="LIMIT", instrument_identity=OptionInstrumentIdentity(
            instrument_id="TIMEOUT-OPT", symbol="TIMEOUT-OPT", expiry="20261210",
            option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"),
            identity_source="TEST_AUTHORITATIVE_OPTION_MASTER",
        ), asset_type="OPTION", requested_price=Decimal("1.0"),
        strategy_id="TRACK7", track_id="TRACK7", tag_id="TIMEOUT-TEST",
    )

def test_virtual_broker_pending_order_times_out_and_is_cancelled():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    policy = Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-TEST-5S")
    source = Track7OrderTimeoutRuntimeSource(clock, policy)
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=250_000_000.0, clock=clock)
    vssf.attach_timeout_source(source)
    adapter = VSSFExecutionAdapter(CanonicalVSSFCommandContextProvider(), vssf)
    engine = VirtualExecutionEngine(position=object(), account=object(),
        authoritative_execute=adapter.execute, authoritative_query=adapter.query,
        authoritative_cancel=adapter.cancel)
    broker = VirtualBroker(engine, market_data_handler=vssf.process_market_data)

    submitted = broker.submit(_pending_command())
    assert submitted.status == "NEW"
    clock.sleep_policy(5)
    assert source.is_strategy_timed_out("TRACK7", clock.now()) is True
    timeout_events = vssf.process_timeouts()
    assert len(timeout_events) == 1
    assert timeout_events[0].status == "CANCELLED"
    assert broker.query("TIMEOUT-1").status == "CANCELLED"
    assert vssf.order_book.pending_orders() == ()
    assert vssf.metrics["executions_issued"] == 0
    assert source.is_strategy_timed_out("TRACK7", clock.now()) is False
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider


def test_standard_runtime_input_projects_authoritative_timeout_then_clears_after_event():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    policy = Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-TEST-5S")
    source = Track7OrderTimeoutRuntimeSource(clock, policy)
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=250_000_000.0, clock=clock)
    vssf.attach_timeout_source(source)
    adapter = VSSFExecutionAdapter(CanonicalVSSFCommandContextProvider(), vssf)
    engine = VirtualExecutionEngine(position=object(), account=object(), authoritative_execute=adapter.execute, authoritative_query=adapter.query, authoritative_cancel=adapter.cancel)
    broker = VirtualBroker(engine, market_data_handler=vssf.process_market_data)
    broker.submit(_pending_command("TIMEOUT-RUNTIME-1"))
    clock.sleep_policy(5)

    tick = SimpleNamespace(timestamp=clock.now().isoformat(), last_price=350.0, strike_price=350.0, option_type="CALL", expiry="202612", seq_id=1, symbol="TIMEOUT-OPT")
    market = SimpleNamespace(recent_ticks=(tick,), scenario=SimpleNamespace(active_config=lambda: {}))
    provider = StandardRuntimeInputProvider(market, track7_order_timeout_source=source)
    data = provider.data.snapshot(tick)
    assert data.order_timeout is True

    events = vssf.process_timeouts()
    assert len(events) == 1
    assert events[0].status == "CANCELLED"
    data_after = provider.data.snapshot(tick)
    assert data_after.order_timeout is False
