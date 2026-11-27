from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from application.composition.validation_only_s4_runtime_snapshot import (
    ValidationOnlyS4RuntimeSnapshotAdapter,
)


def test_runtime_snapshot_adapter_is_an_explicit_validation_only_seam() -> None:
    assert ValidationOnlyS4RuntimeSnapshotAdapter.RUNTIME_USE == "PROHIBITED_OUTSIDE_VALIDATION"


def test_snapshot_rejects_non_validation_namespaces() -> None:
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_VALIDATION_NAMESPACE_REQUIRED"):
        ValidationOnlyS4RuntimeSnapshotAdapter(source_namespace="KIS:LIVE", account_id="SYNTHETIC:ACCOUNT", execution_source_id="SYNTHETIC:VSSF:ENGINE:001")


def test_snapshot_codec_rejects_unallowlisted_runtime_objects() -> None:
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:S4", execution_source_id="SYNTHETIC:VSSF:ENGINE:001",
    )
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED"):
        adapter.encode_value(object())


def test_snapshot_codec_round_trips_exact_decimal_and_timezone_datetime() -> None:
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:S4", execution_source_id="SYNTHETIC:VSSF:ENGINE:001",
    )
    observed_at = datetime(2026, 11, 27, 1, 2, 3, tzinfo=UTC)
    encoded = adapter.encode_value({"price": Decimal("1000.2500"), "observed_at": observed_at})
    decoded = adapter.decode_value(encoded)
    assert decoded == {"price": Decimal("1000.2500"), "observed_at": observed_at}


def _build_synthetic_bridge(run_id: str, group_id: str, strategy_id: str):
    from application.composition.virtual_multi_leg_execution import (
        VirtualMultiLegExecutionBridge,
    )
    from contracts.track9_position_read_models import (
        Track9InsurancePositionReadModel,
        Track9OptionPositionAttributionReadModel,
    )
    from core.oms.position_group import PositionGroupRegistry
    from environments.virtual.authoritative_vssf.track9_fee_ledger import (
        VirtualTrack9FeeLedger,
    )
    from environments.virtual.position.virtual_position_lot_store import (
        VirtualPositionLotStore,
    )

    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = run_id
    bridge.groups = {}
    bridge.position_groups = PositionGroupRegistry()
    bridge._group_plans = {}
    bridge._track2_entry_progress_disabled_groups = set()
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    bridge.option_position_attribution = Track9OptionPositionAttributionReadModel(bridge.position_lot_store)
    bridge.insurance_position = Track9InsurancePositionReadModel(bridge.position_lot_store)
    bridge.provenance = {}
    bridge.execution_legs = {}
    bridge.leg_positions = {}
    bridge.pending_legs = {}
    bridge._applied_execution_fingerprints = {}
    bridge._s9_retry_schedule = {}
    bridge._s9_retry_attempts = {}
    bridge._pending_attempt_ids = {}
    return bridge


def test_runtime_snapshot_restores_vssf_bridge_and_track4_after_fresh_instances(tmp_path) -> None:
    import json

    from application.composition.validation_only_s4_checkpoint import (
        S4ExecutionEventIdentity,
        S4ExecutionStage,
        SqliteS4ValidationCheckpointStore,
        ValidationOnlyS4CheckpointCoordinator,
    )
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import (
        BrokerOrderCommand,
        ExecutionLeg,
        ExecutionReport,
        MultiLegExecutionPlan,
    )
    from core.oms.position_group import (
        LegStatus,
        PositionGroup,
        PositionGroupLeg,
        PositionGroupSnapshot,
    )
    from core.strategy.track4_gamma_scalping import Track4GammaScalping
    from environments.virtual.authoritative_vssf.canonical import (
        VSSFExecutionFill,
        VSSFOrderResult,
    )
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalOrderCommand,
        CanonicalOrderSide,
    )

    run_id = "SYNTHETIC:S4:RUN:SNAPSHOT-001"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:SNAPSHOT-001"
    group_id = "SYNTHETIC:S4:GROUP:SNAPSHOT-001"
    strategy_id = "track4_gamma_scalping"
    account_id = "SYNTHETIC:S4:ACCOUNT:SNAPSHOT-001"
    source = "SYNTHETIC:DERIVED_SCENARIO"
    stamp = datetime(2026, 11, 27, 1, 2, 3, tzinfo=UTC)
    identity = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC:MINI:SNAPSHOT-001", symbol="SYNTHETIC:MINI:SNAPSHOT-001",
        product_type=FuturesProductType.MINI, contract_multiplier=Decimal(50000), identity_source=source,
    )

    def runtime():
        return VirtualSecuritiesFirmRuntime(
            initial_capital=Decimal(1000000000), validation_run_id=run_id,
            validation_candidate_id=candidate_id,
        )

    def strategy():
        return Track4GammaScalping(
            enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
        )

    original_runtime = runtime()
    account_command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC:ACCOUNT:ORDER:001", track_id=strategy_id,
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=1, price=1000.0, symbol=identity.symbol, strategy_id=strategy_id,
        group_id=group_id, leg_id="mini", instrument_id=identity.instrument_id,
        contract_multiplier=50000.0, identity_source=source,
    )
    account_fill = original_runtime.execution_engine.execute_order(
        account_command, Decimal(1000), 1, timestamp=stamp,
    )
    original_runtime.account.apply_execution(account_fill)
    original_runtime.order_book.add_pending_order(CanonicalOrderCommand(
        client_order_id="SYNTHETIC:ACCOUNT:PENDING:001", track_id=strategy_id,
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.SELL,
        qty=1, price=1001.0, symbol=identity.symbol, strategy_id=strategy_id,
        group_id=group_id, leg_id="mini", instrument_id=identity.instrument_id,
        contract_multiplier=50000.0, identity_source=source,
    ))
    original_runtime._submitted_at["SYNTHETIC:ACCOUNT:PENDING:001"] = stamp
    original_runtime._lifecycle_results["SYNTHETIC:ACCOUNT:PENDING:001"] = VSSFOrderResult(
        client_order_id="SYNTHETIC:ACCOUNT:PENDING:001", status="NEW",
        submitted_at=stamp.isoformat(), observed_at=stamp.isoformat(), remaining_qty=1,
        track_id=strategy_id, asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.SELL, symbol=identity.symbol, group_id=group_id, leg_id="mini",
        execution_fills=(VSSFExecutionFill(
            exec_id=account_fill.exec_id, executed_qty=1, executed_price=Decimal(1000),
            fee=Decimal(0), timestamp=stamp.isoformat(),
        ),),
    )
    original_runtime._market_time = stamp

    original_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    leg = ExecutionLeg(leg_id="mini", side="BUY", quantity=1, instrument_identity=identity)
    plan = MultiLegExecutionPlan(group_id=group_id, strategy_id=strategy_id, legs=(leg,))
    broker_command = BrokerOrderCommand(
        client_order_id="SYNTHETIC:ACCOUNT:ORDER:001", instrument_id=identity.instrument_id,
        side="BUY", quantity=1, order_type="MARKET", instrument_identity=identity,
        asset_type="FUTURES", strategy_id=strategy_id, group_id=group_id,
        leg_id="mini", position_role="NONE",
    )
    bridge_report = ExecutionReport(
        client_order_id=broker_command.client_order_id, broker_order_id="SYNTHETIC:BROKER:001",
        execution_id=account_fill.exec_id, status="FILLED", filled_quantity=1,
        remaining_quantity=0, execution_price=Decimal(1000), execution_timestamp=stamp,
        fee=Decimal("0.25"), group_id=group_id, leg_id="mini",
    )
    original_bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity, broker_command=broker_command, report=bridge_report,
    )
    original_bridge._group_plans[group_id] = plan
    original_bridge.groups[group_id] = [bridge_report]
    original_bridge.position_groups.register(PositionGroup(
        group_id=group_id, strategy_id=strategy_id, direction="MULTI_LEG",
        legs=(PositionGroupLeg(
            leg_id="mini", group_id=group_id, instrument_id=identity.instrument_id,
            side="BUY", quantity=1, contract_multiplier=identity.contract_multiplier,
            identity_source=source, status=LegStatus.FILLED,
        ),),
    ))
    original_bridge.position_groups.update_snapshot(PositionGroupSnapshot(
        group_id=group_id, strategy_id=strategy_id, complete=True, legs=(),
        realized_pnl=Decimal(0), unrealized_pnl=Decimal(0), total_pnl=Decimal(0),
        fees=Decimal("0.25"), slippage=Decimal(0), net_pnl=Decimal("-0.25"),
        quote_freshness_verified=True,
    ))
    original_bridge.pending_legs["SYNTHETIC:BRIDGE:PENDING:001"] = (
        plan,
        PositionGroupLeg(
            leg_id="mini", group_id=group_id, instrument_id=identity.instrument_id,
            side="BUY", quantity=1, contract_multiplier=identity.contract_multiplier,
            identity_source=source, status=LegStatus.PENDING,
        ),
        broker_command,
    )
    original_bridge._pending_attempt_ids["SYNTHETIC:BRIDGE:PENDING:001"] = "SYNTHETIC:ATTEMPT:001"

    original_strategy = strategy()
    original_strategy.state.active_hedge_qty = -1
    original_strategy.state.basecamp_active = True
    original_strategy.state.is_active = True
    original_strategy.state.scalp_high_pnl = Decimal("125.5")
    original_strategy._exit_pending = True
    callback_state = {"callback_sequence": 3, "pending_callback_ids": ["SYNTHETIC:CALLBACK:001"]}

    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id=account_id, execution_source_id="SYNTHETIC:VSSF:ENGINE:SNAPSHOT-001",
    )
    snapshot = adapter.snapshot(
        runtime=original_runtime, bridge=original_bridge, strategy=original_strategy,
        run_id=run_id, strategy_id=strategy_id, group_id=group_id,
        callback_state=callback_state,
    )
    json.dumps(snapshot, sort_keys=True)

    # Persist the composite runtime through the approved append-only stage contract.
    identity_key = S4ExecutionEventIdentity(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id=account_id,
        execution_source_id="SYNTHETIC:VSSF:ENGINE:SNAPSHOT-001", execution_id=account_fill.exec_id,
    )
    event_payload = {
        "run_id": run_id, "strategy_id": strategy_id, "group_id": group_id,
        "fingerprint": "SYNTHETIC:SNAPSHOT:FINGERPRINT:001",
        "client_order_id": account_fill.client_order_id,
        "status": "FILLED", "filled_quantity": 1, "remaining_quantity": 0,
        "execution_timestamp": stamp.isoformat(),
    }
    coordinator = ValidationOnlyS4CheckpointCoordinator(
        SqliteS4ValidationCheckpointStore(tmp_path / "s4-runtime-checkpoint.sqlite3"),
    )
    assert coordinator.receive_execution(identity_key, event_payload) == "RECEIVED"
    previous_checkpoint_id = None
    for revision, stage in enumerate((
        S4ExecutionStage.ACCOUNT_APPLIED, S4ExecutionStage.BRIDGE_APPLIED,
        S4ExecutionStage.CALLBACK_APPLIED, S4ExecutionStage.ACKED,
    ), start=1):
        envelope = adapter.checkpoint_envelope(
            snapshot, identity=identity_key, phase=stage.value,
            checkpoint_id=f"SYNTHETIC:CHECKPOINT:{revision}", revision=revision,
            previous_checkpoint_id=previous_checkpoint_id,
        )
        coordinator.commit_projection(identity_key, stage, envelope)
        previous_checkpoint_id = envelope["checkpoint_id"]
    durable_checkpoint = coordinator.store.load_latest_checkpoint(
        run_id, strategy_id, group_id, account_id,
    )
    assert durable_checkpoint is not None
    assert durable_checkpoint["phase"] == "ACKED"
    assert coordinator.recovery_work() == []
    assert coordinator.receive_execution(identity_key, event_payload) == "ACKED"

    restored_runtime = runtime()
    restored_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    restored_strategy = strategy()
    restored_callbacks = {}
    result = adapter.restore(
        durable_checkpoint, runtime=restored_runtime, bridge=restored_bridge, strategy=restored_strategy,
        run_id=run_id, strategy_id=strategy_id, group_id=group_id,
        callback_state=restored_callbacks,
    )

    assert result["restored"] is True
    assert restored_runtime.account.balance == original_runtime.account.balance
    assert restored_runtime.account.positions == original_runtime.account.positions
    assert restored_runtime.account.ledger_engine.transactions == original_runtime.account.ledger_engine.transactions
    assert restored_runtime.execution_engine._seq == 1
    assert restored_runtime.execution_engine.reports == original_runtime.execution_engine.reports
    assert restored_runtime.order_book.pending_orders() == original_runtime.order_book.pending_orders()
    assert restored_runtime._submitted_at == original_runtime._submitted_at
    assert restored_runtime._lifecycle_results == original_runtime._lifecycle_results
    assert restored_bridge.position_lot_store.open_lots() == original_bridge.position_lot_store.open_lots()
    assert restored_bridge.position_lot_store.history() == original_bridge.position_lot_store.history()
    assert restored_bridge.position_lot_store.close_events() == original_bridge.position_lot_store.close_events()
    assert restored_bridge.fee_ledger.snapshot(run_id=run_id) == original_bridge.fee_ledger.snapshot(run_id=run_id)
    assert restored_bridge._applied_execution_fingerprints == original_bridge._applied_execution_fingerprints
    assert restored_bridge.pending_legs == original_bridge.pending_legs
    assert restored_bridge.position_groups.all() == original_bridge.position_groups.all()
    assert restored_bridge.position_groups.snapshot(group_id) == original_bridge.position_groups.snapshot(group_id)
    assert restored_strategy.state == original_strategy.state
    assert restored_strategy._exit_pending is True
    assert restored_callbacks == callback_state

    # Re-delivery after constructing fresh objects is idempotent in both projections.
    restored_runtime.account.apply_execution(account_fill)
    assert restored_runtime.account.positions == original_runtime.account.positions
    assert len(restored_runtime.account.ledger_engine.transactions) == 1
    restored_bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity, broker_command=broker_command, report=bridge_report,
    )
    assert len(restored_bridge.position_lot_store.history()) == 1
    assert len(restored_bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert restored_bridge.leg_positions[identity.instrument_id].qty == 1


def test_paper_account_duplicate_execution_id_is_idempotent_and_conflict_fails_closed() -> None:
    from dataclasses import replace

    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalOrderCommand,
        CanonicalOrderSide,
    )

    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id="SYNTHETIC:S4:RUN:ACCOUNT-DEDUPE",
        validation_candidate_id="SYNTHETIC:S4:CANDIDATE:ACCOUNT-DEDUPE",
    )
    stamp = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)
    command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC:S4:ORDER:ACCOUNT-DEDUPE", track_id="track4_gamma_scalping",
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=1, price=1000.0, symbol="SYNTHETIC:MINI:ACCOUNT-DEDUPE",
        strategy_id="track4_gamma_scalping", group_id="SYNTHETIC:S4:GROUP:ACCOUNT-DEDUPE",
        leg_id="mini", instrument_id="SYNTHETIC:MINI:ACCOUNT-DEDUPE",
        contract_multiplier=50000.0, identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )
    fill = runtime.execution_engine.execute_order(command, Decimal(1000), 1, timestamp=stamp)
    runtime.account.apply_execution(fill)
    first_position = dict(runtime.account.positions[command.symbol])
    first_balance = runtime.account.balance
    runtime.account.apply_execution(fill)
    assert runtime.account.positions[command.symbol] == first_position
    assert runtime.account.balance == first_balance
    assert len(runtime.account.ledger_engine.transactions) == 1

    conflicting = replace(fill, executed_price=1001.0)
    with pytest.raises(ValueError, match="VSSF_ACCOUNT_EXECUTION_ID_PAYLOAD_CONFLICT"):
        runtime.account.apply_execution(conflicting)
    conflicting_group = replace(fill, group_id="SYNTHETIC:S4:GROUP:OTHER")
    with pytest.raises(ValueError, match="VSSF_ACCOUNT_EXECUTION_ID_PAYLOAD_CONFLICT"):
        runtime.account.apply_execution(conflicting_group)

def test_snapshot_preserves_naive_internal_time_without_promoting_it_to_event_time() -> None:
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:S4",
        execution_source_id="SYNTHETIC:VSSF:ENGINE:001",
    )
    naive_time = datetime.fromisoformat("2026-11-27T09:00:00")
    assert adapter.decode_value(adapter.encode_value(naive_time)) == naive_time


def test_snapshot_rejects_cross_group_bridge_state_before_serialization() -> None:
    from contracts.types import ExecutionLeg, MultiLegExecutionPlan
    from core.strategy.track4_gamma_scalping import Track4GammaScalping
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )

    run_id = "SYNTHETIC:S4:RUN:CROSS-GROUP"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:CROSS-GROUP"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:CROSS-GROUP"
    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000, validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    bridge._group_plans["SYNTHETIC:S4:GROUP:OTHER"] = MultiLegExecutionPlan(
        group_id="SYNTHETIC:S4:GROUP:OTHER", strategy_id=strategy_id,
        legs=(ExecutionLeg(leg_id="mini", side="BUY", quantity=1),),
    )
    strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
    )
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:CROSS-GROUP",
        execution_source_id="SYNTHETIC:VSSF:ENGINE:CROSS-GROUP",
    )
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_GROUP_SCOPE_MISMATCH"):
        adapter.snapshot(
            runtime=runtime, bridge=bridge, strategy=strategy, run_id=run_id,
            strategy_id=strategy_id, group_id=group_id,
        )


def test_restore_rejects_strategy_configuration_drift_before_mutating_runtime() -> None:
    from core.strategy.track4_gamma_scalping import Track4GammaScalping
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )

    run_id = "SYNTHETIC:S4:RUN:CONFIG-DRIFT"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:CONFIG-DRIFT"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:CONFIG-DRIFT"
    original_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000, validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    original_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    original_strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
    )
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:CONFIG-DRIFT",
        execution_source_id="SYNTHETIC:VSSF:ENGINE:CONFIG-DRIFT",
    )
    snapshot = adapter.snapshot(
        runtime=original_runtime, bridge=original_bridge, strategy=original_strategy,
        run_id=run_id, strategy_id=strategy_id, group_id=group_id,
    )
    target_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000, validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    target_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    target_strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal(2000), risk_limits_available=True,
    )
    original_balance = target_runtime.account.balance
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_STRATEGY_CONFIG_MISMATCH"):
        adapter.restore(
            snapshot, runtime=target_runtime, bridge=target_bridge, strategy=target_strategy,
            run_id=run_id, strategy_id=strategy_id, group_id=group_id,
        )
    assert target_runtime.account.balance == original_balance
    assert target_bridge.position_lot_store.history() == ()


def test_checkpoint_envelope_rejects_execution_source_owner_change() -> None:
    from application.composition.validation_only_s4_checkpoint import (
        S4ExecutionEventIdentity,
    )

    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:OWNER",
        execution_source_id="SYNTHETIC:VSSF:ENGINE:OWNER-A",
    )
    identity = S4ExecutionEventIdentity(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id="SYNTHETIC:ACCOUNT:OWNER",
        execution_source_id="SYNTHETIC:VSSF:ENGINE:OWNER-B", execution_id="SYNTHETIC:EXEC:OWNER",
    )
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_CHECKPOINT_IDENTITY_MISMATCH"):
        adapter.checkpoint_envelope(
            {"runtime_use": adapter.RUNTIME_USE}, identity=identity,
            phase="ACCOUNT_APPLIED", checkpoint_id="SYNTHETIC:CP:OWNER",
            revision=1, previous_checkpoint_id=None,
        )


def test_legacy_account_ledger_without_payload_fingerprint_fails_closed() -> None:
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalOrderCommand,
        CanonicalOrderSide,
    )

    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id="SYNTHETIC:S4:RUN:LEGACY-LEDGER",
        validation_candidate_id="SYNTHETIC:S4:CANDIDATE:LEGACY-LEDGER",
    )
    stamp = datetime(2026, 11, 27, 3, 0, tzinfo=UTC)
    command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC:S4:ORDER:LEGACY-LEDGER", track_id="track4_gamma_scalping",
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=1, price=1000.0, symbol="SYNTHETIC:MINI:LEGACY-LEDGER",
        strategy_id="track4_gamma_scalping", group_id="SYNTHETIC:S4:GROUP:LEGACY-LEDGER",
        leg_id="mini", instrument_id="SYNTHETIC:MINI:LEGACY-LEDGER",
        contract_multiplier=50000.0, identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )
    fill = runtime.execution_engine.execute_order(command, Decimal(1000), 1, timestamp=stamp)
    runtime.account.ledger_engine.transactions.append({"exec_id": fill.exec_id})
    with pytest.raises(ValueError, match="VSSF_ACCOUNT_EXECUTION_IDENTITY_UNVERIFIABLE"):
        runtime.account.apply_execution(fill)
    assert runtime.account.positions == {}

def test_runtime_partial_stage_restart_resumes_bridge_without_reapplying_account(tmp_path) -> None:
    from application.composition.validation_only_s4_checkpoint import (
        S4ExecutionEventIdentity,
        S4ExecutionStage,
        SqliteS4ValidationCheckpointStore,
        ValidationOnlyS4CheckpointCoordinator,
    )
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import (
        BrokerOrderCommand,
        ExecutionLeg,
        ExecutionReport,
        MultiLegExecutionPlan,
    )
    from core.strategy.track4_gamma_scalping import Track4GammaScalping
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalOrderCommand,
        CanonicalOrderSide,
    )

    run_id = "SYNTHETIC:S4:RUN:PARTIAL-RESTART"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:PARTIAL-RESTART"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:PARTIAL-RESTART"
    account_id = "SYNTHETIC:S4:ACCOUNT:PARTIAL-RESTART"
    namespace = "SYNTHETIC:S4:SNAPSHOT"
    source_id = "SYNTHETIC:VSSF:ENGINE:PARTIAL-RESTART"
    source = "SYNTHETIC:DERIVED_SCENARIO"
    stamp = datetime(2026, 11, 27, 4, 0, tzinfo=UTC)
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace=namespace, account_id=account_id, execution_source_id=source_id,
    )

    def make_runtime():
        return VirtualSecuritiesFirmRuntime(
            initial_capital=1_000_000_000, validation_run_id=run_id,
            validation_candidate_id=candidate_id,
        )

    def make_strategy():
        return Track4GammaScalping(
            enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
        )

    identity = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC:MINI:PARTIAL-RESTART",
        symbol="SYNTHETIC:MINI:PARTIAL-RESTART", product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal(50000), identity_source=source,
    )
    command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC:S4:ORDER:PARTIAL-RESTART", track_id=strategy_id,
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=1, price=1000.0, symbol=identity.symbol, strategy_id=strategy_id,
        group_id=group_id, leg_id="mini", instrument_id=identity.instrument_id,
        contract_multiplier=50000.0, identity_source=source,
    )
    runtime_before_restart = make_runtime()
    fill = runtime_before_restart.execution_engine.execute_order(command, Decimal(1000), 1, timestamp=stamp)
    runtime_before_restart.account.apply_execution(fill)
    bridge_before_restart = _build_synthetic_bridge(run_id, group_id, strategy_id)
    strategy_before_restart = make_strategy()
    callbacks = {}
    account_snapshot = adapter.snapshot(
        runtime=runtime_before_restart, bridge=bridge_before_restart,
        strategy=strategy_before_restart, run_id=run_id, strategy_id=strategy_id,
        group_id=group_id, callback_state=callbacks,
    )

    event_identity = S4ExecutionEventIdentity(
        source_namespace=namespace, account_id=account_id,
        execution_source_id=source_id, execution_id=fill.exec_id,
    )
    event_payload = {
        "run_id": run_id, "strategy_id": strategy_id, "group_id": group_id,
        "fingerprint": "SYNTHETIC:PARTIAL-RESTART:FINGERPRINT",
        "client_order_id": fill.client_order_id, "status": "FILLED",
        "filled_quantity": 1, "remaining_quantity": 0,
        "execution_timestamp": stamp.isoformat(),
    }
    coordinator = ValidationOnlyS4CheckpointCoordinator(
        SqliteS4ValidationCheckpointStore(tmp_path / "partial-stage.sqlite3"),
    )
    assert coordinator.receive_execution(event_identity, event_payload) == "RECEIVED"
    account_checkpoint = adapter.checkpoint_envelope(
        account_snapshot, identity=event_identity, phase=S4ExecutionStage.ACCOUNT_APPLIED.value,
        checkpoint_id="SYNTHETIC:PARTIAL:CP:1", revision=1, previous_checkpoint_id=None,
    )
    coordinator.commit_projection(event_identity, S4ExecutionStage.ACCOUNT_APPLIED, account_checkpoint)

    # New runtime objects represent a restart after ACCOUNT_APPLIED.
    runtime_after_restart = make_runtime()
    bridge_after_restart = _build_synthetic_bridge(run_id, group_id, strategy_id)
    strategy_after_restart = make_strategy()
    restored_callbacks = {}
    adapter.restore(
        account_checkpoint, runtime=runtime_after_restart, bridge=bridge_after_restart,
        strategy=strategy_after_restart, run_id=run_id, strategy_id=strategy_id,
        group_id=group_id, callback_state=restored_callbacks,
    )
    recovery = coordinator.recovery_work()
    assert len(recovery) == 1 and recovery[0]["next_stage"] == "BRIDGE_APPLIED"
    runtime_after_restart.account.apply_execution(fill)
    assert len(runtime_after_restart.account.ledger_engine.transactions) == 1

    leg = ExecutionLeg(leg_id="mini", side="BUY", quantity=1, instrument_identity=identity)
    plan = MultiLegExecutionPlan(group_id=group_id, strategy_id=strategy_id, legs=(leg,))
    broker_command = BrokerOrderCommand(
        client_order_id=fill.client_order_id, instrument_id=identity.instrument_id,
        side="BUY", quantity=1, order_type="MARKET", instrument_identity=identity,
        asset_type="FUTURES", strategy_id=strategy_id, group_id=group_id,
        leg_id="mini", position_role="NONE",
    )
    report = ExecutionReport(
        client_order_id=fill.client_order_id, broker_order_id="SYNTHETIC:BROKER:PARTIAL-RESTART",
        execution_id=fill.exec_id, status="FILLED", filled_quantity=1, remaining_quantity=0,
        execution_price=Decimal(1000), execution_timestamp=stamp, fee=Decimal("0.1"),
        group_id=group_id, leg_id="mini",
    )
    bridge_after_restart._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity, broker_command=broker_command, report=report,
    )
    bridge_snapshot = adapter.snapshot(
        runtime=runtime_after_restart, bridge=bridge_after_restart,
        strategy=strategy_after_restart, run_id=run_id, strategy_id=strategy_id,
        group_id=group_id, callback_state=restored_callbacks,
    )
    bridge_checkpoint = adapter.checkpoint_envelope(
        bridge_snapshot, identity=event_identity, phase=S4ExecutionStage.BRIDGE_APPLIED.value,
        checkpoint_id="SYNTHETIC:PARTIAL:CP:2", revision=2,
        previous_checkpoint_id=account_checkpoint["checkpoint_id"],
    )
    coordinator.commit_projection(event_identity, S4ExecutionStage.BRIDGE_APPLIED, bridge_checkpoint)

    restored_callbacks["callback_sequence"] = 1
    callback_snapshot = adapter.snapshot(
        runtime=runtime_after_restart, bridge=bridge_after_restart,
        strategy=strategy_after_restart, run_id=run_id, strategy_id=strategy_id,
        group_id=group_id, callback_state=restored_callbacks,
    )
    callback_checkpoint = adapter.checkpoint_envelope(
        callback_snapshot, identity=event_identity, phase=S4ExecutionStage.CALLBACK_APPLIED.value,
        checkpoint_id="SYNTHETIC:PARTIAL:CP:3", revision=3,
        previous_checkpoint_id=bridge_checkpoint["checkpoint_id"],
    )
    coordinator.commit_projection(event_identity, S4ExecutionStage.CALLBACK_APPLIED, callback_checkpoint)
    ack_checkpoint = adapter.checkpoint_envelope(
        callback_snapshot, identity=event_identity, phase=S4ExecutionStage.ACKED.value,
        checkpoint_id="SYNTHETIC:PARTIAL:CP:4", revision=4,
        previous_checkpoint_id=callback_checkpoint["checkpoint_id"],
    )
    coordinator.commit_projection(event_identity, S4ExecutionStage.ACKED, ack_checkpoint)

    final_runtime = make_runtime()
    final_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    final_strategy = make_strategy()
    final_callbacks = {}
    adapter.restore(
        coordinator.store.load_latest_checkpoint(run_id, strategy_id, group_id, account_id),
        runtime=final_runtime, bridge=final_bridge, strategy=final_strategy,
        run_id=run_id, strategy_id=strategy_id, group_id=group_id,
        callback_state=final_callbacks,
    )
    final_runtime.account.apply_execution(fill)
    final_bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity, broker_command=broker_command, report=report,
    )
    assert len(final_runtime.account.ledger_engine.transactions) == 1
    assert len(final_bridge.position_lot_store.history()) == 1
    assert len(final_bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert final_callbacks == {"callback_sequence": 1}
    assert coordinator.recovery_work() == []


def test_restore_rejects_execution_watermark_drift_before_mutating_runtime() -> None:
    from core.strategy.track4_gamma_scalping import Track4GammaScalping
    from environments.virtual.authoritative_vssf.firm_runtime import (
        VirtualSecuritiesFirmRuntime,
    )
    from shared.contracts.canonical import (
        CanonicalAssetType,
        CanonicalOrderCommand,
        CanonicalOrderSide,
    )

    run_id = "SYNTHETIC:S4:RUN:WATERMARK-DRIFT"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:WATERMARK-DRIFT"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:WATERMARK-DRIFT"
    account_id = "SYNTHETIC:S4:ACCOUNT:WATERMARK-DRIFT"
    source_id = "SYNTHETIC:VSSF:ENGINE:WATERMARK-DRIFT"
    original_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000, validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC:S4:ORDER:WATERMARK-DRIFT", track_id=strategy_id,
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=1, price=1000.0, symbol="SYNTHETIC:MINI:WATERMARK-DRIFT",
        strategy_id=strategy_id, group_id=group_id, leg_id="mini",
        instrument_id="SYNTHETIC:MINI:WATERMARK-DRIFT", contract_multiplier=50000.0,
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )
    fill = original_runtime.execution_engine.execute_order(
        command, Decimal(1000), 1, timestamp=datetime(2026, 11, 27, 5, 0, tzinfo=UTC),
    )
    original_runtime.account.apply_execution(fill)
    original_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    original_strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
    )
    adapter = ValidationOnlyS4RuntimeSnapshotAdapter(
        source_namespace="SYNTHETIC:S4:SNAPSHOT", account_id=account_id,
        execution_source_id=source_id,
    )
    snapshot = adapter.snapshot(
        runtime=original_runtime, bridge=original_bridge, strategy=original_strategy,
        run_id=run_id, strategy_id=strategy_id, group_id=group_id,
    )
    watermarks = adapter.decode_value(snapshot["execution_watermarks"])
    watermarks["account_execution_ids"] = ()
    snapshot["execution_watermarks"] = adapter.encode_value(watermarks)

    target_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000, validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    target_bridge = _build_synthetic_bridge(run_id, group_id, strategy_id)
    target_strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal(1000), risk_limits_available=True,
    )
    with pytest.raises(ValueError, match="S4_RUNTIME_SNAPSHOT_EXECUTION_WATERMARK_MISMATCH"):
        adapter.restore(
            snapshot, runtime=target_runtime, bridge=target_bridge, strategy=target_strategy,
            run_id=run_id, strategy_id=strategy_id, group_id=group_id,
        )
    assert target_runtime.account.ledger_engine.transactions == []
    assert target_bridge.position_lot_store.history() == ()
