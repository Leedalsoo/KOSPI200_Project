from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.strategy_hub.hub import StrategyHub
from contracts.analytics import AnalyticsStatus
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel
from contracts.types import EnvironmentType, OptionInstrumentIdentity
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.registry import StrategyRegistry
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


class _AllowedRisk:
    def snapshot(self):
        return RiskGuardStatusSnapshot(datetime.now(timezone.utc), True, False, SensorLevel.GREEN, "ISOLATED_VIRTUAL_TEST_READY", "fixture-v1")


def _tick(timestamp, seq_id, underlying):
    return ReferenceCanonicalMarketTick(timestamp=timestamp, underlying_price=underlying, underlying_symbol="KOSPI200",
        underlying_source="DERIVED_SCENARIO_TEST_FIXTURE", strike_price=350.0, option_type="PUT", contract_multiplier=250000.0,
        bid_price=9.8, ask_price=10.0, last_price=9.9, volume=100, seq_id=seq_id, expiry="20261015",
        symbol="TEST-PUT-350", option_source="DERIVED_SCENARIO_TEST_FIXTURE", instrument_id="TEST-PUT-350")


def test_strategy9_real_strategy_runs_overnight_entry_fill_and_next_open_close_in_virtual_runtime():
    strategy_id = Track9EventOvernightInsurance.strategy_id
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    for code, option_type, strike in (("TEST-PUT-350", "PUT", "350"), ("TEST-CALL-360", "CALL", "360")):
        master.register_contract_identity(KisOptionContractIdentity(shrn_iscd=code, stnd_iscd=code, expiry="20261015",
            option_type=option_type, strike=Decimal(strike), contract_multiplier=Decimal("250000")))
    dependencies = VirtualCompositionDependencies(contract_registry=None, contract_mappings={}, initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(), option_master=master)
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="strategy9-runtime-isolation-test"), RuntimePolicy(allow_live_orders=False))
    bundle.initialize(); bundle.connect(); bundle.start()
    strategy = Track9EventOvernightInsurance(pair_quantity=1)
    registry = StrategyRegistry(); registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, run_id="strategy9-derived-scenario-runtime-test", option_master=master,
        risk_guard_status_source=_AllowedRisk(), execution_result_callback=lambda plan, result: hub.on_execution_result(plan.strategy_id, plan.purpose or "", result))
    def context_builder(tick, state):
        as_of = datetime.fromisoformat(tick.timestamp)
        # Entry prices on the next-day tick are taken from actual prior Virtual fill reports, not guessed marks.
        reports = [report for group in bridge.groups.values() for report in group if report.status == "FILLED" and report.execution_price is not None]
        put_fills = [r for r in reports if r.leg_id == "put"]
        call_fills = [r for r in reports if r.leg_id == "call"]
        values = {
            "price.last": Decimal(str(tick.underlying_price)), "options.atm_put_strike": Decimal("350"),
            "options.atm_call_strike": Decimal("360"), "options.contract_multiplier": Decimal("250000"),
            "options.track9_put_mark_price": Decimal("10"), "options.track9_call_mark_price": Decimal("10"),
        }
        if put_fills and call_fills:
            values["options.track9_put_entry_price"] = Decimal(str(put_fills[-1].execution_price))
            values["options.track9_call_entry_price"] = Decimal(str(call_fills[-1].execution_price))
        metrics = {k: SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=v) for k, v in values.items()}
        analytics = SimpleNamespace(as_of=as_of, get=lambda key: metrics.get(key))
        common = CommonStrategyInput(as_of=as_of, current_price=Decimal(str(tick.underlying_price)), budget=Decimal("2000000"),
            time_str=as_of.strftime("%H:%M:%S"), date_str=as_of.date().isoformat())
        return {strategy_id: StrategyContext(market_state=state, strategy_id=strategy_id,
            input=StrategyInput(common=common), analytics=analytics)}
    def identity_provider(evaluation, _tick):
        proposal = evaluation.result.execution_proposal
        option_type = str(proposal.option_type); strike = Decimal(str(proposal.strike))
        code = "TEST-PUT-350" if option_type == "PUT" else "TEST-CALL-360"
        return OptionInstrumentIdentity(code, code, "20261015", option_type, strike, Decimal("250000"), "OPTION_MASTER")
    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if str(proposal.side).upper() == "SELL":
            strategy.build_execution_plan(f"strategy9-close-intent-{canonical.signal_id}", proposal=proposal)
            return bridge.build_close_plan_from_open_lots(strategy_id=strategy_id, purpose="OVERNIGHT_INSURANCE_CLOSE")
        return strategy.build_execution_plan(f"strategy9-derived-{canonical.signal_id}", proposal=proposal)
    loop = AutomatedVirtualTradingLoop(bundle=bundle, strategy_hub=hub, run_id="strategy9-derived-scenario-runtime-test",
        context_builder=context_builder, identity_provider=identity_provider, multi_leg_plan_resolver=plan_resolver,
        multi_leg_executor=bridge.execute, pending_multi_leg_processor=bridge.process_pending_quotes, risk_guard_status_source=_AllowedRisk())
    bundle.market.subscribe(loop.on_tick)
    for option_type, strike in (("PUT", 350.0), ("CALL", 360.0)):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261015"),
            {"bid":"9.8", "ask":"10.0", "last":"9.9", "timestamp":"2026-10-12T15:10:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-12T15:10:00", 1, 355.0))
    entry = loop.last_result
    assert entry is not None and (entry.signals, entry.approved, entry.routed, entry.filled, entry.rejected) == (1, 1, 2, 2, 0)
    assert len(bridge.position_lot_store.open_lots()) == 2 and strategy.state.state == "OVERNIGHT_INSURANCE_AWAITING_FILLS"
    for option_type, strike in (("PUT", 350.0), ("CALL", 360.0)):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261015"),
            {"bid":"9.8", "ask":"10.0", "last":"9.9", "timestamp":"2026-10-13T09:00:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-13T09:00:00", 2, 355.0))
    close = loop.last_result
    assert close is not None and (close.signals, close.approved, close.routed, close.filled, close.rejected) == (1, 1, 2, 2, 0)
    assert bridge.position_lot_store.open_lots() == ()
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf.account.positions == {} and strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"
    assert strategy.state.closed_next_open is True and strategy._exit_pending is False
    bundle.shutdown()
