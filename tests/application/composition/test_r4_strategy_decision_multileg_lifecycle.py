from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.strategy_hub.hub import StrategyHub
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.registry import StrategyRegistry
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote


DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")
TRACK1_KEY = ("TRACK1_TAIL_DEFENSE", "1.1.0")


class OneShotSyntheticEntry:
    strategy_id = TRACK1_KEY[0]
    version = TRACK1_KEY[1]

    def __init__(self, tick):
        self.tick = tick

    def feature_requirements(self):
        return ()

    def initialize(self, context: StrategyContext) -> None:
        pass

    def on_market_state(self, context: StrategyContext) -> None:
        pass

    def reset(self) -> None:
        pass

    def evaluate(self, context: StrategyContext):
        tick = self.tick
        return (Signal(
            strategy_id=self.strategy_id, direction="BUY", confidence=1.0,
            reason="R4_TEST_FIXTURE_MULTI_LEG_ENTRY",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=1, asset_type="OPTION",
                requested_price=Decimal(str(tick.ask_price)), side="BUY",
                track_id=self.strategy_id, tag_id="R4_MULTI_LEG_FIXTURE",
                option_type=str(tick.option_type), strike=Decimal(str(tick.strike_price)),
            ),
        ),)


def _identity(tick, option_master) -> OptionInstrumentIdentity:
    identity = option_master.get_contract_identity(tick.instrument_id)
    assert identity is not None and identity.stnd_iscd is None
    return OptionInstrumentIdentity(
        identity.shrn_iscd, identity.shrn_iscd, identity.expiry, identity.option_type,
        Decimal(str(identity.strike)), Decimal(str(identity.contract_multiplier)),
        "DERIVED_SCENARIO_TEST_FIXTURE",
    )


def test_positive_strategy_decision_resolver_bridge_multileg_lifecycle():
    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    events = HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events()
    call_tick = next(events)
    put_tick = next(
        tick for tick in events
        if str(tick.option_type).upper() == "PUT"
        and str(tick.expiry) == str(call_tick.expiry)
        and float(tick.strike_price) == float(call_tick.strike_price)
    )
    call_identity = _identity(call_tick, option_master)
    put_identity = _identity(put_tick, option_master)
    assert call_identity.instrument_id != put_identity.instrument_id
    assert call_identity.expiry == put_identity.expiry and call_identity.strike == put_identity.strike

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(TRACK1_KEY,), run_id="R4-STRATEGY-DECISION-MULTILEG",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(OneShotSyntheticEntry(call_tick))
    loop.strategy_hub = StrategyHub(registry, (TRACK1_KEY,))

    def resolve_test_multileg(evaluation, canonical):
        assert canonical.track_id == TRACK1_KEY[0]
        assert evaluation.result.reason == "R4_TEST_FIXTURE_MULTI_LEG_ENTRY"
        return MultiLegExecutionPlan(
            group_id="R4-STRATEGY-DECISION-MULTILEG-GROUP",
            strategy_id=TRACK1_KEY[0],
            purpose="R4_TEST_FIXTURE_ONLY",
            legs=(
                ExecutionLeg("call-leg", "BUY", 1, option_type="CALL", strike=call_identity.strike, instrument_identity=call_identity),
                ExecutionLeg("put-leg", "BUY", 1, option_type="PUT", strike=put_identity.strike, instrument_identity=put_identity),
            ),
        )
    loop.multi_leg_plan_resolver = resolve_test_multileg

    def fixture_freshness(plan, leg, identity, command):
        observed_at = datetime.fromisoformat(call_tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason="R4_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R4-TEST-FIXTURE-v1", source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST", environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id, symbol=command.broker_symbol,
            source_instant=observed_at, received_at=observed_at,
            evidence_sha256=sha256(f"{observed_at.isoformat()}|{command.instrument_id}|R4-TEST".encode()).hexdigest(),
        )
    loop.multi_leg_bridge.freshness_verdict_provider = fixture_freshness

    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    for tick in (call_tick, put_tick):
        _publish_contract_scoped_replay_quote(
            tick, option_master=bootstrap.bundle.option_master,
            market=bootstrap.bundle.market, order_book=vssf_runtime.order_book,
        )
    sources.set_tick(call_tick)
    bootstrap.bundle.market.publish_replay_tick(call_tick)

    result = loop.last_result
    assert result is not None
    assert result.signals == 1 and result.approved == 1
    assert result.routed == 2 and result.filled == 2
    assert len(result.execution_ids) == 2 and all(result.execution_ids)
    group = loop.multi_leg_bridge.position_groups.snapshot("R4-STRATEGY-DECISION-MULTILEG-GROUP")
    assert len(group.legs) == 2
    assert {lot.instrument_id for lot in loop.multi_leg_bridge.position_lot_store.open_lots()} == {
        call_identity.instrument_id, put_identity.instrument_id,
    }



def test_missing_production_freshness_evidence_fails_closed_before_virtual_broker():
    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    tick = next(HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events())
    identity = _identity(tick, option_master)

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(TRACK1_KEY,), run_id="R4-MISSING-PRODUCTION-FRESHNESS",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(OneShotSyntheticEntry(tick))
    loop.strategy_hub = StrategyHub(registry, (TRACK1_KEY,))

    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    _publish_contract_scoped_replay_quote(
        tick, option_master=bootstrap.bundle.option_master,
        market=bootstrap.bundle.market, order_book=vssf_runtime.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    result = loop.last_result
    assert result is not None
    assert result.signals == 1
    assert result.approved == 1
    assert result.routed == 0
    assert result.filled == 0
    assert result.rejected == 1
    assert result.execution_ids == ()
    assert loop.broker_adapter.last_report is None
    assert identity.instrument_id not in vssf_runtime.account.positions
