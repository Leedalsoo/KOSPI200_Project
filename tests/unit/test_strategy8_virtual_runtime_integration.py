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
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


class _AllowedRisk:
    def snapshot(self):
        return RiskGuardStatusSnapshot(datetime.now(timezone.utc), True, False, SensorLevel.GREEN, "ISOLATED_VIRTUAL_TEST_READY", "fixture-v1")


def _analytics(timestamp, price):
    as_of = datetime.fromisoformat(timestamp)
    values = {
        "price.last": Decimal(str(price)), "options.dte": Decimal("20"),
        "options.call_iv": Decimal("12"), "options.put_iv": Decimal("13"), "options.atm_iv": Decimal("12.5"),
        "options.call_strike": Decimal("365"), "options.put_strike": Decimal("335"),
        "options.call_contract_multiplier": Decimal("250000"), "options.put_contract_multiplier": Decimal("250000"),
        "options.moneyness": {"call_distance": Decimal(str(price)) - Decimal("365"), "put_distance": Decimal("335") - Decimal(str(price))},
        "market.current_regime": "NORMAL", "volatility.active": Decimal("1"),
        "portfolio.current_pnl": Decimal("0"), "portfolio.total_fees": Decimal("0"),
        "portfolio.net_pnl": Decimal("0"), "portfolio.margin_ratio": Decimal("0.2"), "risk.guard_active": False,
    }
    metrics = {k: SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=v) for k, v in values.items()}
    return SimpleNamespace(as_of=as_of, get=lambda key: metrics.get(key))


def _tick(timestamp, seq_id, underlying):
    return ReferenceCanonicalMarketTick(timestamp=timestamp, underlying_price=underlying, underlying_symbol="KOSPI200",
        underlying_source="DERIVED_SCENARIO_TEST_FIXTURE", strike_price=335.0, option_type="PUT", contract_multiplier=250000.0,
        bid_price=9.8, ask_price=10.0, last_price=9.9, volume=100, seq_id=seq_id, expiry="20261105",
        symbol="TEST-PUT-335", option_source="DERIVED_SCENARIO_TEST_FIXTURE", instrument_id="TEST-PUT-335")


def test_strategy8_real_strategy_runs_entry_fill_trailing_close_and_flat_in_virtual_runtime():
    strategy_id = Track8MacroRegimeMonthlyStrangle.strategy_id
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    for code, option_type, strike in (("TEST-PUT-335", "PUT", "335"), ("TEST-CALL-365", "CALL", "365")):
        master.register_contract_identity(KisOptionContractIdentity(shrn_iscd=code, stnd_iscd=code, expiry="20261105",
            option_type=option_type, strike=Decimal(strike), contract_multiplier=Decimal("250000")))
    dependencies = VirtualCompositionDependencies(contract_registry=None, contract_mappings={}, initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(), option_master=master)
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="strategy8-runtime-isolation-test"), RuntimePolicy(allow_live_orders=False))
    bundle.initialize(); bundle.connect(); bundle.start()
    strategy = Track8MacroRegimeMonthlyStrangle()
    registry = StrategyRegistry(); registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, run_id="strategy8-derived-scenario-runtime-test", option_master=master,
        risk_guard_status_source=_AllowedRisk(), execution_result_callback=lambda plan, result: hub.on_execution_result(plan.strategy_id, plan.purpose or "", result))
    def context_builder(tick, state):
        price = Decimal(str(tick.underlying_price))
        common = CommonStrategyInput(as_of=datetime.fromisoformat(tick.timestamp), current_price=price, active_vol=Decimal("1"),
            budget=Decimal("2000000"), current_pnl=Decimal("0"), total_fees=Decimal("0"),
            time_str=datetime.fromisoformat(tick.timestamp).strftime("%H:%M:%S"), date_str=datetime.fromisoformat(tick.timestamp).date().isoformat())
        return {strategy_id: StrategyContext(market_state=state, strategy_id=strategy_id, input=StrategyInput(common=common), analytics=_analytics(tick.timestamp, price))}
    def identity_provider(evaluation, _tick):
        proposal = evaluation.result.execution_proposal
        option_type = str(proposal.option_type)
        strike = Decimal(str(proposal.strike))
        code = "TEST-PUT-335" if option_type == "PUT" else "TEST-CALL-365"
        return OptionInstrumentIdentity(code, code, "20261105", option_type, strike, Decimal("250000"), "OPTION_MASTER")
    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if str(proposal.side).upper() == "SELL":
            return bridge.build_close_plan_from_open_lots(strategy_id=strategy_id, purpose=str(proposal.tag_id or "MONTHLY_STRANGLE_CLOSE"))
        return strategy.build_execution_plan(f"strategy8-derived-{canonical.signal_id}")
    loop = AutomatedVirtualTradingLoop(bundle=bundle, strategy_hub=hub, run_id="strategy8-derived-scenario-runtime-test",
        context_builder=context_builder, identity_provider=identity_provider, multi_leg_plan_resolver=plan_resolver,
        multi_leg_executor=bridge.execute, pending_multi_leg_processor=bridge.process_pending_quotes, risk_guard_status_source=_AllowedRisk())
    bundle.market.subscribe(loop.on_tick)
    for option_type, strike in (("PUT", 335.0), ("CALL", 365.0)):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261105"),
            {"bid":"9.8", "ask":"10.0", "last":"9.9", "timestamp":"2026-10-12T09:30:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:30:00", 1, 370.0))
    entry = loop.last_result
    assert entry is not None and (entry.signals, entry.approved, entry.routed, entry.filled, entry.rejected) == (1, 1, 2, 2, 0)
    assert len(bridge.position_lot_store.open_lots()) == 2 and strategy.state.is_active
    for option_type, strike in (("PUT", 335.0), ("CALL", 365.0)):
        bundle.market.publish_authoritative_option_quote((option_type, strike, "20261105"),
            {"bid":"8.8", "ask":"9.0", "last":"8.9", "timestamp":"2026-10-12T09:31:00", "contract_multiplier":"250000"})
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:31:00", 2, 365.0))
    close = loop.last_result
    assert close is not None and (close.signals, close.approved, close.routed, close.filled, close.rejected) == (1, 1, 2, 2, 0)
    assert bridge.position_lot_store.open_lots() == ()
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf.account.positions == {} and strategy.state.is_active is False and strategy._exit_pending is False
    bundle.shutdown()
