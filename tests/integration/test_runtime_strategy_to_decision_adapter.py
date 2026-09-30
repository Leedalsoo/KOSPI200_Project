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
from core.strategy.contracts import NonExecutionEvent, Signal, SignalKind
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
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


def test_actual_runtime_strategy_ids_use_priority_on_conflicting_sides():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    winner = RuntimeStrategyEvaluation(
        context=Context("TRACK1_TAIL_DEFENSE"),
        result=make_signal(side="BUY"),
        local_sequence=1,
        runtime_context=RuntimeExecutionContext(77, 1),
    )
    loser = RuntimeStrategyEvaluation(
        context=Context("track2_asymmetric_trap"),
        result=make_signal(side="SELL"),
        local_sequence=2,
        runtime_context=RuntimeExecutionContext(77, 2),
    )
    result = adapter.arbitrate(
        [loser, winner],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
    )
    assert [s.track_id for s in result.arbitration.approved_signals] == ["TRACK1_TAIL_DEFENSE"]
    assert [s.track_id for s, _ in result.arbitration.rejected_signals] == ["track2_asymmetric_trap"]


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
        adapter.arbitrate([bad], price=351.10, timestamp="2026-09-06T10:00:00", account=None)


def test_proposalless_execution_signal_fails_closed():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    signal = Signal("Track5", "LONG", 1.0, "ENTRY_WITHOUT_PROPOSAL")
    with pytest.raises(ValueError, match="EXECUTION_PROPOSAL_REQUIRED"):
        adapter.arbitrate([evaluation(1, signal)], price=351.10, timestamp="2026-09-06T10:00:00", account=None)


def test_non_execution_event_is_not_converted_to_order():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    signal = Signal(
        "Track5", "LIQUIDITY", 0.7, "LIQUIDITY_STAGE_1",
        kind=SignalKind.NON_EXECUTION,
        non_execution_event=NonExecutionEvent("LIQUIDITY_STAGE", "state update"),
    )
    result = adapter.arbitrate([evaluation(1, signal)], price=351.10, timestamp="2026-09-06T10:00:00", account=None)
    assert result.canonical_signals == ()


def make_plan(strategy_id: str = "Track4") -> MultiLegExecutionPlan:
    return MultiLegExecutionPlan(
        group_id="G-1",
        strategy_id=strategy_id,
        purpose="TEST_MULTI_LEG",
        legs=(
            ExecutionLeg("LEG-1", "BUY", 1, position_role="NONE"),
            ExecutionLeg("LEG-2", "SELL", 1, position_role="NONE"),
        ),
    )


def test_approved_signal_can_carry_a_strategy_owned_multi_leg_decision():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [evaluation(1, make_signal())],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
        multi_leg_plan_resolver=lambda _evaluation, _canonical: make_plan(),
    )
    assert len(result.multi_leg_decisions) == 1
    decision = result.multi_leg_decisions[0]
    assert decision.signal_id == "SIG-77-Track4-1"
    assert decision.strategy_id == "Track4"
    assert decision.plan.group_id == "G-1"
    assert [leg.leg_id for leg in decision.plan.legs] == ["LEG-1", "LEG-2"]


def test_multi_leg_plan_is_not_attached_to_rejected_signal():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    calls = []
    result = adapter.arbitrate(
        [evaluation(1, make_signal(side="BUY")), evaluation(2, make_signal(side="SELL"))],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
        multi_leg_plan_resolver=lambda evaluation, _canonical: (
            calls.append(evaluation.runtime_context.local_sequence) or make_plan()
        ),
    )
    assert len(result.arbitration.approved_signals) == 1
    assert calls == [1]
    assert len(result.multi_leg_decisions) == 1
    assert result.multi_leg_decisions[0].signal_id == "SIG-77-Track4-1"


def test_multi_leg_plan_strategy_mismatch_fails_closed():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    with pytest.raises(ValueError, match="MULTI_LEG_STRATEGY_ID_MISMATCH"):
        adapter.arbitrate(
            [evaluation(1, make_signal())],
            price=351.10,
            timestamp="2026-09-06T10:00:00",
            account=None,
            multi_leg_plan_resolver=lambda _evaluation, _canonical: make_plan("OtherStrategy"),
        )
