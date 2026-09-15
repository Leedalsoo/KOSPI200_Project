from decimal import Decimal

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


def _bundle_with_runtime():
    from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
    from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
    from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
    from contracts.types import EnvironmentType
    deps = VirtualCompositionDependencies(contract_registry=None, contract_mappings={}, initial_capital=250_000_000.0, vssf_command_context=CanonicalVSSFCommandContextProvider())
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=deps).build(EnvironmentConfig(EnvironmentType.VIRTUAL, "test"), RuntimePolicy())
    bundle.connect(); bundle.start(); return bundle


def test_control_tower_projects_real_virtual_ticks_and_execution():
    bundle = _bundle_with_runtime(); market = bundle.market
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=3))
    identity = OptionInstrumentIdentity("KOSPI200", "KOSPI200", "202609", "CALL", Decimal(str(tick.strike_price)))
    command = BrokerOrderCommand(client_order_id="UI-PROJECTION-1", instrument_id="KOSPI200", side="BUY", quantity=1, order_type="LIMIT", requested_price=Decimal(str(tick.ask_price)), track_id="UI-TRACK", tag_id="UI-TAG", asset_type="OPTION", instrument_identity=identity)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    vssf_command = CanonicalVSSFCommandContextProvider().build_command(command)
    raw_report = vssf.process_order(vssf_command)
    assert raw_report is not None and raw_report.executed_qty == 1
    bundle.execution.account._account_source.apply_execution(raw_report)
    bundle.execution.account._account_source.update_tick_price(tick.underlying_price)

    class Controller:
        _hub = type("Hub", (), {"active": bundle})()
        def status(self): return type("Status", (), {"state": "RUNNING"})()

    adapter = ControlTowerUIAdapter(Controller())
    exchange = adapter.get_tab_detail("virtual_exchange"); broker = adapter.get_tab_detail("virtual_broker")
    assert len(exchange["recent_ticks"]) == 1
    assert exchange["market_depth"]["bids"][0]["price"] == tick.bid_price
    assert exchange["market_depth"]["asks"][0]["price"] == tick.ask_price
    assert broker["recent_executions"] == []
    assert broker["positions"][0]["avg_price"] == raw_report.executed_price
    assert broker["positions"][0]["current_price"] == tick.underlying_price
    assert broker["unrealized_pnl"] is not None
    bundle.stop()
