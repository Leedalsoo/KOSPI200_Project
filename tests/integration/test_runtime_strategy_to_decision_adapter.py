from dataclasses import dataclass
from decimal import Decimal

import pytest

from application.composition.runtime_strategy_result_collection_adapter import (
RuntimeStrategyEvaluation,
)
from application.composition.runtime_strategy_to_decision_adapter import (
RuntimeStrategyToDecisionAdapter,
)
from core.decision.decision_arbiter import DecisionArbiter
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Context:
    strategy_id: str


def make_signal(*, side: str = "BUY", qty: int = 1) -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=qty,
        asset_type="FUTURES",
        requested_price=Decimal("350.25"),
        side=side,
        track_id="Track4",
        tag_id="DELTA_HEDGE",
    )
    return Signal(
        strategy_id="Track4",
        direction="LONG",
        confidence=1.0,
        reason="DELTA_HEDGE",
        execution_proposal=proposal,
    )


def evaluation(local_sequence: int, signal: Signal) -> RuntimeStrategyEvaluation:
    return RuntimeStrategyEvaluation(
        context=Context("Track4"),
        result=signal,
        local_sequence=local_sequence,
        runtime_context=RuntimeExecutionContext(77, local_sequence),
    )


def test_runtime_evaluations_use_runtime_owned_ids_then_existing_arbiter():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [evaluation(1, make_signal()), evaluation(2, make_signal())],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
    )

    assert [s.signal_id for s in result.canonical_signals] == [
        "SIG-77-Track4-1", "SIG-77-Track4-2"
    ]
    assert [s.qty for s in result.canonical_signals] == [1, 1]
    assert [s.price for s in result.canonical_signals] == [351.10, 351.10]
    assert result.arbitration.approved_signals == list(result.canonical_signals)


def test_conflicting_sides_are_resolved_by_existing_arbiter_without_adapter_rewrite():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [evaluation(1, make_signal(side="BUY")), evaluation(2, make_signal(side="SELL"))],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
    )
    assert len(result.arbitration.approved_signals) == 1
    assert len(result.arbitration.rejected_signals) == 1


def test_missing_runtime_track_identity_fails_closed():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    bad = RuntimeStrategyEvaluation(
        context=Context(""), result=make_signal(), local_sequence=1,
        runtime_context=RuntimeExecutionContext(77, 1),
    )
    with pytest.raises(ValueError, match="RUNTIME_TRACK_ID_REQUIRED"):
        pass
        adapter.arbitrate([bad], price=351.10, timestamp="2026-09-06T10:00:00", account=None)
