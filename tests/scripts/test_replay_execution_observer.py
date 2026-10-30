from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, BrokerOrderResponse, ExecutionReport
from environments.high_speed.replay_trace import ReplayExecutionObserver, ReplayLogMode, ReplayTraceController


class _FakeAdapter:
    def __init__(self, report=None, *, fail=False):
        self.last_report = None
        self.report = report
        self.fail = fail
        self.calls = []

    def submit(self, command):
        self.calls.append(command)
        if self.fail:
            raise RuntimeError("submit failed")
        self.last_report = self.report
        return BrokerOrderResponse(command.client_order_id, accepted=True)


def _command():
    return BrokerOrderCommand(
        client_order_id="client-1",
        instrument_id="SYNTHETIC_CONTRACT:ABC",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        strategy_id="S1",
        group_id="group-1",
        leg_id="leg-1",
    )


def _report(*, filled_quantity=2, execution_id="exec-1"):
    return ExecutionReport(
        client_order_id="client-1",
        broker_order_id="virtual-1",
        execution_id=execution_id,
        status="FILLED" if filled_quantity else "REJECTED",
        filled_quantity=filled_quantity,
        remaining_quantity=0 if filled_quantity else 2,
        execution_price=Decimal("1.20") if filled_quantity else None,
        execution_timestamp=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc) if filled_quantity else None,
        fee=Decimal("0.01") if filled_quantity else None,
        group_id="group-1",
        leg_id="leg-1",
    )


def test_observer_traces_command_report_and_fill_without_changing_result(tmp_path):
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=tmp_path / "trace.jsonl")
    adapter = _FakeAdapter(_report())
    original_submit = adapter.submit
    observer = ReplayExecutionObserver(trace, run_id="same-run")
    observer.event_sequence = 7
    observer.attach(adapter, adapter_name="single_leg")

    command = _command()
    response = adapter.submit(command)

    assert response == BrokerOrderResponse(command.client_order_id, accepted=True)
    assert adapter.calls == [command]
    assert observer.summary()["order_commands_observed"] == 1
    assert observer.summary()["execution_reports_observed"] == 1
    assert observer.summary()["fills_observed"] == 1

    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["order_command", "execution_report", "fill"]
    assert all(row["event_sequence"] == 7 for row in rows)
    assert rows[0]["payload"]["command"]["client_order_id"] == "client-1"
    assert rows[1]["payload"]["report"]["execution_id"] == "exec-1"
    assert rows[2]["payload"]["execution_id"] == "exec-1"
    assert rows[2]["payload"]["execution_price"] == "1.20"

    observer.detach()
    assert adapter.submit.__func__ is original_submit.__func__
    assert adapter.submit(command) == response
    assert len(adapter.calls) == 2


def test_observer_does_not_change_submission_when_trace_write_fails(tmp_path):
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=tmp_path / "trace.jsonl")

    def fail_emit(*args, **kwargs):
        raise OSError("trace storage unavailable")

    trace.emit = fail_emit
    response = BrokerOrderResponse("client-1", accepted=True)
    adapter = _FakeAdapter(_report())
    observer = ReplayExecutionObserver(trace, run_id="same-run")
    observer.attach(adapter, adapter_name="single_leg")

    actual = adapter.submit(_command())

    assert actual == response
    assert len(adapter.calls) == 1
    assert observer.summary()["status"] == "TRACE_WRITE_FAILED"
    assert observer.summary()["trace_write_errors"]
    observer.detach()


def test_observer_marks_missing_report_instead_of_inventing_a_fill(tmp_path):
    output = tmp_path / "trace.jsonl"
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=output)
    adapter = _FakeAdapter(report=None)
    observer = ReplayExecutionObserver(trace, run_id="same-run")
    observer.attach(adapter, adapter_name="single_leg")

    adapter.submit(_command())

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["order_command", "execution_report_unavailable"]
    assert observer.summary()["fills_observed"] == 0
    assert rows[1]["payload"]["reason"] == "CANONICAL_REPORT_NOT_EXPOSED"
    observer.detach()


def test_observer_records_attempt_then_preserves_submit_exception(tmp_path):
    output = tmp_path / "trace.jsonl"
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=output)
    adapter = _FakeAdapter(fail=True)
    observer = ReplayExecutionObserver(trace, run_id="same-run")
    observer.attach(adapter, adapter_name="multi_leg")

    with pytest.raises(RuntimeError, match="submit failed"):
        adapter.submit(_command())

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == ["order_command", "execution_report_unavailable"]
    assert rows[1]["payload"]["exception_type"] == "RuntimeError"
    observer.detach()
