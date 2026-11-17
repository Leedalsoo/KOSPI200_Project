from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

import verification.run_track2_market_calibrated_runtime_replay as replay


def _arguments(tmp_path):
    dataset = tmp_path / "runtime_v2"
    dataset.mkdir()
    manifest = dataset / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    quote_manifest = tmp_path / "quote-manifest.json"
    quote_manifest.write_text("{}", encoding="utf-8")
    trace = tmp_path / "reports" / "trace.jsonl"
    return dataset, manifest, profile, quote_manifest, trace


def test_runner_forces_isolated_track2_validation_and_reports_trace_hash(tmp_path, monkeypatch, capsys):
    dataset, manifest, profile, quote_manifest, trace = _arguments(tmp_path)
    calls = {}

    class FakeRunner:
        def __init__(self, supplied_dataset, **kwargs):
            calls["dataset"] = supplied_dataset
            calls.update(kwargs)

        def run(self, *, max_events=None):
            calls["max_events"] = max_events
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_bytes(b"deterministic validation trace\n")
            return SimpleNamespace(
                run_id="TEST-RUN-1", events=2072, signals=1, approved=1,
                routed=4, filled=4, rejected=0, exhausted=True,
                realized_pnl=0.0, unrealized_pnl=-787500.0, net_pnl=-787500.0,
                trace_status="CONNECTED",
            )

    monkeypatch.setattr(replay, "HighSpeedVirtualRuntimeReplayRunner", FakeRunner)
    code = replay.main([
        "--dataset", str(dataset), "--manifest", str(manifest),
        "--profile", str(profile), "--quote-scenario-manifest", str(quote_manifest),
        "--trace-output", str(trace), "--run-id", "TEST-RUN-1",
        "--max-events", "86",
    ])

    assert code == 0
    assert calls["validation_only_synthetic"] is True
    assert calls["strategy_keys"] == (("track2_asymmetric_trap", "1.0"),)
    assert calls["validation_only_track2_manifest"] == manifest.resolve()
    assert calls["validation_only_track2_risk_profile"] == profile.resolve()
    assert calls["validation_only_track2_quote_scenario_manifest"] == quote_manifest.resolve()
    assert calls["log_mode"] == "detailed"
    assert calls["max_events"] == 86
    result = json.loads(capsys.readouterr().out)
    assert result["trace_sha256"] == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert result["max_events"] == 86
    assert result["validation_only"] is True
    assert result["live_api_enabled"] is False
    assert result["real_vts_api_enabled"] is False
    assert result["order_submission_enabled"] is False


def test_runner_refuses_to_overwrite_an_existing_trace(tmp_path, monkeypatch):
    dataset, manifest, profile, quote_manifest, trace = _arguments(tmp_path)
    trace.parent.mkdir(parents=True)
    trace.write_text("preserve", encoding="utf-8")
    called = False

    class ForbiddenRunner:
        def __init__(self, *args, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr(replay, "HighSpeedVirtualRuntimeReplayRunner", ForbiddenRunner)
    with pytest.raises(SystemExit) as exc:
        replay.main([
            "--dataset", str(dataset), "--manifest", str(manifest),
            "--profile", str(profile), "--quote-scenario-manifest", str(quote_manifest),
            "--trace-output", str(trace), "--run-id", "TEST-RUN-2",
        ])
    assert exc.value.code == 2
    assert called is False
    assert trace.read_text(encoding="utf-8") == "preserve"

def test_runner_rejects_nonpositive_event_cap(tmp_path):
    dataset, manifest, profile, quote_manifest, trace = _arguments(tmp_path)
    with pytest.raises(SystemExit) as exc:
        replay.main([
            "--dataset", str(dataset), "--manifest", str(manifest),
            "--profile", str(profile), "--quote-scenario-manifest", str(quote_manifest),
            "--trace-output", str(trace), "--run-id", "TEST-RUN-3", "--max-events", "0",
        ])
    assert exc.value.code == 2
    assert not trace.exists()
