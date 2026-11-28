from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import (
    VirtualMultiLegExecutionBridge,
)
from application.composition.track9_validation_only_runtime_adapter import (
    Track9ValidationOnlyRuntimeAdapter,
)
from contracts.types import ExecutionReport
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import (
    HighSpeedVirtualRuntimeReplayRunner,
)
from tests.application.composition.validation_only_lineage_audit import (
    lineage_mismatches,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108"
MANIFEST = DATA / "manifest.json"
CONTRACT = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"
RISK = ROOT / "config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json"


class _RejectCallOnlyBroker:
    def __init__(self, delegate):
        self.delegate = delegate

    def submit(self, command):
        if str(getattr(command, "leg_id", "")) == "call":
            return ExecutionReport(
                client_order_id=command.client_order_id,
                broker_order_id=None,
                execution_id=None,
                status="REJECTED",
                filled_quantity=0,
                remaining_quantity=int(command.quantity),
                execution_price=None,
                execution_timestamp=None,
                rejected_reason="SYNTHETIC_FAULT_INJECTION_CALL_LEG_REJECTED",
                group_id=command.group_id,
                leg_id=command.leg_id,
            )
        return self.delegate.submit(command)

    def query(self, client_order_id):
        return self.delegate.query(client_order_id)


def test_s9_natural_signal_one_leg_rejection_keeps_filled_buy_leg_overnight(monkeypatch):
    bridges = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self.ack.broker = _RejectCallOnlyBroker(self.ack.broker)
        bridges.append(self)

    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "__init__", patched_init)
    runner = HighSpeedVirtualRuntimeReplayRunner(
        DATA,
        run_id="S9-ONE-LEG-REJECT-20261108",
        strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=MANIFEST,
        validation_only_s9_contract_profile=CONTRACT,
        validation_only_s9_risk_profile=RISK,
        log_mode=ReplayLogMode.FAST,
    )
    report = runner.run(max_events=2)

    assert len(bridges) >= 2
    bridge = bridges[-1]
    assert runner.s9_strategy is not None
    assert runner.s9_strategy.state.state == "OVERNIGHT_INSURANCE_PARTIAL"
    assert report.signals == 1
    assert report.routed == 2
    assert report.filled == 1
    assert report.rejected == 1

    groups = bridge.position_groups.all()
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert {leg.leg_id: leg.status.value for leg in group.legs} == {
        "put": "FILLED",
        "call": "REJECTED",
    }
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].instrument_identity.option_type == "PUT"
    assert lots[0].remaining_quantity == 1

    # Read-only correlation of the surviving PUT PositionLot, its Fee Ledger
    # execution, rejected CALL group leg, and the S9 per-group reservation audit.
    run_id = runner.run_id
    fee_rows = tuple(bridge.fee_ledger.snapshot(run_id=run_id))
    execution_rows = tuple(runner.s9_runtime_snapshot["execution_reports"])
    adapter = runner.s9_validation_runtime_adapter
    group_records = tuple((item.group_id, item.strategy_id) for item in groups.values())
    position_records = tuple((
        lot.run_id, lot.strategy_id, lot.group_id, lot.leg_id, lot.client_order_id,
        lot.execution_id, lot.instrument_id, str(lot.instrument_identity.expiry),
    ) for lot in lots)
    fee_records = tuple((
        row.run_id, row.strategy_id, row.group_id, row.leg_id, row.client_order_id,
        row.execution_id, row.instrument_id,
    ) for row in fee_rows)
    execution_records = tuple((
        row.strategy_id, row.group_id, row.leg_id, row.client_order_id,
        row.exec_id, row.instrument_id, str(row.expiry),
    ) for row in execution_rows)
    pending_records = tuple((
        plan.group_id, leg.leg_id, command.group_id, command.leg_id, command.client_order_id,
    ) for plan, leg, command in bridge.pending_legs.values())
    reservation_records = tuple((group_id,) for group_id in adapter._reserved)
    risk_audit_records = tuple((row["run_id"], row["group_id"]) for row in adapter.risk_audit_records)
    audit_args = {
        "expected_run_id": run_id, "expected_strategy_id": "track9_event_overnight_insurance",
        "group_records": group_records, "pending_records": pending_records,
        "position_records": position_records, "fee_records": fee_records,
        "execution_records": execution_records, "reservation_records": reservation_records,
        "risk_audit_records": risk_audit_records,
    }
    before_audit_state = (
        tuple(bridge.position_groups.all().items()), tuple(bridge.position_lot_store.open_lots()),
        tuple(bridge.fee_ledger.snapshot(run_id=run_id)), tuple(bridge.pending_legs.items()),
        tuple(sorted(adapter._reserved.items())), tuple(dict(row) for row in adapter.risk_audit_records),
        tuple(runner.s9_runtime_snapshot["execution_reports"]),
    )
    assert lineage_mismatches(**audit_args) == ()
    assert len(reservation_records) == 1
    assert reservation_records[0][0] == lots[0].group_id
    assert any(item.startswith("fee_projection_missing:") for item in lineage_mismatches(
        **{**audit_args, "fee_records": ()}
    ))
    assert any(item.startswith("position_execution_duplicate:") for item in lineage_mismatches(
        **{**audit_args, "position_records": position_records + (position_records[0],)}
    ))
    wrong_fee = (fee_records[0][0], fee_records[0][1], "WRONG-GROUP", *fee_records[0][3:])
    assert any(item.startswith("fee_execution_lineage_mismatch:") for item in lineage_mismatches(
        **{**audit_args, "fee_records": (wrong_fee,)}
    ))
    assert before_audit_state == (
        tuple(bridge.position_groups.all().items()), tuple(bridge.position_lot_store.open_lots()),
        tuple(bridge.fee_ledger.snapshot(run_id=run_id)), tuple(bridge.pending_legs.items()),
        tuple(sorted(adapter._reserved.items())), tuple(dict(row) for row in adapter.risk_audit_records),
        tuple(runner.s9_runtime_snapshot["execution_reports"]),
    )


class _PendingCallFirstBroker:
    def __init__(self, delegate):
        self.delegate = delegate
        self.pending = {}
        self.call_buy_submissions = 0

    def submit(self, command):
        if str(getattr(command, "leg_id", "")) == "call" and str(getattr(command, "side", "")).upper() == "BUY":
            self.call_buy_submissions += 1
            if self.call_buy_submissions == 1:
                submitted_at = datetime(2026, 11, 6, 15, 0, tzinfo=timezone(timedelta(hours=9)))
                report = ExecutionReport(
                    client_order_id=command.client_order_id,
                    broker_order_id="S9-CALL-PENDING",
                    execution_id=None,
                    status="NEW",
                    filled_quantity=0,
                    remaining_quantity=int(command.quantity),
                    execution_price=None,
                    execution_timestamp=None,
                    submitted_at=submitted_at,
                    group_id=command.group_id,
                    leg_id=command.leg_id,
                )
                self.pending[command.client_order_id] = report
                return report
        return self.delegate.submit(command)

    def query(self, client_order_id):
        if client_order_id in self.pending:
            return self.pending[client_order_id]
        return self.delegate.query(client_order_id)

    def cancel(self, client_order_id):
        if client_order_id in self.pending:
            report = replace(self.pending[client_order_id], status="CANCELLED")
            self.pending[client_order_id] = report
            return report
        return self.delegate.cancel(client_order_id)


def _retry_dataset(tmp_path: Path, *, include_close: bool = False) -> tuple[Path, Path]:
    source_rows = [
        json.loads(line)
        for line in (DATA / "20261106.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expanded = [source_rows[0], source_rows[1]]
    for clock, order in (("15:05:00", (0, 1)), ("15:10:00", (1, 0))):
        for source_index in order:
            row = json.loads(json.dumps(source_rows[source_index]))
            tick = row["tick"]
            tick["timestamp"] = f"2026-11-06T{clock}+09:00"
            tick["option_observed_hour"] = clock
            tick["underlying_observed_hour"] = clock
            expanded.append(row)
    if include_close:
        for source_index in (0, 1):
            row = json.loads(json.dumps(source_rows[source_index]))
            tick = row["tick"]
            tick["timestamp"] = "2026-11-06T15:45:00+09:00"
            tick["option_observed_hour"] = "15:45:00"
            tick["underlying_observed_hour"] = "15:45:00"
            expanded.append(row)
    expanded.extend(source_rows[2:])
    for seq, row in enumerate(expanded, start=1):
        row["tick"]["seq_id"] = seq

    root = tmp_path / "s9_retry_dataset"
    root.mkdir()
    output = root / "20261106.jsonl"
    payload = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in expanded).encode("utf-8")
    output.write_bytes(payload)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(payload).hexdigest()
    manifest["output_path"] = str(output.resolve())
    manifest["output_sha256"] = digest
    manifest["dataset_sha256"] = digest
    manifest["output_bytes"] = len(payload)
    manifest["rows"] = len(expanded)
    manifest["dataset_file"] = output.name
    manifest_path = root / "manifest.json"
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    (root / "manifest.json.sha256").write_text(
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n", encoding="utf-8",
    )
    return root, manifest_path


def _observe_s9_reservation_lifecycle(monkeypatch, runner, bridges):
    observations = []
    releases = []
    original_process = VirtualMultiLegExecutionBridge.process_s9_entry_retries
    original_release = Track9ValidationOnlyRuntimeAdapter.release_group

    def observe_process(self, now, strategy=None):
        result = original_process(self, now, strategy=strategy)
        adapter = runner.s9_validation_runtime_adapter
        if adapter is not None:
            pending_groups = tuple(sorted({
                str(plan.group_id) for plan, _leg, _command in self.pending_legs.values()
            }))
            open_groups = tuple(sorted({
                str(lot.group_id) for lot in self.position_lot_store.open_lots()
            }))
            observations.append({
                "pending_groups": pending_groups,
                "open_groups": open_groups,
                "reserved_groups": tuple(sorted(adapter._reserved)),
            })
        return result

    def observe_release(self, group_id):
        if self is runner.s9_validation_runtime_adapter:
            bridge = bridges[-1]
            releases.append({
                "group_id": str(group_id),
                "was_reserved": str(group_id) in self._reserved,
                "pending_groups": tuple(sorted({
                    str(plan.group_id) for plan, _leg, _command in bridge.pending_legs.values()
                })),
                "open_groups": tuple(sorted({
                    str(lot.group_id) for lot in bridge.position_lot_store.open_lots()
                })),
            })
        return original_release(self, group_id)

    monkeypatch.setattr(
        VirtualMultiLegExecutionBridge, "process_s9_entry_retries", observe_process,
    )
    monkeypatch.setattr(Track9ValidationOnlyRuntimeAdapter, "release_group", observe_release)
    return observations, releases


def _assert_s9_reservation_lifecycle(adapter, observations, releases):
    assert observations
    assert any(
        event["pending_groups"]
        and set(event["pending_groups"]).issubset(event["reserved_groups"])
        for event in observations
    )
    assert any(
        event["open_groups"]
        and set(event["open_groups"]).issubset(event["reserved_groups"])
        for event in observations
    )
    assert len(releases) == 1
    release = releases[0]
    assert release["was_reserved"] is True
    assert release["pending_groups"] == ()
    assert release["open_groups"] == ()
    assert release["group_id"] not in adapter._reserved
    assert adapter._reserved == {}


def _assert_s9_closed_lifecycle_lineage(runner, bridge):
    run_id = runner.run_id
    strategy_id = "track9_event_overnight_insurance"
    groups = bridge.position_groups.all()
    assert len(groups) == 1
    group_id = next(iter(groups))
    reports = tuple(runner.s9_runtime_snapshot["execution_reports"])
    fees = tuple(bridge.fee_ledger.snapshot(run_id=run_id))
    history = tuple(bridge.position_lot_store.history())
    close_events = tuple(bridge.position_lot_store.close_events())
    reports_by_id = {row.exec_id: row for row in reports}
    fees_by_id = {row.execution_id: row for row in fees}

    assert reports and len(reports_by_id) == len(reports)
    assert set(reports_by_id) == set(fees_by_id)
    assert history and close_events
    for execution_id, report in reports_by_id.items():
        fee = fees_by_id[execution_id]
        assert report.strategy_id == strategy_id
        assert report.group_id == group_id
        assert fee.run_id == run_id
        assert fee.strategy_id == strategy_id
        assert fee.group_id == group_id
        assert (fee.leg_id, fee.client_order_id, fee.instrument_id) == (
            report.leg_id, report.client_order_id, report.instrument_id,
        )
    for lot in history:
        report = reports_by_id[lot.execution_id]
        assert (lot.run_id, lot.strategy_id, lot.group_id) == (
            run_id, strategy_id, group_id,
        )
        assert (lot.leg_id, lot.client_order_id, lot.instrument_id) == (
            report.leg_id, report.client_order_id, report.instrument_id,
        )
    for event in close_events:
        source_lot = next(
            lot for lot in history if lot.execution_id == event.source_lot_execution_id
        )
        close_report = reports_by_id[event.execution_id]
        assert close_report.group_id == source_lot.group_id == group_id
        assert close_report.strategy_id == strategy_id
        assert close_report.client_order_id == fees_by_id[event.execution_id].client_order_id


def test_s9_natural_signal_pending_leg_timeout_cancel_confirm_wait_retry_then_next_day_close(
    monkeypatch, tmp_path,
):
    dataset, manifest = _retry_dataset(tmp_path)
    bridges = []
    brokers = []
    executions = []
    original_init = VirtualMultiLegExecutionBridge.__init__
    original_execute = VirtualMultiLegExecutionBridge.execute

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        broker = _PendingCallFirstBroker(self.ack.broker)
        self.ack.broker = broker
        brokers.append(broker)
        bridges.append(self)

    def capture_execute(self, plan, **kwargs):
        result = original_execute(self, plan, **kwargs)
        if plan.strategy_id == "track9_event_overnight_insurance":
            executions.append((plan, result))
        return result

    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "__init__", patched_init)
    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "execute", capture_execute)
    runner = HighSpeedVirtualRuntimeReplayRunner(
        dataset,
        run_id="S9-BUY-BUY-5M-RETRY-E2E-20261108",
        strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=manifest,
        validation_only_s9_contract_profile=CONTRACT,
        validation_only_s9_risk_profile=RISK,
        log_mode=ReplayLogMode.FAST,
    )
    observations, releases = _observe_s9_reservation_lifecycle(
        monkeypatch, runner, bridges,
    )
    report = runner.run(max_events=8)
    _assert_s9_reservation_lifecycle(
        runner.s9_validation_runtime_adapter, observations, releases,
    )

    bridge = bridges[-1]
    _assert_s9_closed_lifecycle_lineage(runner, bridge)
    broker = brokers[-1]
    broker = brokers[-1]
    assert broker.call_buy_submissions == 2  # initial pending BUY + one retry BUY
    entry_reports = bridge.group_reports(next(iter(bridge.position_groups.all().keys())))
    call_reports = [item for item in entry_reports if item.leg_id == "call"]
    assert any(item.status == "CANCELLED" for item in call_reports)
    assert any(item.status == "FILLED" for item in call_reports)
    assert runner.s9_strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"
    assert bridge.pending_legs == {}
    assert bridge.position_lot_store.open_lots() == ()
    groups = bridge.position_groups.all()
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert group.is_complete is True
    assert report.rejected == 0

    close_plan, close_result = executions[-1]
    assert close_plan.purpose == "OVERNIGHT_INSURANCE_CLOSE"
    callback_deliveries = []
    original_strategy_callback = runner.s9_strategy.on_execution_result

    def count_strategy_callback(purpose, result):
        callback_deliveries.append((purpose, result))
        return original_strategy_callback(purpose, result)

    monkeypatch.setattr(runner.s9_strategy, "on_execution_result", count_strategy_callback)
    bridge.execution_result_callback(close_plan, close_result)
    bridge.execution_result_callback(close_plan, close_result)
    assert callback_deliveries == []
    assert len(releases) == 1
    assert runner.s9_strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"


class _NeverFillCallBroker:
    def __init__(self, delegate):
        self.delegate = delegate
        self.pending = {}
        self.call_buy_submissions = 0
        self.cancelled_call_orders = 0

    def submit(self, command):
        if str(getattr(command, "leg_id", "")) == "call" and str(getattr(command, "side", "")).upper() == "BUY":
            self.call_buy_submissions += 1
            report = ExecutionReport(
                client_order_id=command.client_order_id,
                broker_order_id=f"S9-CALL-PENDING-{self.call_buy_submissions}",
                execution_id=None, status="NEW", filled_quantity=0,
                remaining_quantity=int(command.quantity), execution_price=None,
                execution_timestamp=None,
                submitted_at=datetime(2026, 11, 6, 15, 0, tzinfo=timezone(timedelta(hours=9))),
                group_id=command.group_id, leg_id=command.leg_id,
            )
            self.pending[command.client_order_id] = report
            return report
        return self.delegate.submit(command)

    def query(self, client_order_id):
        return self.pending.get(client_order_id) or self.delegate.query(client_order_id)

    def cancel(self, client_order_id):
        if client_order_id in self.pending:
            self.cancelled_call_orders += 1
            report = replace(self.pending[client_order_id], status="CANCELLED")
            self.pending[client_order_id] = report
            return report
        return self.delegate.cancel(client_order_id)


def test_s9_unpaired_put_is_kept_overnight_then_only_existing_leg_closes_next_day(
    monkeypatch, tmp_path,
):
    dataset, manifest = _retry_dataset(tmp_path, include_close=True)
    bridges = []
    brokers = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        broker = _NeverFillCallBroker(self.ack.broker)
        self.ack.broker = broker
        brokers.append(broker)
        bridges.append(self)

    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "__init__", patched_init)
    runner = HighSpeedVirtualRuntimeReplayRunner(
        dataset,
        run_id="S9-ONE-LEG-OVERNIGHT-CLOSE-E2E-20261108",
        strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=manifest,
        validation_only_s9_contract_profile=CONTRACT,
        validation_only_s9_risk_profile=RISK,
        log_mode=ReplayLogMode.FAST,
    )
    observations, releases = _observe_s9_reservation_lifecycle(
        monkeypatch, runner, bridges,
    )
    runner.run(max_events=10)
    _assert_s9_reservation_lifecycle(
        runner.s9_validation_runtime_adapter, observations, releases,
    )

    bridge, broker = bridges[-1], brokers[-1]
    _assert_s9_closed_lifecycle_lineage(runner, bridge)
    assert broker.call_buy_submissions == 2  # initial order and one retry before close
    assert broker.cancelled_call_orders == 2  # timeout cancel, then close-boundary cancel
    assert runner.s9_strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"
    assert bridge.pending_legs == {}
    assert bridge.position_lot_store.open_lots() == ()
    reports = bridge.group_reports(next(iter(bridge.position_groups.all().keys())))
    assert sum(1 for item in reports if item.leg_id == "call" and item.status == "CANCELLED") == 2
    assert any(item.leg_id.startswith("close-") and item.status == "FILLED" for item in reports)


def test_s9_callback_fingerprint_is_report_order_invariant():
    from application.composition.automated_virtual_runtime_factory import (
        _track9_execution_result_callback_key,
    )

    plan = SimpleNamespace(group_id="S9-GROUP", purpose="OVERNIGHT_INSURANCE_CLOSE")
    put = SimpleNamespace(
        client_order_id="S9-PUT-ORDER", execution_id="S9-PUT-EXEC", status="FILLED",
        filled_quantity=1, remaining_quantity=0, execution_price=Decimal("10"),
        fee=Decimal("0.1"), execution_timestamp="2026-11-09T10:00:00+09:00",
        group_id=plan.group_id, leg_id="put",
    )
    call = SimpleNamespace(
        client_order_id="S9-CALL-ORDER", execution_id="S9-CALL-EXEC", status="FILLED",
        filled_quantity=1, remaining_quantity=0, execution_price=Decimal("11"),
        fee=Decimal("0.1"), execution_timestamp="2026-11-09T10:00:01+09:00",
        group_id=plan.group_id, leg_id="call",
    )
    result = SimpleNamespace(
        reports=(put, call), group_complete=True, pending_legs=0, position_flat=True,
    )
    reordered = SimpleNamespace(
        reports=(call, put), group_complete=True, pending_legs=0, position_flat=True,
    )

    assert _track9_execution_result_callback_key(plan, result) == (
        _track9_execution_result_callback_key(plan, reordered)
    )


def test_s9_callback_fingerprint_distinguishes_attempt_and_terminal_state():
    from application.composition.automated_virtual_runtime_factory import (
        _track9_execution_result_callback_key,
    )

    plan = SimpleNamespace(group_id="S9-GROUP", purpose="OVERNIGHT_INSURANCE_CLOSE")
    first = SimpleNamespace(
        client_order_id="S9-ATTEMPT-1", execution_id="S9-EXEC-1", status="FILLED",
        filled_quantity=1, remaining_quantity=0, execution_price=Decimal("10"),
        fee=Decimal("0.1"), execution_timestamp="2026-11-09T10:00:00+09:00",
        group_id=plan.group_id, leg_id="put",
    )
    second = SimpleNamespace(**{**vars(first), "client_order_id": "S9-ATTEMPT-2"})
    first_result = SimpleNamespace(
        reports=(first,), group_complete=True, pending_legs=0, position_flat=True,
    )
    second_attempt_result = SimpleNamespace(
        reports=(second,), group_complete=True, pending_legs=0, position_flat=True,
    )
    pending_result = SimpleNamespace(
        reports=(first,), group_complete=False, pending_legs=1, position_flat=False,
    )

    first_key = _track9_execution_result_callback_key(plan, first_result)
    assert first_key != _track9_execution_result_callback_key(plan, second_attempt_result)
    assert first_key != _track9_execution_result_callback_key(plan, pending_result)
