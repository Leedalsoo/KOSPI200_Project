from decimal import Decimal

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.position.vssf_position_aggregate_adapter import VSSFPositionAggregateAdapter


def test_vms_broker_vssf_execution_position_pnl_loop():
    vms = VirtualMarketSimulatorRuntime()
    tick = next(vms.generate_tick_stream(total_days=1, ticks_per_day=1))
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=1_000_000_000.0)
    execution = VirtualExecutionEngine(
        position=VSSFPositionAggregateAdapter(vssf.account),
        account=VSSFAccountSnapshotAdapter(vssf.account),
        authoritative_execute=VSSFExecutionAdapter(
            command_context=CanonicalVSSFCommandContextProvider(), vssf_runtime=vssf
        ).execute,
    )
    broker = VirtualBroker(execution, market_data_handler=vssf.process_market_data)
    broker.process_market_data(tick)
    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1", symbol="KOSPI200", expiry="202609",
        option_type="CALL", strike=Decimal(str(tick.strike_price)),
    )
    order = BrokerOrderCommand(
        client_order_id="ORD-CLOSED-LOOP-1", instrument_id=identity.instrument_id,
        side="BUY", quantity=2, order_type="LIMIT", instrument_identity=identity,
        asset_type="OPTION", requested_price=Decimal(str(tick.ask_price)),
        track_id="TRACK1", tag_id="CLOSED-LOOP",
    )
    report = broker.submit(order)
    assert report.client_order_id == order.client_order_id
    assert report.filled_quantity == 2
    account = VSSFAccountSnapshotAdapter(vssf.account).snapshot()
    positions = VSSFPositionAggregateAdapter(vssf.account).snapshot()
    assert positions[identity.symbol].qty == 2
    assert account.balances["unrealized_pnl"] == Decimal("0")
    assert vssf.metrics["market_ticks"] == 1
    assert vssf.metrics["executions_issued"] == 1
