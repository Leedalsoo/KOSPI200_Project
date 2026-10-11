from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.strategy5_risk_diagnostic_jsonl import Strategy5RiskDiagnosticJsonl
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel
from contracts.types import EnvironmentType, ExecutionLeg, MultiLegExecutionPlan
from core.option.option_master import InMemoryOptionContractMaster
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


class _AllowedVirtualRiskGuard:
    def snapshot(self) -> RiskGuardStatusSnapshot:
        return RiskGuardStatusSnapshot(
            observed_at=datetime.now(timezone.utc),
            admission_allowed=True,
            kill_switch_engaged=False,
            health_level=SensorLevel.GREEN,
            reason="ISOLATED_VIRTUAL_TEST_READY",
            decision_version="fixture-v1",
        )


class _FailingWriter:
    def append_preflight(self, **_payload: Any) -> Path:
        raise OSError("isolated diagnostic storage failure")


class _CountingRouter:
    def __init__(self, router: Any) -> None:
        self._router = router
        self.calls = 0

    def register_and_route(self, *args: Any, **kwargs: Any):
        self.calls += 1
        return self._router.register_and_route(*args, **kwargs)


def _run_case(*, fail_writer: bool, output_root: Path) -> dict[str, Any]:
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=master,
        contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(
            environment=EnvironmentType.VIRTUAL,
            name="strategy5-risk-diagnostic-isolation-test",
        ),
        RuntimePolicy(allow_live_orders=False),
    )
    bundle.initialize()
    bundle.connect()
    bundle.start()

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle,
        run_id="isolated-risk-compare",
        option_master=master,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
    )
    bridge._strategy5_risk_diagnostic = (
        _FailingWriter() if fail_writer else Strategy5RiskDiagnosticJsonl(output_root)
    )
    router = _CountingRouter(bridge.router)
    bridge.router = router

    identity = FuturesInstrumentIdentity(
        "TEST-MINI-2001",
        "TEST-MINI-2001",
        FuturesProductType.MINI,
        Decimal("50000"),
        "ISOLATED_TEST_FIXTURE",
    )
    # Quantity 51 is intentionally above the existing RiskConfig cap (50),
    # so both cases must reject before the router and cannot create a fill.
    leg = ExecutionLeg(
        leg_id="futures-risk-rejection",
        side="BUY",
        quantity=51,
        requested_price=Decimal("100"),
        position_role="NONE",
        instrument_identity=identity,
    )
    plan = MultiLegExecutionPlan(
        group_id="isolated-risk-group",
        strategy_id="track5_gap_divergence",
        purpose="DIAGNOSTIC_ISOLATION_TEST",
        legs=(leg,),
    )

    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    account_before = bundle.account.snapshot()
    positions_before = dict(vssf.account.positions)
    open_lots_before = bridge.position_lot_store.open_lots()
    result = bridge.execute(plan)
    account_after = bundle.account.snapshot()
    positions_after = dict(vssf.account.positions)
    open_lots_after = bridge.position_lot_store.open_lots()
    approvals = bridge.risk_approval_read_model.for_group(plan.group_id)
    report = result.reports[0]

    case = {
        "diagnostic_status": bridge.risk_diagnostic_status["status"],
        "risk_decision": approvals[0].result.decision,
        "risk_approved": approvals[0].result.is_approved,
        "risk_reason": approvals[0].result.rejection_reason,
        "report_status": report.status,
        "report_reason": report.rejected_reason,
        "routed_legs": result.routed_legs,
        "filled_legs": result.filled_legs,
        "router_calls": router.calls,
        "account_balances_before": dict(account_before.balances),
        "account_balances_after": dict(account_after.balances),
        "positions_before": positions_before,
        "positions_after": positions_after,
        "open_lots_before": open_lots_before,
        "open_lots_after": open_lots_after,
    }
    if not fail_writer:
        artifacts = list(output_root.glob("*.jsonl"))
        assert len(artifacts) == 1
        lines = artifacts[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["schema_version"] == "strategy5-risk-diagnostic.v1"
        assert record["event_type"] == "GROUP_RISK_PREFLIGHT"
        assert record["provenance"] == {
            "run_id": "isolated-risk-compare",
            "strategy_id": "track5_gap_divergence",
            "group_id": "isolated-risk-group",
        }
        assert record["aggregate"]["decision"] == "DENY"
        assert record["legs"][0]["risk_decision"] == "DENY"
        case["jsonl_records"] = len(lines)
    else:
        assert not list(output_root.glob("*.jsonl"))
        case["jsonl_records"] = 0

    bundle.shutdown()
    return case


def test_virtual_runtime_diagnostic_storage_failure_does_not_change_risk_or_order_flow(tmp_path: Path) -> None:
    success = _run_case(fail_writer=False, output_root=tmp_path / "success")
    failure = _run_case(fail_writer=True, output_root=tmp_path / "failure")

    assert success["diagnostic_status"] == "RECORDED"
    assert failure["diagnostic_status"] == "FAILED"
    assert success["jsonl_records"] == 1
    assert failure["jsonl_records"] == 0

    compared_fields = (
        "risk_decision",
        "risk_approved",
        "risk_reason",
        "report_status",
        "report_reason",
        "routed_legs",
        "filled_legs",
        "router_calls",
        "account_balances_before",
        "account_balances_after",
        "positions_before",
        "positions_after",
        "open_lots_before",
        "open_lots_after",
    )
    assert {field: success[field] for field in compared_fields} == {
        field: failure[field] for field in compared_fields
    }
    assert success["risk_decision"] == "DENY"
    assert success["risk_approved"] is False
    assert success["routed_legs"] == failure["routed_legs"] == 0
    assert success["router_calls"] == failure["router_calls"] == 0
    assert success["filled_legs"] == failure["filled_legs"] == 0
    assert success["positions_before"] == success["positions_after"]
    assert failure["positions_before"] == failure["positions_after"]
    assert success["open_lots_before"] == success["open_lots_after"]
    assert failure["open_lots_before"] == failure["open_lots_after"]


def _run_approved_fill_case(*, fail_writer: bool, output_root: Path) -> dict[str, Any]:
    from contracts.types import CanonicalFuturesQuote

    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=master,
        contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(
            environment=EnvironmentType.VIRTUAL,
            name="strategy5-risk-diagnostic-approved-fill-isolation-test",
        ),
        RuntimePolicy(allow_live_orders=False),
    )
    bundle.initialize()
    bundle.connect()
    bundle.start()

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle,
        run_id="isolated-approved-fill-compare",
        option_master=master,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
    )
    bridge._strategy5_risk_diagnostic = (
        _FailingWriter() if fail_writer else Strategy5RiskDiagnosticJsonl(output_root)
    )
    router = _CountingRouter(bridge.router)
    bridge.router = router

    identity = FuturesInstrumentIdentity(
        "TEST-MINI-2001",
        "TEST-MINI-2001",
        FuturesProductType.MINI,
        Decimal("50000"),
        "ISOLATED_TEST_FIXTURE",
    )
    # This test-only quote is explicitly DERIVED_SCENARIO input in an isolated
    # Virtual bundle. It is never written to REAL_VTS or sent to a Live broker.
    observed_at = datetime.now(timezone.utc)
    bundle.market.publish_authoritative_futures_quote(
        CanonicalFuturesQuote(
            instrument_id=identity.instrument_id,
            observed_at=observed_at,
            bid_price=Decimal("350"),
            ask_price=Decimal("350"),
            last_price=Decimal("350"),
            source="DERIVED_SCENARIO_TEST_FIXTURE",
        )
    )
    leg = ExecutionLeg(
        leg_id="futures-approved-fill",
        side="BUY",
        quantity=1,
        requested_price=Decimal("350"),
        position_role="NONE",
        instrument_identity=identity,
    )
    plan = MultiLegExecutionPlan(
        group_id="isolated-approved-fill-group",
        strategy_id="track5_gap_divergence",
        purpose="DIAGNOSTIC_APPROVED_FILL_ISOLATION_TEST",
        legs=(leg,),
    )

    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    account_before = bundle.account.snapshot()
    balances_before = dict(account_before.balances)
    used_margin_before = str(vssf.account.used_margin)
    free_margin_before = str(vssf.account.free_margin)
    positions_before = {
        key: dict(value) for key, value in vssf.account.positions.items()
    }
    open_lots_before = bridge.position_lot_store.open_lots()
    result = bridge.execute(plan)
    account_after = bundle.account.snapshot()
    balances_after = dict(account_after.balances)
    used_margin_after = str(vssf.account.used_margin)
    free_margin_after = str(vssf.account.free_margin)
    positions_after = {
        key: dict(value) for key, value in vssf.account.positions.items()
    }
    open_lots_after = bridge.position_lot_store.open_lots()
    approvals = bridge.risk_approval_read_model.for_group(plan.group_id)
    report = result.reports[0]

    case = {
        "diagnostic_status": bridge.risk_diagnostic_status["status"],
        "risk_decision": str(approvals[0].result.decision),
        "risk_approved": approvals[0].result.is_approved,
        "risk_reason": approvals[0].result.rejection_reason,
        "report_status": report.status,
        "report_filled_quantity": report.filled_quantity,
        "report_remaining_quantity": report.remaining_quantity,
        "report_execution_price": str(report.execution_price),
        "report_rejected_reason": report.rejected_reason,
        "result_approved_legs": result.approved_legs,
        "result_routed_legs": result.routed_legs,
        "result_filled_legs": result.filled_legs,
        "router_calls": router.calls,
        "balances_before": balances_before,
        "balances_after": balances_after,
        "balance_delta": {
            key: str(Decimal(str(balances_after.get(key, 0)))
                     - Decimal(str(balances_before.get(key, 0))))
            for key in set(balances_before) | set(balances_after)
        },
        "used_margin_before": used_margin_before,
        "used_margin_after": used_margin_after,
        "free_margin_before": free_margin_before,
        "free_margin_after": free_margin_after,
        "positions_before": positions_before,
        "positions_after": positions_after,
        "open_lots_before": open_lots_before,
        "open_lots_after": open_lots_after,
    }
    if not fail_writer:
        artifacts = list(output_root.glob("*.jsonl"))
        assert len(artifacts) == 1
        lines = artifacts[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["schema_version"] == "strategy5-risk-diagnostic.v1"
        assert record["event_type"] == "GROUP_RISK_PREFLIGHT"
        assert record["provenance"] == {
            "run_id": "isolated-approved-fill-compare",
            "strategy_id": "track5_gap_divergence",
            "group_id": "isolated-approved-fill-group",
        }
        assert record["aggregate"]["decision"] == "ALLOW"
        assert record["legs"][0]["risk_approved"] is True
        case["jsonl_records"] = len(lines)
    else:
        assert not list(output_root.glob("*.jsonl"))
        case["jsonl_records"] = 0

    bundle.shutdown()
    return case


def test_virtual_runtime_diagnostic_storage_failure_does_not_change_approved_fill_or_positions(
    tmp_path: Path,
) -> None:
    success = _run_approved_fill_case(fail_writer=False, output_root=tmp_path / "approved-success")
    failure = _run_approved_fill_case(fail_writer=True, output_root=tmp_path / "approved-failure")

    assert success["diagnostic_status"] == "RECORDED"
    assert failure["diagnostic_status"] == "FAILED"
    assert success["jsonl_records"] == 1
    assert failure["jsonl_records"] == 0

    compared_fields = (
        "risk_decision",
        "risk_approved",
        "risk_reason",
        "report_status",
        "report_filled_quantity",
        "report_remaining_quantity",
        "report_execution_price",
        "report_rejected_reason",
        "result_approved_legs",
        "result_routed_legs",
        "result_filled_legs",
        "router_calls",
        "balances_before",
        "balances_after",
        "balance_delta",
        "used_margin_before",
        "used_margin_after",
        "free_margin_before",
        "free_margin_after",
        "positions_before",
        "positions_after",
        "open_lots_before",
        "open_lots_after",
    )
    assert {field: success[field] for field in compared_fields} == {
        field: failure[field] for field in compared_fields
    }
    assert success["risk_decision"] == "ALLOW"
    assert success["risk_approved"] is True
    assert success["report_status"] == "FILLED"
    assert success["report_filled_quantity"] == 1
    assert success["report_remaining_quantity"] == 0
    assert success["result_approved_legs"] == 1
    assert success["result_routed_legs"] == 1
    assert success["result_filled_legs"] == 1
    assert success["router_calls"] == 1
    assert len(success["open_lots_after"]) == len(failure["open_lots_after"]) == 1
    assert success["positions_after"] == failure["positions_after"]

class _DeterministicStrategy5EntryFixture:
    strategy_id = "track5_gap_divergence"
    version = "test-fixture-v1"

    def initialize(self, _context: Any) -> None:
        return None

    def on_market_state(self, _context: Any) -> None:
        return None

    def evaluate(self, _context: Any):
        from core.strategy.contracts import Signal
        from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

        return (
            Signal(
                strategy_id=self.strategy_id,
                direction="BUY",
                confidence=1.0,
                reason="ISOLATED_TEST_ENTRY",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=1,
                    asset_type="FUTURES",
                    requested_price=Decimal("350"),
                    side="BUY",
                    track_id=self.strategy_id,
                    tag_id="ENTRY",
                ),
            ),
        )

    def reset(self) -> None:
        return None


def _run_automated_loop_approved_fill_case(
    *, fail_writer: bool, output_root: Path
) -> dict[str, Any]:
    from types import SimpleNamespace

    from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
    from application.strategy_hub.hub import StrategyHub
    from contracts.types import CanonicalFuturesQuote
    from core.strategy.registry import StrategyRegistry

    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=master,
        contract_mappings={},
        initial_capital=250_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(
        EnvironmentConfig(
            environment=EnvironmentType.VIRTUAL,
            name="strategy5-risk-diagnostic-automated-loop-isolation-test",
        ),
        RuntimePolicy(allow_live_orders=False),
    )
    bundle.initialize()
    bundle.connect()
    bundle.start()

    registry = StrategyRegistry()
    strategy = _DeterministicStrategy5EntryFixture()
    registry.register(strategy)
    strategy_hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    identity = FuturesInstrumentIdentity(
        "TEST-MINI-2001",
        "TEST-MINI-2001",
        FuturesProductType.MINI,
        Decimal("50000"),
        "ISOLATED_TEST_FIXTURE",
    )
    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle,
        run_id="isolated-automated-loop-approved-fill",
        option_master=master,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
        execution_result_callback=lambda plan, result: strategy_hub.on_execution_result(
            plan.strategy_id, plan.purpose or "", result
        ),
    )
    bridge._strategy5_risk_diagnostic = (
        _FailingWriter() if fail_writer else Strategy5RiskDiagnosticJsonl(output_root)
    )
    router = _CountingRouter(bridge.router)
    bridge.router = router

    observed_at = datetime.now(timezone.utc)
    bundle.market.publish_authoritative_futures_quote(
        CanonicalFuturesQuote(
            instrument_id=identity.instrument_id,
            observed_at=observed_at,
            bid_price=Decimal("350"),
            ask_price=Decimal("350"),
            last_price=Decimal("350"),
            source="DERIVED_SCENARIO_TEST_FIXTURE",
        )
    )

    def context_builder(tick: object, state: object) -> dict[str, object]:
        from core.strategy.contracts import StrategyContext

        return {
            strategy.strategy_id: StrategyContext(
                market_state=state,
                strategy_id=strategy.strategy_id,
            )
        }

    def identity_provider(_evaluation: object, _tick: object):
        return identity

    def multi_leg_plan_resolver(_evaluation: object, _canonical: object):
        return MultiLegExecutionPlan(
            group_id="isolated-automated-loop-approved-fill-group",
            strategy_id=strategy.strategy_id,
            purpose="DIAGNOSTIC_AUTOMATED_LOOP_APPROVED_FILL_TEST",
            legs=(
                ExecutionLeg(
                    leg_id="futures-approved-fill",
                    side="BUY",
                    quantity=1,
                    requested_price=Decimal("350"),
                    position_role="NONE",
                    instrument_identity=identity,
                ),
            ),
        )

    loop = AutomatedVirtualTradingLoop(
        bundle=bundle,
        strategy_hub=strategy_hub,
        run_id="isolated-automated-loop-approved-fill",
        context_builder=context_builder,
        identity_provider=identity_provider,
        multi_leg_plan_resolver=multi_leg_plan_resolver,
        multi_leg_executor=bridge.execute,
        risk_guard_status_source=_AllowedVirtualRiskGuard(),
    )
    loop.multi_leg_bridge = bridge

    tick = SimpleNamespace(
        seq_id=1,
        timestamp=observed_at.isoformat(),
        underlying_price=Decimal("350"),
        ask_price=Decimal("350"),
        volume=1,
    )
    account_before = bundle.account.snapshot()
    balances_before = dict(account_before.balances)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    used_margin_before = str(vssf.account.used_margin)
    free_margin_before = str(vssf.account.free_margin)
    positions_before = {
        key: dict(value) for key, value in vssf.account.positions.items()
    }
    open_lots_before = bridge.position_lot_store.open_lots()

    tick_result = loop.on_tick(tick)

    account_after = bundle.account.snapshot()
    balances_after = dict(account_after.balances)
    positions_after = {
        key: dict(value) for key, value in vssf.account.positions.items()
    }
    open_lots_after = bridge.position_lot_store.open_lots()
    approvals = bridge.risk_approval_read_model.for_group(
        "isolated-automated-loop-approved-fill-group"
    )
    assert len(approvals) == 1
    report = bridge.group_reports(
        "isolated-automated-loop-approved-fill-group"
    )[0]

    case = {
        "diagnostic_status": bridge.risk_diagnostic_status["status"],
        "risk_decision": str(approvals[0].result.decision),
        "risk_approved": approvals[0].result.is_approved,
        "risk_reason": approvals[0].result.rejection_reason,
        "tick_signals": tick_result.signals,
        "tick_approved": tick_result.approved,
        "tick_routed": tick_result.routed,
        "tick_filled": tick_result.filled,
        "tick_rejected": tick_result.rejected,
        "tick_execution_ids_count": len(tick_result.execution_ids),
        "strategy_status": [
            {
                "strategy_id": status.strategy_id,
                "reaction_signals": status.reaction_signals,
                "execution_signals": status.execution_signals,
                "approved": status.approved,
                "routed": status.routed,
                "filled_quantity": status.filled_quantity,
                "risk_rejected": status.risk_rejected,
                "runtime_failures": status.runtime_failures,
            }
            for status in tick_result.strategy_status
        ],
        "report_status": report.status,
        "report_filled_quantity": report.filled_quantity,
        "report_remaining_quantity": report.remaining_quantity,
        "report_execution_price": str(report.execution_price),
        "report_rejected_reason": report.rejected_reason,
        "router_calls": router.calls,
        "balances_before": balances_before,
        "balances_after": balances_after,
        "balance_delta": {
            key: str(Decimal(str(balances_after.get(key, 0)))
                     - Decimal(str(balances_before.get(key, 0)))
            )
            for key in set(balances_before) | set(balances_after)
        },
        "used_margin_before": used_margin_before,
        "used_margin_after": str(vssf.account.used_margin),
        "free_margin_before": free_margin_before,
        "free_margin_after": str(vssf.account.free_margin),
        "positions_before": positions_before,
        "positions_after": positions_after,
        "open_lots_before": open_lots_before,
        "open_lots_after": open_lots_after,
    }
    if not fail_writer:
        artifacts = list(output_root.glob("*.jsonl"))
        assert len(artifacts) == 1
        lines = artifacts[0].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["schema_version"] == "strategy5-risk-diagnostic.v1"
        assert record["event_type"] == "GROUP_RISK_PREFLIGHT"
        assert record["provenance"] == {
            "run_id": "isolated-automated-loop-approved-fill",
            "strategy_id": strategy.strategy_id,
            "group_id": "isolated-automated-loop-approved-fill-group",
        }
        assert record["aggregate"]["decision"] == "ALLOW"
        assert record["legs"][0]["risk_approved"] is True
        case["jsonl_records"] = len(lines)
    else:
        assert not list(output_root.glob("*.jsonl"))
        case["jsonl_records"] = 0

    bundle.shutdown()
    return case


def test_automated_virtual_trading_loop_diagnostic_storage_failure_preserves_approved_fill(
    tmp_path: Path,
) -> None:
    success = _run_automated_loop_approved_fill_case(
        fail_writer=False, output_root=tmp_path / "loop-success"
    )
    failure = _run_automated_loop_approved_fill_case(
        fail_writer=True, output_root=tmp_path / "loop-failure"
    )

    assert success["diagnostic_status"] == "RECORDED"
    assert failure["diagnostic_status"] == "FAILED"
    assert success["jsonl_records"] == 1
    assert failure["jsonl_records"] == 0

    compared_fields = (
        "risk_decision",
        "risk_approved",
        "risk_reason",
        "tick_signals",
        "tick_approved",
        "tick_routed",
        "tick_filled",
        "tick_rejected",
        "tick_execution_ids_count",
        "strategy_status",
        "report_status",
        "report_filled_quantity",
        "report_remaining_quantity",
        "report_execution_price",
        "report_rejected_reason",
        "router_calls",
        "balances_before",
        "balances_after",
        "balance_delta",
        "used_margin_before",
        "used_margin_after",
        "free_margin_before",
        "free_margin_after",
        "positions_before",
        "positions_after",
        "open_lots_before",
        "open_lots_after",
    )
    assert {field: success[field] for field in compared_fields} == {
        field: failure[field] for field in compared_fields
    }
    assert success["risk_decision"] == "ALLOW"
    assert success["risk_approved"] is True
    assert success["tick_signals"] == 1
    assert success["tick_approved"] == 1
    assert success["tick_routed"] == 1
    assert success["tick_filled"] == 1
    assert success["tick_rejected"] == 0
    assert success["report_status"] == "FILLED"
    assert success["report_filled_quantity"] == 1
    assert success["report_remaining_quantity"] == 0
    assert success["router_calls"] == 1
    assert len(success["open_lots_after"]) == len(failure["open_lots_after"]) == 1
