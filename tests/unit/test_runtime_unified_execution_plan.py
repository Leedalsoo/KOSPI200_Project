from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.execution_plan import ExecutionPlanKind
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def _evaluation(strategy_id: str = "track4_gamma_scalping"):
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-TEST", symbol="OPT-TEST", expiry="2026-10-15",
        option_type="CALL", strike=Decimal("500"),
        contract_multiplier=Decimal("250000"), identity_source="test",
    )
    signal = Signal(
        strategy_id=strategy_id, direction="BUY", confidence=1.0, reason="ENTRY",
        execution_proposal=StrategyExecutionProposal(
            proposed_quantity=1, asset_type="OPTION", side="BUY",
            track_id=strategy_id, tag_id="ENTRY", option_type="CALL",
            strike=Decimal("500"),
        ),
    )
    context = StrategyContext(strategy_id=strategy_id)
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1,
        context=context,
        result=SimpleNamespace(
            signals=(signal,),
            config_provenance=((strategy_id, "1.0", "cfg-1", "a" * 64),),
        ),
    )
    return evaluations, identity


def test_adapter_emits_unified_single_order_execution_plan():
    evaluations, identity = _evaluation()
    result = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations, price=500.0, timestamp="2026-10-10T10:00:00",
        account=object(),
        instrument_identity_provider=lambda _evaluation, _tick: identity,
    )
    assert len(result.execution_plans) == 1
    plan = result.execution_plans[0]
    assert plan.kind is ExecutionPlanKind.SINGLE_ORDER
    assert plan.single_order_proposal is not None
    assert plan.multi_leg_plan is None
    assert plan.strategy_config_version == "cfg-1"
    assert plan.strategy_config_hash == "a" * 64
    assert result.multi_leg_decisions == ()


def test_adapter_emits_unified_multi_leg_execution_plan_and_compatibility_projection():
    strategy_id = "track2_asymmetric_trap"
    evaluations, identity = _evaluation(strategy_id)
    multi_leg = MultiLegExecutionPlan(
        group_id="group-test", strategy_id=strategy_id,
        legs=(ExecutionLeg(leg_id="call", side="BUY", quantity=1),),
    )
    result = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations, price=500.0, timestamp="2026-10-10T10:00:00",
        account=object(),
        instrument_identity_provider=lambda _evaluation, _tick: identity,
        multi_leg_plan_resolver=lambda _evaluation, _canonical: multi_leg,
    )
    assert len(result.execution_plans) == 1
    assert result.execution_plans[0].kind is ExecutionPlanKind.MULTI_LEG
    execution_plan = result.execution_plans[0]
    assert execution_plan.multi_leg_plan is not None
    assert execution_plan.multi_leg_plan.strategy_config_version == "cfg-1"
    assert execution_plan.multi_leg_plan.strategy_config_hash == "a" * 64
    assert result.multi_leg_decisions[0].plan is execution_plan.multi_leg_plan
