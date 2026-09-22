from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from application.market_observation_scenario import ScenarioObservationTransformer
from contracts.types import (
    ExecutionLeg, MarketAnalytics, MarketDataProvenance, MarketObservation,
    MarketOrderBook, MarketQuote, MultiLegExecutionPlan, OptionInstrumentIdentity,
)
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.market.historical_market_store import HistoricalMarketStore

def fixture_observations():
    """Build four canonical observations for isolated-run regression coverage."""
    identity = OptionInstrumentIdentity(
        instrument_id="C01610A29", symbol="C01610A29", expiry="2026-10-08",
        option_type="PUT", strike=Decimal("1075"),
        contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
    )
    observations = []
    for index, last in enumerate((Decimal("23.45"),) * 4, start=1):
        observations.append(MarketObservation(
            observation_id=f"fixture-{index}", observed_at=None,
            collected_at=datetime(2026, 9, 21, 12, 26, index, tzinfo=timezone.utc),
            source="kis_vts_rest", provider="KISOptionRestAdapter",
            schema_version="canonical-market-observation-v1", run_id="vts-rest-fixture",
            contract=identity,
            quote=MarketQuote(last=last, bid=last, ask=last, volume=Decimal("100")),
            order_book=MarketOrderBook(), analytics=MarketAnalytics(),
            provenance=MarketDataProvenance(tr_ids=("FHMIF10000000", "FHMIF10010000")),
        ))
    return observations


def master_for(obs):
    c = obs.contract
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd=c.instrument_id, stnd_iscd=c.symbol, expiry=c.expiry or "",
        option_type=c.option_type or "", strike=Decimal(str(c.strike or "0")),
        info_type="5", contract_multiplier=c.contract_multiplier or Decimal("0"),
    ))
    return master


def bundle_for(master, name):
    deps = VirtualCompositionDependencies(
        contract_registry=None, option_master=master, contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=deps).build(
        config=EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name=name),
        policy=RuntimePolicy(),
    )
    bundle.connect()
    bundle.start()
    return bundle


def scenario_store(tmp_path, observations, scenario, run_id, transform):
    store = HistoricalMarketStore(tmp_path / f"{scenario}-{run_id}.jsonl")
    transformer = ScenarioObservationTransformer()
    for obs in observations:
        item = transformer.transform(
            obs, scenario_id=scenario, run_id=run_id, transform=transform,
            metadata={"pattern": scenario},
        )
        store.append_observation(item.observation)
    return store
def execute_one(tmp_path, observations, master, scenario, run_id, transform):
    store = scenario_store(tmp_path, observations, scenario, run_id, transform)
    bundle = bundle_for(master, f"run_{run_id}")
    bundle.market.load_historical_observation_store(store, source=f"scenario:{scenario}")
    for _ in observations:
        assert bundle.market.replay_next() is not None

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, run_id=run_id, option_master=master
    )
    plan = MultiLegExecutionPlan(
        group_id=f"{run_id}-G1", strategy_id="RUN_PATTERN_STRATEGY",
        purpose="RUN_ID_PATTERN_VALIDATION",
        legs=(ExecutionLeg("put", "BUY", 1, "PUT", Decimal("1075")),),
    )
    result = bridge.execute(plan)
    assert result.filled_legs == 1
    report = result.reports[0]
    assert report.status == "FILLED"
    assert report.client_order_id == f"{run_id}-G1-put"

    lot = bridge.position_lot_store.open_lots()[0]
    assert lot.run_id == run_id
    assert lot.execution_id == report.execution_id
    assert lot.client_order_id == report.client_order_id
    assert lot.instrument_id == "C01610A29"
    assert lot.instrument_identity.identity_source == "OPTION_MASTER"
    snapshot = bridge.position_groups.snapshot(plan.group_id)
    assert snapshot is not None
    assert snapshot.legs[0].run_id == run_id
    assert snapshot.legs[0].client_order_id == report.client_order_id
    assert snapshot.legs[0].execution_id == report.execution_id
    assert snapshot.legs[0].identity_source == "OPTION_MASTER"
    assert bundle.position.snapshot()
    bundle.stop()
    return Decimal(str(report.execution_price))


def test_actual_rest_four_records_repeat_across_isolated_runs_and_patterns(tmp_path):
    observations = fixture_observations()
    assert len(observations) == 4
    assert {o.contract.instrument_id for o in observations} == {"C01610A29"}
    assert {o.contract.identity_source for o in observations} == {"OPTION_MASTER"}
    master = master_for(observations[0])

    patterns = {
        "baseline": lambda o: o,
        "price_up": lambda o: replace(o, quote=replace(
            o.quote, bid=o.quote.bid + Decimal("2"),
            ask=o.quote.ask + Decimal("2"), last=o.quote.last + Decimal("2"))),
        "price_down": lambda o: replace(o, quote=replace(
            o.quote, bid=o.quote.bid - Decimal("2"),
            ask=o.quote.ask - Decimal("2"), last=o.quote.last - Decimal("2"))),
        "wide_spread": lambda o: replace(o, quote=replace(
            o.quote, bid=Decimal("18.00"), ask=Decimal("27.00"),
            last=Decimal("22.50"))),
    }

    results = {}
    for scenario, transform in patterns.items():
        run_id = f"PATTERN-{scenario.upper()}-001"
        results[scenario] = execute_one(
            tmp_path, observations, master, scenario, run_id, transform
        )

    assert results == {
        "baseline": Decimal("23.45"), "price_up": Decimal("25.45"),
        "price_down": Decimal("21.45"), "wide_spread": Decimal("27.00"),
    }
def test_second_run_starts_without_first_run_execution_state(tmp_path):
    observations = fixture_observations()
    master = master_for(observations[0])
    store_a = scenario_store(
        tmp_path, observations, "baseline", "RUN-A", lambda o: o
    )
    store_b = scenario_store(
        tmp_path, observations, "baseline", "RUN-B", lambda o: o
    )

    first = bundle_for(master, "run_RUN-A")
    first.market.load_historical_observation_store(store_a, source="scenario:baseline")
    for _ in observations:
        assert first.market.replay_next() is not None
    bridge_a = VirtualMultiLegExecutionBridge(
        bundle=first, run_id="RUN-A", option_master=master
    )
    plan = MultiLegExecutionPlan(
        group_id="RUN-A-G1", strategy_id="ISO",
        legs=(ExecutionLeg("put", "BUY", 1, "PUT", Decimal("1075")),),
    )
    result_a = bridge_a.execute(plan)
    assert result_a.filled_legs == 1
    assert first.position.snapshot()
    assert len(bridge_a.position_lot_store.history()) == 1
    first.stop()

    second = bundle_for(master, "run_RUN-B")
    second.market.load_historical_observation_store(store_b, source="scenario:baseline")
    assert second.position.snapshot() == {}
    assert second.execution._authoritative_execute.__self__.vssf_runtime.execution_engine.reports == []
    assert second.account.snapshot().balances["available_cash"] == Decimal("250000000.0")
    assert second.market.replay.cursor == 0
    bridge_b = VirtualMultiLegExecutionBridge(
        bundle=second, run_id="RUN-B", option_master=master
    )
    assert bridge_b.position_lot_store.history() == ()
    second.stop()
