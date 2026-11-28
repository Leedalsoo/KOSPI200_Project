from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.validation_only_track7_execution import S7ValidationOnlyRuntimeAdapter
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote
from tests.core.test_track7_aggregate_snapshot_contract import _capture_aggregate, _restore_aggregate

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"


def _proposal(tag_id: str, option_type: str, strike: Decimal, *, side: str = "BUY"):
    return StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        side=side,
        track_id="track7_volatility_skew_weekly_insurance",
        tag_id=tag_id,
        option_type=option_type,
        strike=strike,
    )


def _track7_read_only_lineage_mismatches(
    *,
    expected_run_id: str,
    expected_group_id: str,
    expected_expiry: str,
    aggregate_group_id: str,
    aggregate_expiry: str,
    pending_records: tuple[tuple[str, str, str, str, str], ...],
    position_records: tuple[tuple[str, str, str, str], ...],
    fee_records: tuple[tuple[str, str, str], ...],
) -> tuple[str, ...]:
    """Test-side read-only identity audit; it never receives mutable stores."""
    mismatches: set[str] = set()
    if aggregate_group_id != expected_group_id:
        mismatches.add("aggregate_group_mismatch")
    if aggregate_expiry != expected_expiry:
        mismatches.add("aggregate_expiry_mismatch")

    if not pending_records:
        mismatches.add("pending_projection_missing")
    if len(pending_records) > 1:
        mismatches.add("pending_projection_duplicate")
    for plan_group, leg_id, command_group, command_leg, expiry in pending_records:
        if plan_group != expected_group_id or command_group != expected_group_id:
            mismatches.add("pending_group_mismatch")
        if leg_id != command_leg:
            mismatches.add("pending_leg_mismatch")
        if expiry != expected_expiry:
            mismatches.add("pending_expiry_mismatch")

    if not position_records:
        mismatches.add("position_projection_missing")
    if len(position_records) > 1:
        mismatches.add("position_projection_duplicate")
    for run_id, group_id, expiry, _execution_id in position_records:
        if run_id != expected_run_id:
            mismatches.add("position_run_mismatch")
        if group_id != expected_group_id:
            mismatches.add("position_group_mismatch")
        if expiry != expected_expiry:
            mismatches.add("position_expiry_mismatch")

    if not fee_records:
        mismatches.add("fee_projection_missing")
    if len(fee_records) > 1:
        mismatches.add("fee_projection_duplicate")
    for run_id, group_id, _execution_id in fee_records:
        if run_id != expected_run_id:
            mismatches.add("fee_run_mismatch")
        if group_id != expected_group_id:
            mismatches.add("fee_group_mismatch")
    if {record[3] for record in position_records} != {record[2] for record in fee_records}:
        mismatches.add("fee_execution_lineage_mismatch")

    if len({record[3] for record in position_records}) != len(position_records):
        mismatches.add("position_execution_duplicate")
    if len({record[2] for record in fee_records}) != len(fee_records):
        mismatches.add("fee_execution_duplicate")
    return tuple(sorted(mismatches))


def test_s7_pending_call_reconciliation_keeps_original_expiry_after_market_tick_rolls():
    replay_adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=replay_adapter)
    ticks = list(HighSpeedReplayRunner(DATASET, synthetic_adapter=replay_adapter).events())
    put_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261112" and str(tick.option_type).upper() == "PUT"
    )
    call_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261112"
        and tick.timestamp == put_tick.timestamp
        and str(tick.option_type).upper() == "CALL"
    )
    other_expiry_tick = next(
        tick for tick in ticks
        if tick.expiry == "20261109"
        and str(tick.option_type).upper() == "PUT"
        and tick.timestamp == put_tick.timestamp
    )

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    s7_adapter = S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET, manifest_path=MANIFEST,
        risk_profile_path=ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json",
    )
    s7_adapter.bind_run_id("Q25-S7-PENDING-IDENTITY-RECONCILIATION")
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("track7_volatility_skew_weekly_insurance", "1.0"),),
        run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
        validation_only_s7_runtime_adapter=s7_adapter,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    strategy = loop.strategy_hub._orchestrator._registry.get(
        "track7_volatility_skew_weekly_insurance", "1.0",
    )
    strategy._activate_expiry("20261112")
    strategy.state = strategy.state.__class__(
        entry_pending=True,
        expiry="20261112",
        put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        entry_stage="PUT_READY",
    )
    _publish_contract_scoped_replay_quote(
        put_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    _publish_contract_scoped_replay_quote(
        call_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    sources.set_tick(call_tick)
    bootstrap.bundle.market.publish_replay_tick(put_tick)
    bootstrap.bundle.market.publish_replay_tick(call_tick)

    put_plan = strategy.build_execution_plan(
        "Q25-S7-PENDING-IDENTITY-GROUP",
        proposal=_proposal("WEEKLY_INSURANCE_ENTRY_PUT", "PUT", Decimal("487.5")),
    )
    put_result = bridge.execute(put_plan)
    assert put_result.reports[0].status == "FILLED"
    assert strategy.state.entry_stage == "CALL_READY"

    call_plan = strategy.build_execution_plan(
        "IGNORED-CALL-GROUP-ID",
        proposal=_proposal("WEEKLY_INSURANCE_ENTRY_CALL", "CALL", Decimal("512.5")),
    )
    pending_limit = Decimal(str(call_tick.bid_price)) - Decimal("1.00")
    call_plan = replace(
        call_plan,
        legs=(replace(call_plan.legs[0], requested_price=pending_limit),),
    )
    call_result = bridge.execute(call_plan)
    assert call_result.reports[0].status == "NEW"
    assert call_result.pending_legs == 1
    assert strategy.state.entry_stage == "CALL_PENDING"

    # The factory callback correlates the pending Bridge order and the
    # already-filled PUT PositionLot without releasing the group reservation.
    assert set(s7_adapter._reserved[call_plan.group_id]) == {"put", "call"}
    assert len(bridge.pending_legs) == 1
    pending_lots = [lot for lot in bridge.position_lot_store.open_lots()
                    if lot.run_id == "Q25-S7-PENDING-IDENTITY-RECONCILIATION"
                    and lot.group_id == call_plan.group_id]
    assert len(pending_lots) == 1
    pending_fees = bridge.fee_ledger.snapshot(run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION")
    assert len(pending_fees) == 1
    assert pending_fees[0].execution_id == pending_lots[0].execution_id
    assert pending_fees[0].group_id == pending_lots[0].group_id == call_plan.group_id

    # Restore the Track7 aggregate snapshot while the matching Bridge projections
    # are still live, then correlate all records read-only by run/group/expiry.
    aggregate_envelope = _capture_aggregate(strategy)
    restored_strategy, restore_gate = _restore_aggregate(aggregate_envelope)
    restored_expiry = restored_strategy._group_expiry[call_plan.group_id]
    restored_group_state = restored_strategy._states_by_expiry[restored_expiry]
    assert restore_gate == {"state_restored": True, "side_effect_actions_allowed": True}
    assert restored_expiry == "20261112"
    assert restored_group_state.entry_pending is True
    assert restored_group_state.entry_stage == "CALL_PENDING"
    assert restored_group_state.entry_group_id == call_plan.group_id

    pending_client_order_id = call_result.reports[0].client_order_id
    pending_group_plan, pending_leg, pending_command = bridge.pending_legs[pending_client_order_id]
    assert pending_group_plan.group_id == call_plan.group_id
    assert pending_leg.leg_id == pending_command.leg_id == "call"
    assert pending_command.group_id == call_plan.group_id
    assert pending_leg.instrument_identity.expiry == restored_expiry
    assert {lot.run_id for lot in pending_lots} == {"Q25-S7-PENDING-IDENTITY-RECONCILIATION"}
    assert {lot.group_id for lot in pending_lots} == {call_plan.group_id}
    assert {lot.instrument_identity.expiry for lot in pending_lots} == {restored_expiry}
    assert {row.run_id for row in pending_fees} == {"Q25-S7-PENDING-IDENTITY-RECONCILIATION"}
    assert {row.group_id for row in pending_fees} == {call_plan.group_id}
    assert {row.execution_id for row in pending_fees} == {lot.execution_id for lot in pending_lots}
    assert len(bridge.pending_legs) == 1

    # Read-only mismatch characterization: the audit receives immutable scalar
    # projections, not the Bridge stores, aggregate object, or reservation maps.
    pending_records = tuple(
        (plan.group_id, leg.leg_id, command.group_id, command.leg_id, leg.instrument_identity.expiry)
        for plan, leg, command in bridge.pending_legs.values()
    )
    position_records = tuple(
        (lot.run_id, lot.group_id, lot.instrument_identity.expiry, lot.execution_id)
        for lot in pending_lots
    )
    fee_records = tuple((row.run_id, row.group_id, row.execution_id) for row in pending_fees)
    projections_before = (pending_records, position_records, fee_records)
    audit_args = {
        "expected_run_id": "Q25-S7-PENDING-IDENTITY-RECONCILIATION",
        "expected_group_id": call_plan.group_id,
        "expected_expiry": restored_expiry,
        "aggregate_group_id": restored_group_state.entry_group_id,
        "aggregate_expiry": restored_expiry,
        "pending_records": pending_records,
        "position_records": position_records,
        "fee_records": fee_records,
    }
    assert _track7_read_only_lineage_mismatches(**audit_args) == ()

    # Exercise the remaining provenance dimensions independently. These are
    # deliberately synthetic input mutations; live Bridge/aggregate objects
    # remain untouched.
    assert "aggregate_group_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "aggregate_group_id": "WRONG-GROUP"}
    )
    assert "aggregate_expiry_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "aggregate_expiry": "20261109"}
    )
    bad_pending_leg = ((pending_records[0][0], "WRONG-LEG", pending_records[0][2],
                        pending_records[0][3], pending_records[0][4]),)
    assert "pending_leg_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "pending_records": bad_pending_leg}
    )
    bad_pending_expiry = ((pending_records[0][0], pending_records[0][1],
                           pending_records[0][2], pending_records[0][3], "20261109"),)
    assert "pending_expiry_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "pending_records": bad_pending_expiry}
    )
    bad_position_run = (("WRONG-RUN", position_records[0][1],
                         position_records[0][2], position_records[0][3]),)
    assert "position_run_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "position_records": bad_position_run}
    )
    bad_position_expiry = ((position_records[0][0], position_records[0][1],
                            "20261109", position_records[0][3]),)
    assert "position_expiry_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "position_records": bad_position_expiry}
    )
    bad_fee_run = (("WRONG-RUN", fee_records[0][1], fee_records[0][2]),)
    assert "fee_run_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "fee_records": bad_fee_run}
    )
    bad_fee_group = ((fee_records[0][0], "WRONG-GROUP", fee_records[0][2]),)
    assert "fee_group_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "fee_records": bad_fee_group}
    )

    bad_pending = ((pending_records[0][0], pending_records[0][1], "WRONG-GROUP",
                    pending_records[0][3], pending_records[0][4]),)
    assert "pending_group_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "pending_records": bad_pending}
    )
    bad_position = ((position_records[0][0], "WRONG-GROUP",
                     position_records[0][2], position_records[0][3]),)
    assert "position_group_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "position_records": bad_position}
    )
    bad_fee = ((fee_records[0][0], fee_records[0][1], "WRONG-EXECUTION"),)
    assert "fee_execution_lineage_mismatch" in _track7_read_only_lineage_mismatches(
        **{**audit_args, "fee_records": bad_fee}
    )
    missing = _track7_read_only_lineage_mismatches(
        **{**audit_args, "pending_records": (), "position_records": (), "fee_records": ()}
    )
    assert {"pending_projection_missing", "position_projection_missing",
            "fee_projection_missing"}.issubset(missing)
    duplicated = _track7_read_only_lineage_mismatches(
        **{**audit_args, "pending_records": pending_records * 2,
           "position_records": position_records * 2, "fee_records": fee_records * 2}
    )
    assert {"pending_projection_duplicate", "position_projection_duplicate",
            "fee_projection_duplicate", "position_execution_duplicate",
            "fee_execution_duplicate"}.issubset(duplicated)
    assert (pending_records, position_records, fee_records) == projections_before
    assert len(bridge.pending_legs) == 1
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=audit_args["expected_run_id"])) == 1
    assert restored_group_state.entry_group_id == call_plan.group_id
    # A same-run adapter reconstruction at the partial-position + pending-order
    # boundary has no supported way to hydrate the active group's reservations.
    reconstructed_pending_adapter = S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET,
        manifest_path=MANIFEST,
        risk_profile_path=ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json",
    )
    reconstructed_pending_adapter.bind_run_id("Q25-S7-PENDING-IDENTITY-RECONCILIATION")
    assert len(bridge.pending_legs) == 1
    assert len(pending_lots) == 1
    assert len(pending_fees) == 1
    assert reconstructed_pending_adapter._reserved == {}
    assert reconstructed_pending_adapter._reserved_entry_fees == {}
    assert reconstructed_pending_adapter._group_expiry_by_id == {}
    assert set(s7_adapter._reserved[call_plan.group_id]) == {"put", "call"}

    client_order_id = call_result.reports[0].client_order_id
    stored_group_plan, stored_leg, stored_command = bridge.pending_legs[client_order_id]
    assert stored_command.client_order_id == client_order_id
    assert stored_group_plan.group_id == call_plan.group_id
    assert stored_leg.leg_id == "call"
    assert stored_command.group_id == call_plan.group_id
    assert stored_command.leg_id == "call"
    assert stored_leg.instrument_identity.expiry == "20261112"
    assert {
        leg.instrument_identity.expiry for leg in stored_group_plan.legs
    } == {"20261112"}

    # A later event for the other weekly expiry must not rebind the pending CALL.
    bootstrap.bundle.market.publish_replay_tick(other_expiry_tick)
    assert bootstrap.bundle.market.last_tick.expiry == "20261109"

    improved_call_tick = replace(
        call_tick,
        timestamp=(datetime.fromisoformat(call_tick.timestamp).replace(microsecond=0)
                   + timedelta(seconds=1)).isoformat(),
        bid_price=float(pending_limit - Decimal("0.01")),
        ask_price=float(pending_limit),
        last_price=float(pending_limit),
    )
    _publish_contract_scoped_replay_quote(
        improved_call_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    vssf.process_market_data(improved_call_tick)

    reconciled = bridge.process_pending_quotes()
    assert len(reconciled) == 1
    final = reconciled[0]
    assert final.group_complete is True
    assert final.pending_legs == 0
    assert final.reports[-1].client_order_id == client_order_id
    assert final.reports[-1].status == "FILLED"
    assert final.reports[-1].execution_id
    assert all(report.status != "REJECTED" for report in bridge.group_reports(call_plan.group_id))
    assert len(bridge.pending_legs) == 0
    assert strategy.state.entry_stage == "COMPLETE"
    assert strategy.state.insurance_active is True
    assert strategy.state.put_open is True
    assert strategy.state.call_open is True

    open_lots = bridge.position_lot_store.open_lots()
    assert len(open_lots) == 2
    assert {lot.instrument_identity.expiry for lot in open_lots} == {"20261112"}
    fee_rows = bridge.fee_ledger.snapshot(run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION")
    assert len(fee_rows) == 2
    assert {row.execution_id for row in fee_rows} == {lot.execution_id for lot in open_lots}
    assert {row.group_id for row in fee_rows} == {call_plan.group_id}
    assert {lot.group_id for lot in open_lots} == {call_plan.group_id}
    assert {lot.run_id for lot in open_lots} == {"Q25-S7-PENDING-IDENTITY-RECONCILIATION"}
    assert set(s7_adapter._reserved[call_plan.group_id]) == {"put", "call"}
    assert s7_adapter._reserved_entry_fees[call_plan.group_id]
    assert s7_adapter._group_expiry_by_id[call_plan.group_id] == "20261112"

    # Cross-store restart boundary: reconstructing only the validation adapter
    # with the same run ID cannot infer reservations from live Bridge projections.
    reconstructed_adapter = S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET,
        manifest_path=MANIFEST,
        risk_profile_path=ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json",
    )
    reconstructed_adapter.bind_run_id("Q25-S7-PENDING-IDENTITY-RECONCILIATION")
    assert len(bridge.position_lot_store.open_lots()) == 2
    assert len(bridge.fee_ledger.snapshot(run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION")) == 2
    assert reconstructed_adapter._reserved == {}
    assert reconstructed_adapter._reserved_entry_fees == {}
    assert reconstructed_adapter._group_expiry_by_id == {}
    # No restore policy is implied: original adapter still owns the live
    # in-process reservation and the reconstructed adapter remains unhydrated.
    assert set(s7_adapter._reserved[call_plan.group_id]) == {"put", "call"}
    snapshot = bridge.position_groups.snapshot(call_plan.group_id)
    assert snapshot is not None
    assert {leg.instrument_id for leg in snapshot.legs} == {
        "SYNTHETIC_CONTRACT:strategy7_weekly:20261112:PUT:487.5",
        "SYNTHETIC_CONTRACT:strategy7_weekly:20261112:CALL:512.5",
    }

    # Refresh both contract-scoped quotes for the terminal close preflight.
    for offset, source_tick in enumerate((put_tick, improved_call_tick), start=2):
        close_tick = replace(
            source_tick,
            timestamp=(datetime.fromisoformat(improved_call_tick.timestamp)
                       + timedelta(seconds=2)).isoformat(),
            seq_id=int(source_tick.seq_id) + 1000 + offset,
        )
        _publish_contract_scoped_replay_quote(
            close_tick,
            option_master=master,
            market=bootstrap.bundle.market,
            order_book=vssf.order_book,
        )
        sources.set_tick(close_tick)
        bootstrap.bundle.market.publish_replay_tick(close_tick)
        vssf.process_market_data(close_tick)

    # Terminal close must release only after both PositionLots are flat and
    # Bridge reports no pending order; the factory callback owns this path.
    close_plan = strategy.build_execution_plan(
        call_plan.group_id,
        proposal=_proposal(
            "WEEKLY_INSURANCE_CLOSE", "PUT", Decimal("487.5"), side="SELL",
        ),
    )
    close_result = bridge.execute(close_plan)
    assert close_result.group_complete is True
    assert close_result.position_flat is True
    assert close_result.pending_legs == 0
    assert all(report.status == "FILLED" for report in close_result.reports)
    assert len(bridge.position_lot_store.open_lots()) == 0
    assert len(bridge.pending_legs) == 0
    assert call_plan.group_id not in s7_adapter._reserved
    assert call_plan.group_id not in s7_adapter._reserved_entry_fees
    assert call_plan.group_id not in s7_adapter._group_expiry_by_id

    # Re-delivery of the same terminal callback must leave the released group
    # unchanged; this is an in-process duplicate-delivery characterization only.
    bridge.execution_result_callback(close_plan, close_result)
    bridge.execution_result_callback(close_plan, close_result)
    assert call_plan.group_id not in s7_adapter._reserved
    assert call_plan.group_id not in s7_adapter._reserved_entry_fees
    assert call_plan.group_id not in s7_adapter._group_expiry_by_id
    assert len(bridge.fee_ledger.snapshot(run_id="Q25-S7-PENDING-IDENTITY-RECONCILIATION")) == 4


def test_s7_read_only_lineage_audit_keeps_two_group_expiries_and_executions_isolated():
    expected_expiries = {
        "GROUP-A": "20261112",
        "GROUP-B": "20261119",
    }
    aggregate_records = (
        ("GROUP-A", "20261112"),
        ("GROUP-B", "20261119"),
    )
    pending_records = (
        ("GROUP-A", "put", "GROUP-A", "put", "20261112"),
        ("GROUP-B", "call", "GROUP-B", "call", "20261119"),
    )
    position_records = (
        ("RUN-MULTI", "GROUP-A", "20261112", "EXEC-A"),
        ("RUN-MULTI", "GROUP-B", "20261119", "EXEC-B"),
    )
    fee_records = (
        ("RUN-MULTI", "GROUP-A", "EXEC-A"),
        ("RUN-MULTI", "GROUP-B", "EXEC-B"),
    )

    assert _track7_multi_group_read_only_lineage_mismatches(
        expected_run_id="RUN-MULTI",
        expected_expiries=expected_expiries,
        aggregate_records=aggregate_records,
        pending_records=pending_records,
        position_records=position_records,
        fee_records=fee_records,
    ) == ()

    crossed_pending = (pending_records[0], ("GROUP-B", "call", "GROUP-B", "call", "20261112"))
    crossed_positions = (position_records[0], ("RUN-MULTI", "GROUP-B", "20261112", "EXEC-A"))
    crossed_fees = (fee_records[0], ("RUN-MULTI", "GROUP-B", "EXEC-WRONG"))
    mismatches = _track7_multi_group_read_only_lineage_mismatches(
        expected_run_id="RUN-MULTI",
        expected_expiries=expected_expiries,
        aggregate_records=aggregate_records,
        pending_records=crossed_pending,
        position_records=crossed_positions,
        fee_records=crossed_fees,
    )
    assert "pending_expiry_mismatch" in mismatches
    assert "position_expiry_mismatch" in mismatches
    assert "fee_execution_lineage_mismatch" in mismatches
    assert "position_execution_cross_group_duplicate" in mismatches

    missing_group_b = _track7_multi_group_read_only_lineage_mismatches(
        expected_run_id="RUN-MULTI",
        expected_expiries=expected_expiries,
        aggregate_records=aggregate_records,
        pending_records=pending_records[:1],
        position_records=position_records[:1],
        fee_records=fee_records[:1],
    )
    assert "pending_projection_missing:GROUP-B" in missing_group_b
    assert "position_projection_missing:GROUP-B" in missing_group_b
    assert "fee_projection_missing:GROUP-B" in missing_group_b

    duplicated_group_a = _track7_multi_group_read_only_lineage_mismatches(
        expected_run_id="RUN-MULTI",
        expected_expiries=expected_expiries,
        aggregate_records=aggregate_records,
        pending_records=pending_records + (pending_records[0],),
        position_records=position_records + (position_records[0],),
        fee_records=fee_records + (fee_records[0],),
    )
    assert "pending_projection_duplicate:GROUP-A" in duplicated_group_a
    assert "position_projection_duplicate:GROUP-A" in duplicated_group_a
    assert "fee_projection_duplicate:GROUP-A" in duplicated_group_a


def _track7_multi_group_read_only_lineage_mismatches(
    *,
    expected_run_id: str,
    expected_expiries: dict[str, str],
    aggregate_records: tuple[tuple[str, str], ...],
    pending_records: tuple[tuple[str, str, str, str, str], ...],
    position_records: tuple[tuple[str, str, str, str], ...],
    fee_records: tuple[tuple[str, str, str], ...],
) -> tuple[str, ...]:
    """Test-side read-only audit scoped independently to each concurrent group."""
    mismatches: set[str] = set()
    groups = set(expected_expiries)

    aggregate_by_group: dict[str, list[str]] = {group: [] for group in groups}
    for group_id, expiry in aggregate_records:
        if group_id in aggregate_by_group:
            aggregate_by_group[group_id].append(expiry)
        else:
            mismatches.add("aggregate_unexpected_group")
    for group_id, expiry in expected_expiries.items():
        rows = aggregate_by_group[group_id]
        if not rows:
            mismatches.add(f"aggregate_missing:{group_id}")
        if len(rows) > 1:
            mismatches.add(f"aggregate_duplicate:{group_id}")
        if any(value != expiry for value in rows):
            mismatches.add("aggregate_expiry_mismatch")

    pending_by_group: dict[str, list[tuple[str, str, str, str, str]]] = {
        group: [] for group in groups
    }
    for record in pending_records:
        plan_group, leg_id, command_group, command_leg, expiry = record
        if plan_group in pending_by_group:
            pending_by_group[plan_group].append(record)
        if plan_group != command_group:
            mismatches.add("pending_group_mismatch")
        if leg_id != command_leg:
            mismatches.add("pending_leg_mismatch")
        expected_group = plan_group if plan_group in expected_expiries else command_group
        if expected_group in expected_expiries and expiry != expected_expiries[expected_group]:
            mismatches.add("pending_expiry_mismatch")
    for group_id, rows in pending_by_group.items():
        if not rows:
            mismatches.add(f"pending_projection_missing:{group_id}")
        keys = [(row[0], row[1]) for row in rows]
        if len(keys) != len(set(keys)):
            mismatches.add(f"pending_projection_duplicate:{group_id}")

    positions_by_group: dict[str, list[tuple[str, str, str, str]]] = {
        group: [] for group in groups
    }
    execution_groups: dict[str, set[str]] = {}
    for record in position_records:
        run_id, group_id, expiry, execution_id = record
        if group_id in positions_by_group:
            positions_by_group[group_id].append(record)
        if run_id != expected_run_id:
            mismatches.add("position_run_mismatch")
        if group_id in expected_expiries and expiry != expected_expiries[group_id]:
            mismatches.add("position_expiry_mismatch")
        execution_groups.setdefault(execution_id, set()).add(group_id)
    for group_id, rows in positions_by_group.items():
        if not rows:
            mismatches.add(f"position_projection_missing:{group_id}")
        keys = [(row[1], row[3]) for row in rows]
        if len(keys) != len(set(keys)):
            mismatches.add(f"position_projection_duplicate:{group_id}")
    if any(len(group_ids) > 1 for group_ids in execution_groups.values()):
        mismatches.add("position_execution_cross_group_duplicate")

    fees_by_group: dict[str, list[tuple[str, str, str]]] = {
        group: [] for group in groups
    }
    for record in fee_records:
        run_id, group_id, _execution_id = record
        if group_id in fees_by_group:
            fees_by_group[group_id].append(record)
        if run_id != expected_run_id:
            mismatches.add("fee_run_mismatch")
    for group_id, rows in fees_by_group.items():
        if not rows:
            mismatches.add(f"fee_projection_missing:{group_id}")
        keys = [(row[1], row[2]) for row in rows]
        if len(keys) != len(set(keys)):
            mismatches.add(f"fee_projection_duplicate:{group_id}")
        position_ids = {row[3] for row in positions_by_group[group_id]}
        fee_ids = {row[2] for row in rows}
        if position_ids != fee_ids:
            mismatches.add("fee_execution_lineage_mismatch")
    return tuple(sorted(mismatches))


def test_s7_factory_callback_releases_only_the_terminal_group_when_another_group_remains_open():
    replay_adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=replay_adapter)
    ticks = list(HighSpeedReplayRunner(DATASET, synthetic_adapter=replay_adapter).events())
    expiries = ("20261109", "20261112")
    put_ticks = {
        expiry: next(
            tick for tick in ticks
            if tick.expiry == expiry
            and str(tick.option_type).upper() == "PUT"
        )
        for expiry in expiries
    }

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master,
        initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    run_id = "Q25-S7-FACTORY-MULTI-GROUP-RELEASE"
    adapter = S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET,
        manifest_path=MANIFEST,
        risk_profile_path=ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json",
    )
    adapter.bind_run_id(run_id)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("track7_volatility_skew_weekly_insurance", "1.0"),),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
        validation_only_s7_runtime_adapter=adapter,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    strategy = loop.strategy_hub._orchestrator._registry.get(
        "track7_volatility_skew_weekly_insurance", "1.0",
    )

    group_ids = {}
    for index, expiry in enumerate(expiries, start=1):
        tick = put_ticks[expiry]
        group_id = f"Q25-S7-MULTI-GROUP-{index}"
        group_ids[expiry] = group_id
        strategy._activate_expiry(expiry)
        strategy.state = strategy.state.__class__(
            entry_pending=True,
            expiry=expiry,
            put_strike=Decimal("487.5"),
            call_strike=Decimal("512.5"),
            contract_multiplier=Decimal("250000"),
            entry_stage="PUT_READY",
        )
        _publish_contract_scoped_replay_quote(
            tick,
            option_master=master,
            market=bootstrap.bundle.market,
            order_book=bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime.order_book,
        )
        sources.set_tick(tick)
        bootstrap.bundle.market.publish_replay_tick(tick)
        plan = strategy.build_execution_plan(
            group_id,
            proposal=_proposal("WEEKLY_INSURANCE_ENTRY_PUT", "PUT", Decimal("487.5")),
        )
        result = bridge.execute(plan)
        assert result.reports[0].status == "FILLED"
        assert strategy.state.put_open is True
        assert group_id in adapter._reserved
        assert group_id in adapter._reserved_entry_fees
        assert adapter._group_expiry_by_id[group_id] == expiry

    assert len(bridge.position_lot_store.open_lots()) == 2
    assert set(adapter._reserved) == set(group_ids.values())
    assert set(adapter._group_expiry_by_id.values()) == set(expiries)

    first_expiry, second_expiry = expiries
    first_group = group_ids[first_expiry]
    second_group = group_ids[second_expiry]
    strategy._activate_expiry(first_expiry)
    close_tick = replace(
        put_ticks[first_expiry],
        timestamp=(
            datetime.fromisoformat(put_ticks[first_expiry].timestamp)
            + timedelta(seconds=2)
        ).isoformat(),
        seq_id=int(put_ticks[first_expiry].seq_id) + 2000,
    )
    _publish_contract_scoped_replay_quote(
        close_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.order_book,
    )
    sources.set_tick(close_tick)
    bootstrap.bundle.market.publish_replay_tick(close_tick)
    close_plan = strategy.build_execution_plan(
        first_group,
        proposal=_proposal(
            "WEEKLY_INSURANCE_CLOSE_PUT", "PUT", Decimal("487.5"), side="SELL",
        ),
    )
    close_result = bridge.execute(close_plan)

    assert close_result.group_complete is True
    assert close_result.position_flat is True
    assert close_result.pending_legs == 0
    assert first_group not in adapter._reserved
    assert first_group not in adapter._reserved_entry_fees
    assert first_group not in adapter._group_expiry_by_id
    assert second_group in adapter._reserved
    assert second_group in adapter._reserved_entry_fees
    assert adapter._group_expiry_by_id[second_group] == second_expiry
    remaining_lots = bridge.position_lot_store.open_lots()
    assert len(remaining_lots) == 1
    assert remaining_lots[0].group_id == second_group
    assert remaining_lots[0].instrument_identity.expiry == second_expiry

    strategy._activate_expiry(second_expiry)
    second_close_tick = replace(
        put_ticks[second_expiry],
        timestamp=(
            datetime.fromisoformat(close_tick.timestamp) + timedelta(seconds=1)
        ).isoformat(),
        seq_id=int(put_ticks[second_expiry].seq_id) + 3000,
    )
    _publish_contract_scoped_replay_quote(
        second_close_tick,
        option_master=master,
        market=bootstrap.bundle.market,
        order_book=bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.order_book,
    )
    sources.set_tick(second_close_tick)
    bootstrap.bundle.market.publish_replay_tick(second_close_tick)
    second_close_plan = strategy.build_execution_plan(
        second_group,
        proposal=_proposal(
            "WEEKLY_INSURANCE_CLOSE_PUT", "PUT", Decimal("487.5"), side="SELL",
        ),
    )
    second_close_result = bridge.execute(second_close_plan)
    assert second_close_result.group_complete is True
    assert second_close_result.position_flat is True
    assert second_close_result.pending_legs == 0
    assert adapter._reserved == {}
    assert adapter._reserved_entry_fees == {}
    assert adapter._group_expiry_by_id == {}
    assert bridge.position_lot_store.open_lots() == ()

