from decimal import Decimal

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from tests.support import build_test_option_master


def _bundle_with_runtime():
    from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
    from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
    from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
    from contracts.types import EnvironmentType
    deps = VirtualCompositionDependencies(contract_registry=None, contract_mappings={}, initial_capital=250_000_000.0, vssf_command_context=CanonicalVSSFCommandContextProvider(), option_master=build_test_option_master())
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=deps).build(EnvironmentConfig(EnvironmentType.VIRTUAL, "test"), RuntimePolicy())
    bundle.connect(); bundle.start(); return bundle


def test_option_program_read_model_projects_nine_strategies_and_runtime_flow():
    from types import SimpleNamespace
    from application.option_program_read_model import OptionProgramReadModel
    from contracts.strategy_runtime_status import StrategyRuntimeStatus

    bundle = _bundle_with_runtime()
    tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    strategy_keys = tuple(
        (f"track{i}", "v1.0") for i in range(1, 10)
    )

    class StrategyHub:
        def __init__(self):
            self.strategy_keys = strategy_keys
        def is_enabled(self, _strategy_id, _version):
            return True

    runtime_hub = SimpleNamespace(
        last_result=SimpleNamespace(
            tick_sequence=tick.seq_id,
            signals=2,
            approved=1,
            routed=1,
            filled=1,
            rejected=0,
            execution_ids=("EXEC-1",),
        ),
        last_strategy_status=tuple(
            StrategyRuntimeStatus(strategy_id, reaction_signals=1)
            for strategy_id, _version in strategy_keys
        ),
    )
    controller = SimpleNamespace(
        status=lambda: SimpleNamespace(state="RUNNING")
    )
    context = SimpleNamespace(
        run_id="RUN-OPTION-PROGRAM",
        environment="virtual",
        scenario="CALM",
        historical_source="REAL_VTS",
        historical_store_path=None,
    )

    projection = OptionProgramReadModel(
        runtime_controller=controller,
        runtime_hub=runtime_hub,
        strategy_hub=StrategyHub(),
        bundle=bundle,
        context=context,
    ).build()

    assert projection["tab_id"] == "option_program"
    assert projection["runtime_state"] == "RUNNING"
    assert len(projection["strategies"]) == 9
    assert projection["market_input"]["seq_id"] == tick.seq_id
    assert projection["flow"]["signal"] == 2
    assert projection["flow"]["order_routed"] == 1
    assert "per_strategy_signal_detail" in projection["unavailable_sections"]
    bundle.stop()


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
        environment_hub = type("Hub", (), {"active": bundle})()
        def status(self): return type("Status", (), {"state": "RUNNING"})()

    adapter = ControlTowerUIAdapter(Controller())
    exchange = adapter.get_tab_detail("virtual_exchange"); broker = adapter.get_tab_detail("virtual_broker")
    assert len(exchange["recent_ticks"]) == 1
    assert exchange["market_depth"]["bids"][0]["price"] == tick.bid_price
    assert exchange["market_depth"]["asks"][0]["price"] == tick.ask_price
    assert broker["recent_executions"] == []
    assert broker["positions"][0]["avg_price"] == raw_report.executed_price
    assert broker["positions"][0]["current_price"] == tick.last_price
    assert broker["positions"][0]["contract_multiplier"] == 250000.0
    assert broker["positions"][0]["pnl"] is not None
    assert "250000.0" not in __import__("pathlib").Path("interfaces/control_tower/ui_adapter.py").read_text(encoding="utf-8")
    assert broker["unrealized_pnl"] is not None
    bundle.stop()
