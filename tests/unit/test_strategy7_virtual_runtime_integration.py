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
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.registry import StrategyRegistry
from core.strategy.track7_volatility_skew_weekly_insurance import Track7ExecutionInput, Track7VolatilitySkewWeeklyInsurance
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


class _AllowedRisk:
    def snapshot(self):
        return RiskGuardStatusSnapshot(datetime.now(timezone.utc), True, False, SensorLevel.GREEN, "ISOLATED_VIRTUAL_TEST_READY", "fixture-v1")


def _analytics(timestamp, *, new_week=False, put_mark=Decimal("10"), call_mark=Decimal("10")):
    as_of = datetime.fromisoformat(timestamp)
    values = {
        "price.last": Decimal("355"),
        "calendar.is_new_week_start": new_week,
        "calendar.is_expiry_day": as_of.date().isoformat() == "2026-10-15",
        "options.track7_put_mark_price": put_mark,
        "options.track7_call_mark_price": call_mark,
    }
    metrics = {k: SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=v) for k, v in values.items()}
    return SimpleNamespace(as_of=as_of, get=lambda key: metrics.get(key))


def _tick(timestamp, seq_id, underlying=355.0):
    return ReferenceCanonicalMarketTick(
        timestamp=timestamp, underlying_price=underlying, underlying_symbol="KOSPI200",
        underlying_source="DERIVED_SCENARIO_TEST_FIXTURE", strike_price=350.0, option_type="PUT",
        contract_multiplier=250000.0, bid_price=9.8, ask_price=10.0, last_price=9.9,
        volume=100, seq_id=seq_id, expiry="20261015", symbol="TEST-PUT-350",
        option_source="DERIVED_SCENARIO_TEST_FIXTURE", instrument_id="TEST-PUT-350",
    )


def test_strategy7_real_strategy_runs_entry_fill_and_exact_expiry_close_in_virtual_runtime():
    strategy_id = Track7VolatilitySkewWeeklyInsurance.strategy_id
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    for code, option_type, strike in (("TEST-PUT-350", "PUT", "350"), ("TEST-CALL-360", "CALL", "360")):
        master.register_contract_identity(KisOptionContractIdentity(
            shrn_iscd=code, stnd_iscd=code, expiry="20261015", option_type=option_type,
            strike=Decimal(strike), contract_multiplier=Decimal("250000")))
    dependencies = VirtualCompositionDependencies(contract_registry=None, contract_mappings={}, initial_capital=250_000_000.0, option_master=master,
        vssf_command_context=CanonicalVSSFCommandContextProvider())
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="strategy7-runtime-isolation-test"),
        RuntimePolicy(allow_live_orders=False))
    bundle.initialize(); bundle.connect(); bundle.start()
    strategy = Track7VolatilitySkewWeeklyInsurance()
    registry = StrategyRegistry(); registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, run_id="strategy7-derived-scenario-runtime-test",
        option_master=master, risk_guard_status_source=_AllowedRisk(),
        execution_result_callback=lambda plan, result: hub.on_execution_result(plan.strategy_id, plan.purpose or "", result))
    payload = Track7ExecutionInput(strategy_id=strategy_id, expiry="2026-10-15", reference_price=Decimal("355"),
        put_strike=Decimal("350"), call_strike=Decimal("360"), contract_multiplier=Decimal("250000"))
    marks = {"put": Decimal("10"), "call": Decimal("10")}
    def context_builder(tick, state):
        analytics = _analytics(tick.timestamp, new_week=tick.seq_id == 1, put_mark=marks["put"], call_mark=marks["call"])
        return {strategy_id: StrategyContext(market_state=state, strategy_id=strategy_id,
            input=StrategyInput(payload=payload), analytics=analytics)}
    def identity_provider(_evaluation, _tick):
        return OptionInstrumentIdentity("TEST-PUT-350", "TEST-PUT-350", "20261015", "PUT", Decimal("350"), Decimal("250000"), "OPTION_MASTER")
    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if str(proposal.side).upper() == "SELL":
            strategy.build_execution_plan(f"strategy7-close-intent-{canonical.signal_id}", proposal=proposal)
            return bridge.build_close_plan_from_open_lots(strategy_id=strategy_id, purpose=str(proposal.tag_id or "WEEKLY_INSURANCE_CLOSE"))
        return strategy.build_execution_plan(f"strategy7-derived-{canonical.signal_id}", proposal=proposal)
    loop = AutomatedVirtualTradingLoop(bundle=bundle, strategy_hub=hub, run_id="strategy7-derived-scenario-runtime-test",
        context_builder=context_builder, identity_provider=identity_provider, multi_leg_plan_resolver=plan_resolver,
        multi_leg_executor=bridge.execute, pending_multi_leg_processor=bridge.process_pending_quotes,
        risk_guard_status_source=_AllowedRisk())
    bundle.market.subscribe(loop.on_tick)
    for option_type, strike, code in (("PUT", 350.0, "TEST-PUT-350"), ("CALL", 360.0, "TEST-CALL-360")):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261015"),
            {"bid":"9.8", "ask":"10.0", "last":"9.9", "timestamp":"2026-10-12T09:30:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:30:00", 1))
    entry = loop.last_result
    assert entry is not None and (entry.signals, entry.approved, entry.routed, entry.filled, entry.rejected) == (1, 1, 2, 2, 0)
    assert len(bridge.position_lot_store.open_lots()) == 2 and strategy.state.insurance_active
    for option_type, strike in (("PUT", 350.0), ("CALL", 360.0)):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261015"),
            {"bid":"9.8", "ask":"10.0", "last":"9.9", "timestamp":"2026-10-15T15:00:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-15T15:00:00", 2))
    close = loop.last_result
    assert close is not None and (close.signals, close.approved, close.routed, close.filled, close.rejected) == (1, 1, 2, 2, 0)
    assert bridge.position_lot_store.open_lots() == ()
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf.account.positions == {} and strategy.state.insurance_active is False and strategy._exit_pending is False
    bundle.shutdown()
