"""Real OptionProject virtual authoritative adapter end-to-end integration."""
from decimal import Decimal

from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.position.vssf_position_aggregate_adapter import VSSFPositionAggregateAdapter
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from shared.contracts.canonical import CanonicalOrderSide
from tests.support import build_test_option_master


def test_real_vms_vssf_adapter_end_to_end():
    vms = VirtualMarketSimulatorRuntime(option_master=build_test_option_master())
    reference_tick = next(vms.generate_tick_stream(total_days=1, ticks_per_day=1))

    vssf = VirtualSecuritiesFirmRuntime(initial_capital=1_000_000_000.0)
    vssf.process_market_data(reference_tick)
    market = VMSMarketTickProjectionAdapter("AUTH-OPTION-1").project(reference_tick)
    assert market.instrument_id == "AUTH-OPTION-1"
    assert market.price == Decimal(str(reference_tick.last_price))
    assert market.source_sequence == reference_tick.seq_id

    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal(str(reference_tick.strike_price)),
    )
    order = BrokerOrderCommand(
        client_order_id="ORD-VMS-VSSF-1",
        instrument_id="AUTH-OPTION-1",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=market.price,
        track_id="TRACK-1",
        tag_id="TAG-1",
    )

    report = VSSFExecutionAdapter(
        command_context=CanonicalVSSFCommandContextProvider(),
        vssf_runtime=vssf,
    ).execute(order)

    assert report.client_order_id == "ORD-VMS-VSSF-1"
    assert vssf.account.positions[identity.symbol]["side"] == CanonicalOrderSide.BUY.value

    account = VSSFAccountSnapshotAdapter(vssf.account).snapshot()
    positions = VSSFPositionAggregateAdapter(vssf.account).snapshot()
    assert account is not None
    assert positions[identity.symbol].side == "BUY"
    assert positions[identity.symbol].qty == 2


def test_authoritative_option_identity_is_preserved_into_execution_report():
    from datetime import datetime, timezone
    from environments.virtual.authoritative_vssf.execution_engine import ExecutionEngine
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide, CanonicalOptionType, CanonicalOrderCommand

    command = CanonicalOrderCommand(
        client_order_id="ORD-IDENTITY-1", track_id="TRACK-IDENTITY-1",
        asset_type=CanonicalAssetType.OPTION, side=CanonicalOrderSide.BUY,
        qty=1, price=1.25, option_type=CanonicalOptionType.CALL, strike=350.0,
        symbol="201T3500", expiry="202610", instrument_id="201T3500",
        contract_multiplier=250000.0, identity_source="OPTION_MASTER",
    )

    report = ExecutionEngine().execute_order(
        command, 1.25, 1, timestamp=datetime(2026, 9, 18, tzinfo=timezone.utc)
    )

    assert report.instrument_id == command.instrument_id
    assert report.contract_multiplier == command.contract_multiplier
    assert report.identity_source == command.identity_source
