from __future__ import annotations

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
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6ExecutionInput
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


class _AllowedVirtualRiskGuard:
    def snapshot(self) -> RiskGuardStatusSnapshot:
        return RiskGuardStatusSnapshot(
            observed_at=datetime.now(timezone.utc),
            admission_allowed=True,
            kill_switch_engaged=False,
            health_level=SensorLevel.GREEN,
            reason="ISOLATED_VIRTUAL_TEST_READY",
            decision_version="fixture-v1",
        )


def _analytics(timestamp: str, underlying_price: Decimal):
    as_of = datetime.fromisoformat(timestamp)
    values = {
        "price.last": underlying_price,
        "volatility.active": Decimal("2.0"),
        "volatility.base": Decimal("1.0"),
        "volatility.ratio": Decimal("2.0"),
        "portfolio.premium_spent": Decimal("10.0"),
    }
    metrics = {
        key: SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)
        for key, value in values.items()
    }
    return SimpleNamespace(as_of=as_of, get=lambda key: metrics.get(key))


def _tick(timestamp: str, seq_id: int, underlying: float, put_bid: float, put_ask: float):
    return ReferenceCanonicalMarketTick(
        timestamp=timestamp,
        underlying_price=underlying,
        underlying_symbol="KOSPI200",
        underlying_source="DERIVED_SCENARIO_TEST_FIXTURE",
        strike_price=90.0,
        option_type="PUT",
        contract_multiplier=250000.0,
        bid_price=put_bid,
        ask_price=put_ask,
        last_price=(put_bid + put_ask) / 2,
        volume=100,
        seq_id=seq_id,
        expiry="20261015",
        symbol="TEST-PUT-90",
        option_source="DERIVED_SCENARIO_TEST_FIXTURE",
        instrument_id="TEST-PUT-90",
    )


def test_strategy6_real_strategy_runs_entry_trailing_update_and_terminal_close_in_virtual_runtime():
    strategy_id = "track6_daily_tail_insurance"
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="TEST-PUT-90", stnd_iscd="TEST-PUT-90", expiry="20261015",
        option_type="PUT", strike=Decimal("90"), contract_multiplier=Decimal("250000"),
    ))
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="TEST-CALL-110", stnd_iscd="TEST-CALL-110", expiry="20261015",
        option_type="CALL", strike=Decimal("110"), contract_multiplier=Decimal("250000"),
    ))
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=master,
        contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="strategy6-runtime-isolation-test"),
        RuntimePolicy(allow_live_orders=False),
    )
    bundle.initialize()
    bundle.connect()
    bundle.start()

    strategy = Track6DailyTailInsurance()
    registry = StrategyRegistry()
    registry.register(strategy)
    strategy_hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle,
        run_id="strategy6-derived-scenario-runtime-test",
        option_master=master,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
        execution_result_callback=lambda plan, result: strategy_hub.on_execution_result(
            plan.strategy_id, plan.purpose or "", result
        ),
    )
    payload = Track6ExecutionInput(
        strategy_id=strategy_id,
        date_str="2026-10-12",
        listed_put_strike=Decimal("90"),
        listed_call_strike=Decimal("110"),
        contract_multiplier=Decimal("250000"),
    )

    def context_builder(tick, state):
        analytics = _analytics(tick.timestamp, Decimal(str(tick.underlying_price)))
        return {strategy_id: StrategyContext(
            market_state=state,
            strategy_id=strategy_id,
            input=StrategyInput(payload=payload),
            analytics=analytics,
        )}

    def identity_provider(_evaluation, _tick):
        return OptionInstrumentIdentity(
            instrument_id="TEST-PUT-90", symbol="TEST-PUT-90", expiry="20261015",
            option_type="PUT", strike=Decimal("90"),
            contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
        )

    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if str(proposal.side).upper() == "SELL":
            return bridge.build_close_plan_from_open_lots(
                strategy_id=strategy_id, purpose=str(proposal.tag_id or "DAILY_TAIL_INSURANCE_CLOSE"),
            )
        return strategy.build_execution_plan(f"strategy6-derived-{canonical.signal_id}")

    loop = AutomatedVirtualTradingLoop(
        bundle=bundle,
        strategy_hub=strategy_hub,
        run_id="strategy6-derived-scenario-runtime-test",
        context_builder=context_builder,
        identity_provider=identity_provider,
        multi_leg_plan_resolver=plan_resolver,
        multi_leg_executor=bridge.execute,
        pending_multi_leg_processor=bridge.process_pending_quotes,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
    )
    bundle.market.subscribe(loop.on_tick)

    bundle.market.publish_authoritative_option_quote(
        ("PUT", 90.0, "20261015"),
        {"bid": "9.8", "ask": "10.0", "last": "9.9", "timestamp": "2026-10-12T09:30:00", "contract_multiplier": "250000"},
    )
    bundle.market.publish_authoritative_option_quote(
        ("CALL", 110.0, "20261015"),
        {"bid": "9.8", "ask": "10.0", "last": "9.9", "timestamp": "2026-10-12T09:30:00", "contract_multiplier": "250000"},
    )
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:30:00", 1, 100.0, 9.8, 10.0))
    entry = loop.last_result
    assert entry is not None
    assert (entry.signals, entry.approved, entry.routed, entry.filled, entry.rejected) == (1, 1, 2, 2, 0)
    assert len(bridge.position_lot_store.open_lots()) == 2
    assert strategy.state.is_active is True

    bundle.market.publish_authoritative_option_quote(
        ("PUT", 90.0, "20261015"),
        {"bid": "11.8", "ask": "12.0", "last": "11.9", "timestamp": "2026-10-12T09:31:00", "contract_multiplier": "250000"},
    )
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:31:00", 2, 88.0, 11.8, 12.0))
    trailing_update = loop.last_result
    assert trailing_update is not None
    assert trailing_update.signals == 1
    assert trailing_update.strategy_status[0].non_execution_signals == 1
    assert trailing_update.routed == trailing_update.filled == 0
    assert len(bridge.position_lot_store.open_lots()) == 2

    bundle.market.publish_authoritative_option_quote(
        ("PUT", 90.0, "20261015"),
        {"bid": "10.5", "ask": "11.0", "last": "10.8", "timestamp": "2026-10-12T09:32:00", "contract_multiplier": "250000"},
    )
    bundle.market.publish_replay_tick(_tick("2026-10-12T09:32:00", 3, 89.0, 10.5, 11.0))
    close = loop.last_result
    assert close is not None
    assert (close.signals, close.approved, close.routed, close.filled, close.rejected) == (1, 1, 2, 2, 0)
    assert close.execution_ids
    assert bridge.position_lot_store.open_lots() == ()
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    assert vssf.account.positions == {}
    assert strategy.state.is_active is False
    assert strategy._exit_pending is False
    bundle.shutdown()
