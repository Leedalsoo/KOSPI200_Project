from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.run_hub.hub import RunScenarioHub, RunSession
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


def _session_factory(context):
    bootstrap = create_virtual_runtime_bootstrap(initial_capital=context.initial_capital or 250_000_000.0)
    return RunSession(
        context=context,
        runtime_controller=bootstrap.runtime_controller,
        bundle=bootstrap.bundle,
        strategy_hub=bootstrap.strategy_hub,
        runtime_hub=bootstrap.runtime_hub,
        ui_adapter=bootstrap.ui_adapter,
        control_tower_hub=bootstrap.control_tower_hub,
    )


def test_same_scenario_runs_are_state_isolated():
    hub = RunScenarioHub()
    first = hub.start(
        run_id="RUN-A", environment="virtual", scenario="baseline",
        strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
        initial_capital=250_000_000.0, session_factory=_session_factory,
    )
    key = first.strategy_hub.strategy_keys[0]
    first.strategy_hub.set_enabled(*key, enabled=False)
    tick = next(first.bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    command = BrokerOrderCommand(
        client_order_id="RUN-A-ORDER", instrument_id="KOSPI200", side="BUY", quantity=1,
        order_type="LIMIT", requested_price=Decimal(str(tick.ask_price)), track_id="RUN-A",
        tag_id="TEST", asset_type="OPTION",
        instrument_identity=OptionInstrumentIdentity("KOSPI200", "KOSPI200", tick.expiry, "CALL", Decimal(str(tick.strike_price))),
    )
    vssf = first.bundle.execution._authoritative_execute.__self__.vssf_runtime
    report = vssf.process_order(CanonicalVSSFCommandContextProvider().build_command(command))
    assert report is not None
    assert vssf.execution_engine.reports
    assert first.bundle.position.snapshot()
    hub.close()

    second = hub.start(
        run_id="RUN-B", environment="virtual", scenario="baseline",
        strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.1.0"),),
        initial_capital=250_000_000.0, session_factory=_session_factory,
    )
    assert second.context.run_id == "RUN-B"
    assert second.strategy_hub.is_enabled(*key)
    vssf2 = second.bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf2.execution_engine.reports == []
    assert second.bundle.position.snapshot() == {}
    assert second.bundle.account.snapshot().balances["available_cash"] == Decimal("250000000.0")
    assert second.bundle.market.replay.cursor == 0
    hub.close()
    assert hub.active is None
