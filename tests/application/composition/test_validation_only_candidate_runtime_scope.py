from decimal import Decimal

import pytest

from application.composition.concrete_virtual_environment_builder import (
    ReferenceVirtualAuthoritativeScopeFactory,
)
from application.composition.virtual_composition_dependencies import (
    VirtualCompositionDependencies,
)
from application.run_hub.contracts import RunContextFactory
from application.run_hub.hub import RunScenarioHub, RunSession
from environments.virtual.authoritative_vssf.firm_runtime import (
    VirtualSecuritiesFirmRuntime,
)
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from environments.virtual.execution.vssf_command_context_provider import (
    CanonicalVSSFCommandContextProvider,
)
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalExecutionReport,
    CanonicalOptionType,
    CanonicalOrderSide,
)


def _report(exec_id: str, side: CanonicalOrderSide, price: float):
    return CanonicalExecutionReport(
        exec_id=exec_id,
        client_order_id=f"client-{exec_id}",
        track_id="S2",
        asset_type=CanonicalAssetType.OPTION,
        side=side,
        executed_qty=1,
        executed_price=price,
        fee=Decimal("10"),
        slippage=0.0,
        timestamp="2026-11-20T09:00:00+09:00",
        symbol="SYNTHETIC_CONTRACT:CANDIDATE-PUT",
        option_type=CanonicalOptionType.PUT,
        strike=500.0,
        expiry="20261210",
        strategy_id="track2_asymmetric_trap",
        group_id="VALIDATION_ONLY:RUN:RUNTIME-1:CANDIDATE:CAND-A",
        leg_id="put",
        instrument_id="SYNTHETIC_CONTRACT:CANDIDATE-PUT",
        contract_multiplier=100000.0,
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def _replay(account: PaperTradingAccount):
    account.apply_execution(_report("entry", CanonicalOrderSide.BUY, 5.0))
    account.update_tick_price(7.0, "SYNTHETIC_CONTRACT:CANDIDATE-PUT")
    account.apply_execution(_report("exit", CanonicalOrderSide.SELL, 6.0))
    return (
        account.realized_pnl,
        account.unrealized_pnl,
        account.balance,
        dict(account.positions),
    )


def test_vssf_runtime_and_account_are_bound_to_same_candidate_scope():
    runtime = VirtualSecuritiesFirmRuntime(
        validation_run_id="RUNTIME-1", validation_candidate_id="CAND-A",
    )
    assert runtime.validation_run_id == runtime.account.validation_run_id == "RUNTIME-1"
    assert runtime.validation_candidate_id == runtime.account.validation_candidate_id == "CAND-A"


def test_candidate_runtime_accounts_are_isolated_and_replay_is_deterministic():
    candidate_a = VirtualSecuritiesFirmRuntime(
        validation_run_id="RUNTIME-1", validation_candidate_id="CAND-A",
    )
    candidate_b = VirtualSecuritiesFirmRuntime(
        validation_run_id="RUNTIME-1", validation_candidate_id="CAND-B",
    )
    replay_a = VirtualSecuritiesFirmRuntime(
        validation_run_id="RUNTIME-1", validation_candidate_id="CAND-A",
    )

    result_a = _replay(candidate_a.account)
    result_replay = _replay(replay_a.account)
    assert result_a == result_replay
    assert candidate_a.account.realized_pnl == Decimal("100000.0")
    assert candidate_a.account.unrealized_pnl == Decimal("0")
    assert candidate_a.account.balance == Decimal("24999980")
    assert candidate_b.account.realized_pnl == Decimal("0")
    assert candidate_b.account.balance == Decimal("25000000.0")
    assert candidate_b.account.positions == {}


def test_candidate_scope_requires_run_and_candidate_ids_together():
    with pytest.raises(ValueError, match="VSSF_VALIDATION_RUN_AND_CANDIDATE_ID_REQUIRED_TOGETHER"):
        VirtualSecuritiesFirmRuntime(validation_candidate_id="CAND-A")
    with pytest.raises(ValueError, match="VSSF_ACCOUNT_VALIDATION_RUN_AND_CANDIDATE_ID_REQUIRED_TOGETHER"):
        PaperTradingAccount(validation_run_id="RUNTIME-1")


def test_reference_scope_factory_injects_candidate_identity_into_new_runtime():
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        contract_mappings={},
        initial_capital=25_000_000,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
        validation_run_id="RUNTIME-1",
        validation_candidate_id="CAND-A",
    )
    scope = ReferenceVirtualAuthoritativeScopeFactory(
        dependencies=dependencies,
    ).create(config=None, policy=None)
    assert scope.vssf_runtime.validation_candidate_id == "CAND-A"
    assert scope.vssf_runtime.account.validation_candidate_id == "CAND-A"
    assert scope.account._account_source is scope.vssf_runtime.account


def test_run_context_restart_preserves_validation_candidate_identity():
    factory = RunContextFactory()
    hub = RunScenarioHub(context_factory=factory)
    created = []

    def session_factory(context):
        created.append(context)
        return RunSession(
            context=context,
            runtime_controller=type("Controller", (), {"stop": lambda self: None})(),
            bundle=None,
            strategy_hub=None,
            runtime_hub=None,
            ui_adapter=None,
            control_tower_hub=None,
        )

    hub.configure(session_factory)
    first = hub.start(
        run_id="RUNTIME-1",
        environment="virtual",
        validation_candidate_id="CAND-A",
        session_factory=session_factory,
    )
    second = hub.restart()
    assert first.context.validation_candidate_id == "CAND-A"
    assert second.context.validation_candidate_id == "CAND-A"
    assert len(created) == 2
