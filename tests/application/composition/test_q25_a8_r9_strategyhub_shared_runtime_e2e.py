from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from itertools import islice
from pathlib import Path

import pytest

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.strategy_hub.hub import StrategyHub
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.oms.multi_leg_plan import build_trap_plan
from core.strategy.contracts import Signal, SignalKind
from core.strategy.registry import StrategyRegistry
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import (
    SyntheticRuntimeSources,
    build_synthetic_option_master,
)
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote


DATASET = "data/derived_scenario/p5_run_20261026_trend_up_seed20261026"
S2_ID = "track2_asymmetric_trap"
S5_ID = "track5_gap_divergence"


@pytest.fixture(scope="module")
def _synthetic_scenario():
    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    ticks = tuple(islice(HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events(), 60))
    expiry = "20261008"
    timestamps = sorted({tick.timestamp for tick in ticks if str(tick.expiry) == expiry})
    assert len(timestamps) >= 5

    def at(timestamp: str, option_type: str, strike: str):
        target = Decimal(strike)
        return next(
            tick for tick in ticks
            if tick.timestamp == timestamp
            and str(tick.expiry) == expiry
            and str(tick.option_type).upper() == option_type
            and Decimal(str(tick.strike_price)) == target
        )

    quote_sets = {
        timestamp: tuple(
            tick for tick in ticks
            if tick.timestamp == timestamp and str(tick.expiry) == expiry
        )
        for timestamp in timestamps[:5]
    }
    return {
        "adapter": adapter,
        "option_master": option_master,
        "entry_tick": at(timestamps[0], "CALL", "1030.0"),
        "hedge_tick": at(timestamps[0], "PUT", "1030.0"),
        "exit_tick": at(timestamps[1], "CALL", "1030.0"),
        "s2_progress_tick": at(timestamps[1], "CALL", "1030.0"),
        "s2_progress_tick_2": at(timestamps[2], "CALL", "1030.0"),
        "s2_progress_tick_3": at(timestamps[3], "CALL", "1030.0"),
        "s2_exit_tick": at(timestamps[4], "CALL", "1030.0"),
        "s2_legs": {
            "inner_put": at(timestamps[0], "PUT", "1032.5"),
            "inner_call": at(timestamps[0], "CALL", "1057.5"),
            "outer_put": at(timestamps[0], "PUT", "1030.0"),
            "outer_call": at(timestamps[0], "CALL", "1060.0"),
        },
        "quote_sets": quote_sets,
    }


class _ScenarioLifecycleStrategy:
    """Test-only signal driver; strategy logic is covered by separate strategy tests."""

    def __init__(self, strategy_id: str, version: str, phases) -> None:
        self.strategy_id = strategy_id
        self.version = version
        self._phases = tuple(phases)
        self._phase = 0

    def feature_requirements(self):
        return ()

    def initialize(self, context) -> None:
        self._phase = 0

    def on_market_state(self, context) -> None:
        return None

    def reset(self) -> None:
        self._phase = 0

    def evaluate(self, context):
        if context.strategy_id != self.strategy_id or self._phase >= len(self._phases):
            return ()
        phase = self._phases[self._phase]
        self._phase += 1
        tick, side, tag = phase
        if side is None:
            return ()
        price = Decimal(str(tick.ask_price if side == "BUY" else tick.bid_price))
        proposal = StrategyExecutionProposal(
            proposed_quantity=1,
            asset_type="OPTION",
            requested_price=price,
            side=side,
            track_id=self.strategy_id,
            tag_id=tag,
            option_type=str(tick.option_type).upper(),
            strike=Decimal(str(tick.strike_price)),
        )
        return (
            Signal(
                strategy_id=self.strategy_id,
                direction=side,
                confidence=1.0,
                reason=f"R9_VALIDATION_ONLY_SHARED_RUNTIME_{tag}",
                kind=SignalKind.EXECUTION,
                execution_proposal=proposal,
            ),
        )


@pytest.mark.parametrize("strategy_key", STANDARD_STRATEGY_KEYS)
def test_each_standard_strategy_routes_validation_scenario_through_shared_runtime(strategy_key, _synthetic_scenario):
    strategy_id, version = strategy_key
    scenario = _synthetic_scenario
    option_master = scenario["option_master"]
    entry_tick = scenario["entry_tick"]
    if strategy_id == S5_ID:
        phases = (
            (entry_tick, "BUY", "R9_E2E_ENTRY"),
            (scenario["hedge_tick"], "BUY", "R9_E2E_HEDGE"),
            (scenario["exit_tick"], "SELL", "R9_E2E_EXIT"),
        )
    elif strategy_id == S2_ID:
        phases = (
            (entry_tick, "BUY", "R9_E2E_ENTRY"),
            (scenario["s2_progress_tick"], None, None),
            (scenario["s2_progress_tick_2"], None, None),
            (scenario["s2_progress_tick_3"], None, None),
            (scenario["s2_exit_tick"], "SELL", "R9_E2E_EXIT"),
        )
    else:
        phases = (
            (entry_tick, "BUY", "R9_E2E_ENTRY"),
            (scenario["exit_tick"], "SELL", "R9_E2E_EXIT"),
        )

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    original_loop = bootstrap.automated_loop
    if original_loop is not None:
        bootstrap.bundle.market.unsubscribe(original_loop.on_tick)

    run_id = f"R9-SHARED-E2E-{strategy_id}"
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(strategy_key,),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(_ScenarioLifecycleStrategy(strategy_id, version, phases))
    loop.strategy_hub = StrategyHub(registry, (strategy_key,))

    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise AssertionError("R9_E2E_EXECUTION_PROPOSAL_REQUIRED")
        side = str(proposal.side).upper()
        if side == "BUY" and strategy_id == S2_ID:
            legs = scenario["s2_legs"]
            plan = build_trap_plan(
                group_id=f"{run_id}-ENTRY",
                strategy_id=strategy_id,
                purpose="ASYMMETRIC_TRAP_WIDE",
                short_put=Decimal(str(legs["outer_put"].strike_price)),
                short_call=Decimal(str(legs["outer_call"].strike_price)),
                long_put=Decimal(str(legs["inner_put"].strike_price)),
                long_call=Decimal(str(legs["inner_call"].strike_price)),
                quantity=1,
            )
            bound_legs = []
            for leg in plan.legs:
                master_identity = option_master.find_contract_identity(
                    str(entry_tick.expiry), str(leg.option_type), Decimal(str(leg.strike))
                )
                assert master_identity is not None
                bound_legs.append(replace(
                    leg,
                    instrument_identity=OptionInstrumentIdentity(
                        instrument_id=master_identity.shrn_iscd,
                        symbol=master_identity.shrn_iscd,
                        expiry=str(master_identity.expiry).replace("-", "")[:8],
                        option_type=str(master_identity.option_type).upper(),
                        strike=Decimal(str(master_identity.strike)),
                        contract_multiplier=Decimal(str(master_identity.contract_multiplier)),
                        identity_source="OPTION_MASTER",
                    ),
                ))
            return replace(plan, legs=tuple(bound_legs))
        if side == "BUY":
            hedge = strategy_id == S5_ID and proposal.tag_id == "R9_E2E_HEDGE"
            leg_id = "R9_E2E_HEDGE" if hedge else "R9_E2E_ENTRY"
            suffix = "HEDGE" if hedge else "ENTRY"
            return MultiLegExecutionPlan(
                group_id=f"{run_id}-GAP-HEDGE" if strategy_id == S5_ID else f"{run_id}-{suffix}",
                strategy_id=strategy_id,
                purpose=f"R9_SHARED_RUNTIME_{suffix}",
                legs=(
                    ExecutionLeg(
                        leg_id,
                        "BUY",
                        1,
                        str(proposal.option_type).upper(),
                        Decimal(str(proposal.strike)),
                        requested_price=Decimal(str(proposal.requested_price)),
                    ),
                ),
            )
        if strategy_id == S2_ID:
            purpose = "TRAP_CLOSE"
            return loop.multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id=strategy_id, purpose=purpose, asset_type="OPTION"
            )
        if strategy_id == S5_ID:
            return loop.multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id=strategy_id,
                purpose="TRACK5_GAP_HEDGE_TERMINAL_EXIT",
                asset_type="OPTION",
            )
        return loop.multi_leg_bridge.build_close_plan_from_open_lots(
            strategy_id=strategy_id,
            purpose="R9_SHARED_RUNTIME_TERMINAL_CLOSE",
            asset_type="OPTION",
            leg_id_prefix="R9_E2E_ENTRY",
        )

    loop.multi_leg_plan_resolver = plan_resolver
    current_tick = {"value": entry_tick}
    original_context_builder = loop.context_builder

    def fixture_context_builder(tick, state):
        contexts = original_context_builder(tick, state)
        identity = option_master.get_contract_identity(tick.instrument_id)
        assert identity is not None
        observed_at = datetime.fromisoformat(tick.timestamp)
        verdict = FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="R9_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R9-TEST-FIXTURE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{tick.timestamp}|{identity.shrn_iscd}|{strategy_id}|R9-TEST".encode()
            ).hexdigest(),
        )
        contexts[strategy_id] = replace(
            contexts[strategy_id], input=None, freshness_verdict=verdict
        )
        return contexts

    loop.context_builder = fixture_context_builder

    def freshness(plan, leg, leg_identity, command):
        observed_at = datetime.fromisoformat(current_tick["value"].timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="R9_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R9-TEST-FIXTURE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{command.instrument_id}|{strategy_id}|R9-TEST".encode()
            ).hexdigest(),
        )

    loop.multi_leg_bridge.freshness_verdict_provider = freshness
    if strategy_id == S2_ID:
        source_manifest = Path(DATASET) / "manifest.json"
        source_manifest_sha256 = sha256(source_manifest.read_bytes()).hexdigest()
        allowed_synthetic_ids = {
            item.shrn_iscd for item in option_master.list_contract_identities()
            if str(getattr(item, "shrn_iscd", "")).startswith("SYNTHETIC_CONTRACT:")
            and getattr(item, "stnd_iscd", None) is None
        }

        def validation_only_track2_identity_validator(plan, stored_identity, master_identity):
            return bool(
                len(source_manifest_sha256) == 64
                and master_identity is not None
                and stored_identity.instrument_id in allowed_synthetic_ids
                and stored_identity.instrument_id == master_identity.shrn_iscd
                and master_identity.stnd_iscd is None
                and str(master_identity.shrn_iscd).startswith("SYNTHETIC_CONTRACT:")
                and str(master_identity.expiry).replace("-", "")[:8] == stored_identity.expiry
                and str(master_identity.option_type).upper() == stored_identity.option_type
                and Decimal(str(master_identity.strike)) == Decimal(str(stored_identity.strike))
                and Decimal(str(master_identity.contract_multiplier)) == Decimal(str(stored_identity.contract_multiplier))
            )

        loop.multi_leg_bridge.validation_only_track2_identity_validator = validation_only_track2_identity_validator
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    for phase_index, (tick, _side, _tag) in enumerate(phases):
        current_tick["value"] = tick
        sources.set_tick(tick)
        quote_set = scenario["quote_sets"][tick.timestamp]
        for quote_tick in quote_set:
            _publish_contract_scoped_replay_quote(
                quote_tick,
                option_master=bootstrap.bundle.option_master,
                market=bootstrap.bundle.market,
                order_book=vssf_runtime.order_book,
            )
        bootstrap.bundle.market.publish_replay_tick(tick)
        result = loop.last_result
        assert result is not None
        if strategy_id == S2_ID and phase_index in {1, 2, 3}:
            assert result.signals == 0
            open_lots = tuple(
                lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.strategy_id == strategy_id and lot.remaining_quantity > 0
            )
            if phase_index == 3:
                assert len(open_lots) == 4
            else:
                assert len(open_lots) >= 2
        else:
            assert result.signals == 1
            assert result.approved == 1
            assert result.routed >= 1
            assert result.filled >= 1
            assert result.execution_ids
        if strategy_id == S5_ID and phase_index == 1:
            open_lots = tuple(
                lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.strategy_id == strategy_id and lot.remaining_quantity > 0
            )
            assert len(open_lots) == 2
            option_types = {str(lot.instrument_identity.option_type).upper() for lot in open_lots}
            assert option_types == {"CALL", "PUT"}

    open_lots = tuple(
        lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
        if lot.run_id == run_id and lot.strategy_id == strategy_id and lot.remaining_quantity > 0
    )
    assert open_lots == ()
    assert loop.fee_ledger is not None
    assert loop.fee_ledger.total(run_id=run_id) >= Decimal("0")
    assert bootstrap.bundle.account.snapshot() is not None











def test_two_strategies_share_one_account_without_cross_strategy_position_close(_synthetic_scenario):
    scenario = _synthetic_scenario
    option_master = scenario["option_master"]
    s1_key = next(key for key in STANDARD_STRATEGY_KEYS if key[0] == "TRACK1_TAIL_DEFENSE")
    s8_key = next(key for key in STANDARD_STRATEGY_KEYS if key[0] == "track8_macro_regime_monthly_strangle")
    s1_id, s1_version = s1_key
    s8_id, s8_version = s8_key
    s1_entry = scenario["entry_tick"]
    s8_entry = scenario["hedge_tick"]
    s1_exit = scenario["exit_tick"]
    s8_exit = scenario["s2_progress_tick_2"]

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    original_loop = bootstrap.automated_loop
    if original_loop is not None:
        bootstrap.bundle.market.unsubscribe(original_loop.on_tick)

    run_id = "R9-SHARED-E2E-CONCURRENT-S1-S8"
    strategy_keys = (s1_key, s8_key)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=strategy_keys,
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(_ScenarioLifecycleStrategy(
        s1_id, s1_version,
        ((s1_entry, "BUY", "R9_E2E_ENTRY"), (s1_exit, "SELL", "R9_E2E_EXIT")),
    ))
    registry.register(_ScenarioLifecycleStrategy(
        s8_id, s8_version,
        ((s8_entry, "BUY", "R9_E2E_ENTRY"), (s1_exit, None, None), (s8_exit, "SELL", "R9_E2E_EXIT")),
    ))
    loop.strategy_hub = StrategyHub(registry, strategy_keys)

    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise AssertionError("R9_CONCURRENT_E2E_EXECUTION_PROPOSAL_REQUIRED")
        strategy_id = str(evaluation.context.strategy_id)
        if str(proposal.side).upper() == "BUY":
            return MultiLegExecutionPlan(
                group_id=f"{run_id}-{strategy_id}-ENTRY",
                strategy_id=strategy_id,
                purpose="R9_CONCURRENT_SHARED_RUNTIME_ENTRY",
                legs=(ExecutionLeg(
                    "R9_E2E_ENTRY",
                    "BUY",
                    1,
                    str(proposal.option_type).upper(),
                    Decimal(str(proposal.strike)),
                    requested_price=Decimal(str(proposal.requested_price)),
                ),),
            )
        return loop.multi_leg_bridge.build_close_plan_from_open_lots(
            strategy_id=strategy_id,
            purpose="R9_CONCURRENT_SHARED_RUNTIME_EXIT",
            asset_type="OPTION",
            leg_id_prefix="R9_E2E_ENTRY",
        )

    loop.multi_leg_plan_resolver = plan_resolver
    target_identities = {
        s1_id: option_master.get_contract_identity(s1_entry.instrument_id),
        s8_id: option_master.get_contract_identity(s8_entry.instrument_id),
    }
    assert all(target_identities.values())
    current_tick = {"value": s1_entry}
    original_context_builder = loop.context_builder

    def fixture_context_builder(tick, state):
        contexts = original_context_builder(tick, state)
        observed_at = datetime.fromisoformat(tick.timestamp)
        for strategy_id, identity in target_identities.items():
            verdict = FreshnessVerdict(
                status=FreshnessStatus.FRESH,
                reason="R9_SYNTHETIC_FIXTURE_ONLY",
                policy_version="R9-TEST-FIXTURE-v1",
                source="DERIVED_SCENARIO_TEST_FIXTURE",
                tr_id="SYNTHETIC-REPLAY-TEST",
                environment="VIRTUAL_VALIDATION_ONLY",
                instrument_id=identity.shrn_iscd,
                symbol=identity.shrn_iscd,
                source_instant=observed_at,
                received_at=observed_at,
                evidence_sha256=sha256(
                    f"{tick.timestamp}|{identity.shrn_iscd}|{strategy_id}|R9-CONCURRENT".encode()
                ).hexdigest(),
            )
            contexts[strategy_id] = replace(
                contexts[strategy_id], input=None, freshness_verdict=verdict
            )
        return contexts

    loop.context_builder = fixture_context_builder

    def freshness(plan, leg, leg_identity, command):
        observed_at = datetime.fromisoformat(current_tick["value"].timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="R9_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R9-TEST-FIXTURE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{command.instrument_id}|{command.strategy_id}|R9-CONCURRENT".encode()
            ).hexdigest(),
        )

    loop.multi_leg_bridge.freshness_verdict_provider = freshness
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    phases = (s1_entry, s1_exit, s8_exit)
    for phase_index, tick in enumerate(phases):
        current_tick["value"] = tick
        sources.set_tick(tick)
        for quote_tick in scenario["quote_sets"][tick.timestamp]:
            _publish_contract_scoped_replay_quote(
                quote_tick,
                option_master=bootstrap.bundle.option_master,
                market=bootstrap.bundle.market,
                order_book=vssf_runtime.order_book,
            )
        bootstrap.bundle.market.publish_replay_tick(tick)
        result = loop.last_result
        assert result is not None
        if phase_index == 0:
            assert result.signals == 2
            assert result.approved == 2
            assert result.routed == 2
            assert result.filled == 2
            open_lots = tuple(
                lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.remaining_quantity > 0
            )
            assert {lot.strategy_id for lot in open_lots} == {s1_id, s8_id}
        elif phase_index == 1:
            assert result.signals == 1
            assert result.approved == 1
            open_lots = tuple(
                lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.remaining_quantity > 0
            )
            assert {lot.strategy_id for lot in open_lots} == {s8_id}
        else:
            assert result.signals == 1
            assert result.approved == 1
            open_lots = tuple(
                lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
                if lot.run_id == run_id and lot.remaining_quantity > 0
            )
            assert open_lots == ()

    assert loop.fee_ledger is not None
    assert loop.fee_ledger.total(run_id=run_id) >= Decimal("0")

