"""Real OptionProject virtual authoritative adapter end-to-end integration."""
from decimal import Decimal

from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity, CanonicalFuturesQuote
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.futures_contract_spec import FuturesProductType
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


def test_authoritative_futures_quote_flows_to_vssf_and_fills_a05610():
    from datetime import datetime, timezone

    vms = VirtualMarketSimulatorRuntime(option_master=build_test_option_master())
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=1_000_000_000.0)
    vms.subscribe_futures_quote(vssf.process_futures_market_data)

    quote = CanonicalFuturesQuote(
        instrument_id="A05610",
        observed_at=datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc),
        bid_price=Decimal("1101.30"),
        ask_price=Decimal("1101.32"),
        last_price=Decimal("1101.31"),
        source="KIS:H0IFCNT0",
    )
    vms.publish_authoritative_futures_quote(quote)

    identity = FuturesInstrumentIdentity(
        instrument_id="A05610",
        symbol="A05610",
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("250000"),
        identity_source="KIS_FUTURES_MASTER",
    )
    order = BrokerOrderCommand(
        client_order_id="ORD-VMS-VSSF-FUT-1",
        instrument_id="A05610",
        side="BUY",
        quantity=1,
        order_type="MARKET",
        instrument_identity=identity,
        asset_type="FUTURES",
        requested_price=Decimal("1101.32"),
        track_id="TRACK-4",
        tag_id="GAMMA_HEDGE",
    )

    report = VSSFExecutionAdapter(
        command_context=CanonicalVSSFCommandContextProvider(),
        vssf_runtime=vssf,
    ).execute(order)

    assert report.status == "FILLED"
    assert report.execution_id is not None
    assert report.filled_quantity == 1
    assert report.execution_price == 1101.32
    assert vssf.account.positions["A05610"]["side"] == CanonicalOrderSide.BUY.value


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
