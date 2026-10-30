from __future__ import annotations

import json

import pytest

from environments.high_speed.replay_trace import ReplayLogMode, ReplayTraceController


def test_fast_mode_is_noop_and_rejects_trace_output(tmp_path):
    with pytest.raises(ValueError, match="FAST_REPLAY_TRACE_OUTPUT_FORBIDDEN"):
        ReplayTraceController(ReplayLogMode.FAST, output_path=tmp_path / "fast.jsonl")
    trace = ReplayTraceController(ReplayLogMode.FAST)
    trace.emit("market_event", run_id="same-run", event_sequence=0, payload={"seq_id": 1})
    assert list(tmp_path.iterdir()) == []


def test_detailed_mode_requires_explicit_new_output_path(tmp_path):
    with pytest.raises(ValueError, match="DETAILED_REPLAY_TRACE_OUTPUT_REQUIRED"):
        ReplayTraceController(ReplayLogMode.DETAILED)
    existing = tmp_path / "existing.jsonl"
    existing.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="DETAILED_REPLAY_TRACE_OUTPUT_ALREADY_EXISTS"):
        ReplayTraceController(ReplayLogMode.DETAILED, output_path=existing)
    assert existing.read_text(encoding="utf-8") == "preserve\n"


def test_detailed_mode_requires_existing_parent_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="DETAILED_REPLAY_TRACE_PARENT_DIRECTORY_REQUIRED"):
        ReplayTraceController(ReplayLogMode.DETAILED, output_path=tmp_path / "missing" / "trace.jsonl")


def test_detailed_trace_records_are_ordered_jsonl_with_stable_schema(tmp_path):
    output = tmp_path / "trace.jsonl"
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=output)
    trace.emit("replay_started", run_id="same-run", payload={"dataset": "fixture", "seed": 7})
    trace.emit("market_event", run_id="same-run", event_sequence=0, timestamp="2026-10-29T09:00:00+09:00", payload={"seq_id": 4, "filled": 1})
    trace.emit("replay_finished", run_id="same-run", payload={"net_pnl": 12.5})
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["trace_sequence"] for row in rows] == [0, 1, 2]
    assert [row["event_type"] for row in rows] == ["replay_started", "market_event", "replay_finished"]
    assert rows[1]["event_sequence"] == 0
    assert rows[1]["payload"] == {"filled": 1, "seq_id": 4}
    assert all(row["schema"] == "high-speed-replay-trace-v1" for row in rows)


def test_mode_and_payload_validation_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="REPLAY_LOG_MODE_UNSUPPORTED"):
        ReplayTraceController("verbose")
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=tmp_path / "trace.jsonl")
    with pytest.raises(ValueError, match="REPLAY_TRACE_EVENT_TYPE_AND_RUN_ID_REQUIRED"):
        trace.emit("", run_id="run")
    with pytest.raises(TypeError, match="REPLAY_TRACE_PAYLOAD_MUST_BE_OBJECT"):
        trace.emit("event", run_id="run", payload=[1])


def test_trace_storage_failure_is_reported_without_interrupting_replay(tmp_path):
    parent = tmp_path / "trace-parent"
    parent.mkdir()
    trace = ReplayTraceController(ReplayLogMode.DETAILED, output_path=parent / "trace.jsonl")
    parent.rmdir()

    trace.emit("market_event", run_id="same-run", event_sequence=0, payload={"seq_id": 1})

    assert trace.status == "TRACE_WRITE_FAILED"
    assert trace.write_errors == ["FileNotFoundError"]
    assert trace._trace_sequence == 0
