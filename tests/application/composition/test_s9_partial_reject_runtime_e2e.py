from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

from contracts.types import ExecutionReport
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.high_speed.replay_trace import ReplayLogMode

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


def test_s9_natural_signal_pending_leg_timeout_cancel_confirm_wait_retry_then_next_day_close(
    monkeypatch, tmp_path,
):
    dataset, manifest = _retry_dataset(tmp_path)
    bridges = []
    brokers = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        broker = _PendingCallFirstBroker(self.ack.broker)
        self.ack.broker = broker
        brokers.append(broker)
        bridges.append(self)

    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "__init__", patched_init)
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
    report = runner.run(max_events=8)

    bridge = bridges[-1]
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
    runner.run(max_events=10)

    bridge, broker = bridges[-1], brokers[-1]
    assert broker.call_buy_submissions == 2  # initial order and one retry before close
    assert broker.cancelled_call_orders == 2  # timeout cancel, then close-boundary cancel
    assert runner.s9_strategy.state.state == "OVERNIGHT_INSURANCE_CLOSED"
    assert bridge.pending_legs == {}
    assert bridge.position_lot_store.open_lots() == ()
    reports = bridge.group_reports(next(iter(bridge.position_groups.all().keys())))
    assert sum(1 for item in reports if item.leg_id == "call" and item.status == "CANCELLED") == 2
    assert any(item.leg_id.startswith("close-") and item.status == "FILLED" for item in reports)
