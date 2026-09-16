from decimal import Decimal

from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


def _bundle(tmp_path):
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(
        KisOptionContractIdentity(
            shrn_iscd="201S11305",
            stnd_iscd="KR4101S11305",
            expiry="2026-10-15",
            option_type="CALL",
            strike=Decimal("510"),
            info_type="5",
            contract_multiplier=Decimal("250000"),
        )
    )
    deps = VirtualCompositionDependencies(
        contract_registry=None,
        contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
        option_master=master,
    )
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="historical-e2e")
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=deps).build(config=config, policy=RuntimePolicy())
    bundle.connect()
    bundle.start()
    return bundle


def test_historical_replay_flows_through_broker_api_and_multi_leg_execution(tmp_path):
    bundle = _bundle(tmp_path)
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-10-15T10:00:00.123",
        underlying_price=512.5,
        strike_price=510.0,
        option_type="CALL",
        contract_multiplier=250000.0,
        bid_price=3.20,
        ask_price=3.30,
        last_price=3.25,
        volume=120,
        seq_id=7,
        expiry="202610",
        symbol="201S11305",
    )
    store.append(tick, source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    replayed = bundle.market.replay_next()

    quote = bundle.broker_api.get_option_quote(
        option_type="CALL", strike=510.0, expiry="202610"
    )
    assert replayed == tick
    assert quote["contract_multiplier"] == 250000.0

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, option_master=bundle.option_master
    )
    plan = MultiLegExecutionPlan(
        group_id="HIST-E2E-G1",
        strategy_id="HIST-E2E-S1",
        purpose="HISTORICAL_REPLAY",
        legs=(ExecutionLeg("call", "BUY", 1, "CALL", Decimal("510")),),
    )

    identity = bridge.identity_for_leg(plan, plan.legs[0])
    assert identity.instrument_id == "201S11305"
    assert identity.expiry == "202610"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("510")

    result = bridge.execute(plan)
    assert result.group_id == plan.group_id
    assert result.filled_legs == 1
    assert result.group_complete is True
    assert len(result.reports) == 1
    assert Decimal(str(result.reports[0].execution_price)) == Decimal("3.30")
    assert result.reports[0].leg_id == "call"
    snapshot = bridge.position_groups.snapshot(plan.group_id)
    assert snapshot is not None
    assert snapshot.total_pnl == -12500.0
    assert bridge.provenance[result.reports[0].execution_id]["strategy_id"] == plan.strategy_id
    assert bridge.provenance[result.reports[0].execution_id]["group_id"] == plan.group_id
    assert bridge.provenance[result.reports[0].execution_id]["leg_id"] == "call"


def test_historical_replay_rejects_multiplier_mismatch(tmp_path):
    bundle = _bundle(tmp_path)
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    store.append(
        ReferenceCanonicalMarketTick(
            timestamp="2026-10-15T10:00:00.123",
            underlying_price=512.5, strike_price=510.0, option_type="CALL",
            contract_multiplier=250000.0, bid_price=3.20, ask_price=3.30,
            last_price=3.25, volume=120, seq_id=8, expiry="202610",
            symbol="201S11305",
        ), source="KIS:H0IOCNT0"
    )
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    bundle.market.replay_next()
    bundle.market.publish_authoritative_option_quote(
        ("CALL", 510.0, "202610"),
        {"bid": 3.20, "ask": 3.30, "last": 3.25,
         "timestamp": "2026-10-15T10:00:00.123", "contract_multiplier": 50000},
    )
    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, option_master=bundle.option_master)
    plan = MultiLegExecutionPlan(
        group_id="HIST-MISMATCH-G1", strategy_id="HIST-MISMATCH-S1",
        legs=(ExecutionLeg("call", "BUY", 1, "CALL", Decimal("510")),),
    )
    import pytest
    with pytest.raises(ValueError, match="MULTI_LEG_OPTION_CONTRACT_MULTIPLIER_MISMATCH"):
        bridge.execute(plan)
