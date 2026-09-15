from decimal import Decimal

from application.composition.runtime_composition_factory import create_virtual_runtime_controller
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


def test_production_virtual_composition_routes_vms_tick_to_broker_vssf():
    controller = create_virtual_runtime_controller(
        contract_registry=object(),
        scenario_configuration={"contract_mappings": []},
        initial_capital=1_000_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    controller.start(
        EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="closed-loop"),
        RuntimePolicy(),
    )
    bundle = controller._hub.active
    assert bundle is not None

    tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf.metrics["market_ticks"] == 1
    assert vssf.orderbook.bid == tick.bid_price
    assert vssf.orderbook.ask == tick.ask_price

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
    report = bundle.broker.submit(order)
    assert report.client_order_id == order.client_order_id
    assert report.filled_quantity == 2
    assert vssf.metrics["executions_issued"] == 1
    assert vssf.account.positions[identity.symbol]["qty"] == 2
    controller.stop()

# Consolidated from tests\integration\test_runtime_controller_virtual_authoritative_lifecycle.py; retained because it covers the same production boundary.

from decimal import Decimal

from application.composition.runtime_composition_factory import create_virtual_runtime_controller
from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


def test_controller_lifecycle_uses_one_authoritative_vms_vssf_scope():
    controller = create_virtual_runtime_controller(contract_registry=object(), scenario_configuration={"contract_mappings": []}, initial_capital=1_000_000_000.0, vssf_command_context=CanonicalVSSFCommandContextProvider())
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="authoritative-lifecycle")
    controller.start(config, RuntimePolicy())
    bundle = controller._hub.active
    assert bundle is not None
    assert controller.status().state == "RUNNING"

    reference_tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    adapter = bundle.execution._authoritative_execute.__self__
    vssf = adapter.vssf_runtime
    standard_tick = VMSMarketTickProjectionAdapter("AUTH-LIFECYCLE-1").project(reference_tick)
    assert standard_tick.price == Decimal(str(reference_tick.last_price))

    identity = OptionInstrumentIdentity(instrument_id="AUTH-LIFECYCLE-1", symbol="KOSPI200", expiry="202609", option_type="CALL", strike=Decimal(str(reference_tick.strike_price)))
    order = BrokerOrderCommand(client_order_id="ORD-LIFECYCLE-1", instrument_id=identity.instrument_id, side="BUY", quantity=2, order_type="LIMIT", instrument_identity=identity, asset_type="OPTION", requested_price=standard_tick.price, track_id="TRACK-LIFECYCLE", tag_id="TAG-LIFECYCLE")
    report = bundle.broker.submit(order)
    assert report.client_order_id == order.client_order_id
    assert vssf.metrics["market_ticks"] == 1
    assert vssf.metrics["executions_issued"] == 1
    assert vssf.account.positions[identity.symbol]["side"] == "BUY"
    assert vssf.account.positions[identity.symbol]["qty"] == 2
    controller.stop()
    assert controller.status().state == "STOPPED"
