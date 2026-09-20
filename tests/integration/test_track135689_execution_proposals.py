from datetime import datetime, timezone
from decimal import Decimal

from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsSnapshot, AnalyticsStatus
from contracts.types import OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1TailDefense, Track1Input
from core.strategy.track5_gap_divergence import Track5GapDivergence


def test_track1_futures_unwind_has_proposal_with_active_quantity():
    strategy = Track1TailDefense()
    context = StrategyContext(strategy_id=strategy.strategy_id)
    strategy.initialize(context)
    strategy.state.market_opened = True
    strategy.state.base_price = 350.0
    strategy.state.active_fence_type = "PUT"
    strategy.state.active_fence_strike = 342.5
    strategy.state.active_hedge = "SELL"
    strategy.state.hedge_entry_price = 350.0
    strategy.state.active_hedge_quantity = 3
    context = StrategyContext(
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=Track1Input(current_time=None, momentum_confirmed=True)),
        market_state=None,
    )
    signal = strategy._build_hedge_unwind_signal()
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "FUTURES"
    assert signal.execution_proposal.side == "BUY"
    assert signal.execution_proposal.proposed_quantity == 3


def track5_snapshot(current_price="354", gap="4", z_score="2.0", regime="NORMAL"):
    now = datetime.now(timezone.utc)
    values = {
        "price.open": Decimal("350") + Decimal(gap),
        "price.gap": Decimal(gap), "price.last": Decimal(current_price),
        "price.previous_close": Decimal("350"), "volatility.active": Decimal("1.5"),
        "volatility.expected_move": Decimal("2.0"), "stats.z_score": Decimal(z_score),
        "regime.market": regime,
    }
    return AnalyticsSnapshot(
        "test-run", None, now, "tick", 1, "1",
        {k: AnalyticsMetric(k, v, AnalyticsStatus.AVAILABLE, "test", now, "1", (AnalyticsProvenance(source="test"),)) for k, v in values.items()},
    )


def test_track5_entry_is_fail_closed_without_execution_metadata():
    signal = Track5GapDivergence().evaluate(StrategyContext(strategy_id="track5_gap_divergence", analytics=track5_snapshot()))[0]
    assert signal.execution_proposal is None


def test_track5_entry_consumes_common_analytics():
    strategy = Track5GapDivergence()
    signals = strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id, analytics=track5_snapshot()))
    assert signals and signals[0].direction == "SHORT"
    assert strategy.state.target_price == Decimal("350")


def test_track5_proposal_requires_explicit_execution_metadata():
    # Standard Strategy 5 has no authoritative execution-quantity source in its
    # analytics contract, so it deliberately emits no execution proposal.
    signal = Track5GapDivergence().evaluate(StrategyContext(strategy_id="track5_gap_divergence", analytics=track5_snapshot()))[0]
    assert signal.execution_proposal is None
