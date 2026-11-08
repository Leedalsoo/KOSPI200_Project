from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.strategy_hub.hub import StrategyHub
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.registry import StrategyRegistry
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote


DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")
TRACK1_KEY = ("TRACK1_TAIL_DEFENSE", "1.2.0")


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
        return (
            Signal(
                strategy_id=self.strategy_id,
                direction="BUY",
                confidence=1.0,
                reason="R4_TEST_FIXTURE_ENTRY",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=1,
                    asset_type="OPTION",
                    requested_price=Decimal(str(tick.ask_price)),
                    side="BUY",
                    track_id=self.strategy_id,
                    tag_id="ENTRY",
                    option_type=str(tick.option_type),
                    strike=Decimal(str(tick.strike_price)),
                ),
            ),
        )


def test_positive_single_leg_strategy_to_virtual_fill_lifecycle():
    adapter = SyntheticReplayAdapter(DATASET)
    option_master = build_synthetic_option_master(DATASET, validation_only_adapter=adapter)
    tick = next(HighSpeedReplayRunner(DATASET, synthetic_adapter=adapter).events())
    identity = option_master.get_contract_identity(tick.instrument_id)
    assert identity is not None
    assert identity.stnd_iscd is None
    assert identity.shrn_iscd.startswith("SYNTHETIC_CONTRACT:")

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=option_master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    original_loop = bootstrap.automated_loop
    if original_loop is not None:
        bootstrap.bundle.market.unsubscribe(original_loop.on_tick)

    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(TRACK1_KEY,),
        run_id="R4-POSITIVE-ORDER-FIXTURE",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(OneShotSyntheticEntry(tick))
    loop.strategy_hub = StrategyHub(registry, (TRACK1_KEY,))

    original_context_builder = loop.context_builder
    def fixture_context_builder(current_tick, state):
        contexts = original_context_builder(current_tick, state)
        # This is explicitly test-only evidence for plumbing verification. It is
        # not a production freshness producer and never enters REAL_VTS/Live.
        observed_at = datetime.fromisoformat(current_tick.timestamp)
        verdict = FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="R4_SYNTHETIC_FIXTURE_ONLY",
            policy_version="R4-TEST-FIXTURE-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{current_tick.timestamp}|{identity.shrn_iscd}|R4-TEST".encode()
            ).hexdigest(),
        )
        context = contexts[TRACK1_KEY[0]]
        contexts[TRACK1_KEY[0]] = replace(context, input=None, freshness_verdict=verdict)
        return contexts
    loop.context_builder = fixture_context_builder

    sources.set_tick(tick)
    vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    _publish_contract_scoped_replay_quote(
        tick,
        option_master=bootstrap.bundle.option_master,
        market=bootstrap.bundle.market,
        order_book=vssf_runtime.order_book,
    )
    bootstrap.bundle.market.publish_replay_tick(tick)

    result = loop.last_result
    assert result is not None
    assert result.signals == 1
    assert result.approved == 1
    assert result.routed == 1
    assert result.filled == 1
    assert len(result.execution_ids) == 1
    assert result.execution_ids[0]
    assert identity.shrn_iscd in vssf_runtime.account.positions
    assert vssf_runtime.account.positions[identity.shrn_iscd]["qty"] == 1
    assert vssf_runtime.account.unrealized_pnl is not None
