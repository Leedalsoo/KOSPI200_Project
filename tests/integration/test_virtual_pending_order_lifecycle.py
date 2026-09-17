from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.clock import VirtualClock


def _command(order_id="PENDING-1"):
    return BrokerOrderCommand(
        client_order_id=order_id, instrument_id="OPT-1", side="BUY", quantity=1,
        order_type="LIMIT", instrument_identity=OptionInstrumentIdentity(
            instrument_id="OPT-1", symbol="OPT-1", expiry="2026-12-10",
            option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"),
            identity_source="TEST_AUTHORITATIVE_OPTION_MASTER",
        ), asset_type="OPTION", requested_price=Decimal("1.0"),
        strategy_id="TRACK7", track_id="TRACK7", tag_id="PENDING-TEST",
    )


def _tick():
    return SimpleNamespace(timestamp="2026-09-17T09:00:02", bid_price=1.0, ask_price=1.0, underlying_price=350.0, instrument_id="OPT-1")


def test_pending_order_is_observed_then_filled_from_runtime_clock():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=250_000_000.0, clock=clock)
    adapter = VSSFExecutionAdapter(CanonicalVSSFCommandContextProvider(), vssf)
    engine = VirtualExecutionEngine(
        position=object(), account=object(), authoritative_execute=adapter.execute,
        authoritative_query=adapter.query, authoritative_cancel=adapter.cancel,
    )
    broker = VirtualBroker(engine, market_data_handler=vssf.process_market_data)

    submitted = broker.submit(_command())
    assert submitted.status == "NEW"
    assert submitted.remaining_quantity == 1
    assert submitted.execution_id is None
    assert submitted.execution_timestamp == datetime(2026, 9, 17, 9, 0, 0)

    clock.sleep_policy(2.0)
    observed = broker.query("PENDING-1")
    assert observed is not None
    assert observed.status == "NEW"
    assert observed.execution_timestamp == datetime(2026, 9, 17, 9, 0, 2)

    broker.process_market_data(_tick())
    filled = broker.query("PENDING-1")
    assert filled is not None
    assert filled.status == "FILLED"
    assert filled.remaining_quantity == 0
    assert filled.filled_quantity == 1
    assert filled.execution_price == 1.0
    assert filled.execution_timestamp == datetime(2026, 9, 17, 9, 0, 2)


def test_pending_order_can_be_cancelled_before_quote_arrives():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=250_000_000.0, clock=clock)
    adapter = VSSFExecutionAdapter(CanonicalVSSFCommandContextProvider(), vssf)
    engine = VirtualExecutionEngine(
        position=object(), account=object(), authoritative_execute=adapter.execute,
        authoritative_query=adapter.query, authoritative_cancel=adapter.cancel,
    )
    broker = VirtualBroker(engine, market_data_handler=vssf.process_market_data)

    broker.submit(_command("PENDING-2"))
    clock.sleep_policy(3.0)
    cancelled = broker.cancel("PENDING-2")
    assert cancelled.status == "CANCELLED"
    assert cancelled.remaining_quantity == 1
    assert cancelled.execution_timestamp == datetime(2026, 9, 17, 9, 0, 3)
    assert broker.query("PENDING-2").status == "CANCELLED"
