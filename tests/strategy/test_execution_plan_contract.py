from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.composition.execution_multi_leg_resolver_registry import ExecutionMultiLegResolverRegistry
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from core.strategy.definition import StrategyDefinition
from core.strategy.execution_plan import ExecutionPlanKind, StrategyExecutionPlan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def _definition(contract: str, *, tags: tuple[str, ...] = ()) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id="strategy_x",
        code_version="1.0",
        config_version="1.0.0",
        enabled=True,
        execution_contract=contract,
        required_sources=("authoritative_quote",),
        required_analytics=(),
        required_execution_tags=tags,
        required_execution_directions=(),
        supported_exit_modes=("STOP",),
        parameters={},
        manifest_version="1.0.0",
        config_hash="0" * 64,
    )


def _evaluation(tag: str = "ENTRY") -> SimpleNamespace:
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        track_id="strategy_x", tag_id=tag,
    )
    signal = SimpleNamespace(execution_proposal=proposal, direction="BUY")
    return SimpleNamespace(result=signal)


def _canonical() -> SimpleNamespace:
    return SimpleNamespace(track_id="strategy_x")


def test_required_multi_leg_plan_fails_closed_when_resolver_is_missing() -> None:
    registry = ExecutionMultiLegResolverRegistry({
        "strategy_x": _definition("MULTI_LEG_REQUIRED"),
    })
    with pytest.raises(ValueError, match="MULTI_LEG_RESOLVER_REQUIRED"):
        registry.resolve("strategy_x", _evaluation(), _canonical())


def test_required_multi_leg_plan_fails_closed_when_resolver_returns_none() -> None:
    registry = ExecutionMultiLegResolverRegistry({
        "strategy_x": _definition("MULTI_LEG_REQUIRED"),
    })
    registry.register("strategy_x", lambda evaluation, canonical: None)
    with pytest.raises(ValueError, match="MULTI_LEG_EXECUTION_PLAN_REQUIRED"):
        registry.resolve("strategy_x", _evaluation(), _canonical())


def test_conditional_multi_leg_contract_only_requires_declared_tags() -> None:
    registry = ExecutionMultiLegResolverRegistry({
        "strategy_x": _definition("CONDITIONAL_MULTI_LEG", tags=("ENTRY",)),
    })
    assert registry.resolve("strategy_x", _evaluation("EXIT"), _canonical()) is None
    with pytest.raises(ValueError, match="MULTI_LEG_RESOLVER_REQUIRED"):
        registry.resolve("strategy_x", _evaluation("ENTRY"), _canonical())


def test_single_order_contract_does_not_require_multi_leg_resolver() -> None:
    registry = ExecutionMultiLegResolverRegistry({
        "strategy_x": _definition("SINGLE_ORDER"),
    })
    assert registry.resolve("strategy_x", _evaluation(), _canonical()) is None


def test_unified_execution_plan_has_exactly_one_execution_shape() -> None:
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY", track_id="strategy_x",
    )
    single = StrategyExecutionPlan(
        signal_id="sig-1", strategy_id="strategy_x",
        kind=ExecutionPlanKind.SINGLE_ORDER, single_order_proposal=proposal,
    )
    assert single.kind is ExecutionPlanKind.SINGLE_ORDER

    multi = MultiLegExecutionPlan(
        group_id="group-1", strategy_id="strategy_x",
        legs=(ExecutionLeg(leg_id="put", side="BUY", quantity=1),),
    )
    grouped = StrategyExecutionPlan(
        signal_id="sig-2", strategy_id="strategy_x",
        kind=ExecutionPlanKind.MULTI_LEG, multi_leg_plan=multi,
    )
    assert grouped.kind is ExecutionPlanKind.MULTI_LEG

    with pytest.raises(ValueError, match="SINGLE_ORDER_PLAN_SHAPE_INVALID"):
        StrategyExecutionPlan(
            signal_id="sig-3", strategy_id="strategy_x",
            kind=ExecutionPlanKind.SINGLE_ORDER,
            single_order_proposal=proposal, multi_leg_plan=multi,
        )


def test_track7_exit_state_waits_for_group_fill_and_position_flat_confirmation():
    from types import SimpleNamespace
    from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance, Track7State
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.state = Track7State(insurance_active=True)
    strategy._exit_pending = True
    strategy.on_execution_result("WEEKLY_INSURANCE_CLOSE", SimpleNamespace(group_complete=True, position_flat=False))
    assert strategy.state.insurance_active is True
    assert strategy._exit_pending is True
    strategy.on_execution_result("WEEKLY_INSURANCE_CLOSE", SimpleNamespace(group_complete=True, position_flat=True))
    assert strategy.state.insurance_active is False
    assert strategy._exit_pending is False


def test_track9_exit_state_waits_for_group_fill_and_position_flat_confirmation():
    from types import SimpleNamespace
    from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9State
    strategy = Track9EventOvernightInsurance()
    strategy.state = Track9State(entry_qty=1, state="OVERNIGHT_INSURANCE_CLOSE_PENDING")
    strategy._exit_pending = True
    strategy.on_execution_result("OVERNIGHT_INSURANCE_CLOSE", SimpleNamespace(group_complete=False, position_flat=True))
    assert strategy.state.entry_qty == 1
    assert strategy._exit_pending is True
    strategy.on_execution_result("OVERNIGHT_INSURANCE_CLOSE", SimpleNamespace(group_complete=True, position_flat=True))
    assert strategy.state.entry_qty == 0
    assert strategy._exit_pending is False
