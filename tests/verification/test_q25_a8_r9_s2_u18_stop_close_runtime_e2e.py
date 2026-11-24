from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

import environments.high_speed.virtual_runtime_replay as replay
from verification.track2_quote_profile_binding import bind_validation_only_track2_quote_scenario_profile
from verification.track2_u18_stop_scenario import build_validation_only_track2_u18_stop_scenario


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/accepted_market_data/runtime_v2"
SIDECAR = ROOT / "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
SOURCE_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json"
STOP_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.exit_path_test.v3.json"


def test_s2_u18_stop_close_uses_shared_virtual_runtime_and_finishes_group_flat(tmp_path, monkeypatch):
    required = (
        DATASET / "manifest.json",
        DATASET / "20261012.jsonl",
        DATASET / "20261013.jsonl",
        SIDECAR / "manifest.json",
        SIDECAR / "four_leg_quotes.jsonl",
        SIDECAR / "candidate_inputs.json",
        SOURCE_PROFILE,
        STOP_PROFILE,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        pytest.skip(
            "No.1534 reuse-first input is not materialized in this checkout; compare the original workspace and "
            f"preserved source inventory before classifying missing data: {missing}"
        )

    source_hashes_before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            DATASET / "manifest.json",
            DATASET / "20261012.jsonl",
            DATASET / "20261013.jsonl",
            SIDECAR / "manifest.json",
            SIDECAR / "four_leg_quotes.jsonl",
            SIDECAR / "candidate_inputs.json",
        )
    }
    scenario = build_validation_only_track2_u18_stop_scenario(
        source_manifest_path=SIDECAR / "manifest.json",
        source_profile_path=SOURCE_PROFILE,
        accepted_dataset_path=DATASET,
        output_dir=tmp_path / "u18-stop-scenario",
    )
    assert scenario["candidate_count"] == 22
    assert scenario["quote_rows"] == 88
    assert scenario["supplemental_snapshots"][0]["source_anchor_age_seconds"] == 21
    assert scenario["supplemental_snapshots"][0]["source_anchor_max_age_seconds"] == 854
    assert scenario["supplemental_snapshots"][0]["underlying_anchor_price"] == "1034.97"

    captured = {}
    original_attach = replay.attach_standard_automated_loop

    def capture_attach(*args, **kwargs):
        loop = original_attach(*args, **kwargs)
        captured["loop"] = loop
        return loop

    monkeypatch.setattr(replay, "attach_standard_automated_loop", capture_attach)
    binding = bind_validation_only_track2_quote_scenario_profile(
        source_manifest_path=scenario["manifest_path"],
        source_profile_path=SOURCE_PROFILE,
        target_profile_path=STOP_PROFILE,
        output_dir=tmp_path / "profile-bound-sidecar",
        purpose="U18_STOP_PATH_VALIDATION_ONLY_MARKET_ANCHORED_POSITION_AWARE_STRESS",
    )
    trace_path = tmp_path / "s2-u18-stop-runtime.jsonl"
    runner = replay.HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id="Q25-A8-R9-S2-U18-STOP-87-20261124",
        strategy_keys=(("track2_asymmetric_trap", "1.0"),),
        validation_only_synthetic=True,
        validation_only_track2_manifest=DATASET / "manifest.json",
        validation_only_track2_risk_profile=STOP_PROFILE,
        validation_only_track2_quote_scenario_manifest=binding.manifest_path,
        log_mode="detailed",
        trace_output=trace_path,
    )
    report = runner.run(max_events=87)

    loop = captured["loop"]
    bridge = loop.multi_leg_bridge
    open_lots = tuple(bridge.position_lot_store.open_lots())
    group_ids = tuple(bridge.position_groups.all().keys())
    assert len(group_ids) == 1
    snapshot = bridge.position_groups.snapshot(group_ids[0])
    account = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account

    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    order_commands = [item for item in trace if item.get("event_type") == "order_command"]
    purposes = Counter(item["payload"]["command"]["order_purpose"] for item in order_commands)
    fills = [item for item in trace if item.get("event_type") == "fill"]

    assert report.events == 87
    assert report.exhausted is False  # Deliberately stop after the first completed group-close scenario.
    assert report.signals == 2  # One four-leg entry and one U18 stop-close signal.
    assert report.approved == 2
    assert report.routed == report.filled == 8
    assert report.rejected == 0
    assert len(fills) == 8
    assert purposes == {"ASYMMETRIC_TRAP_NARROW": 4, "TRAP_CLOSE": 4}
    assert open_lots == ()
    assert account.positions == {}
    assert float(snapshot.initial_net_premium_received) == pytest.approx(1_987_500.0)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in source_hashes_before.items())

    bound_manifest = json.loads(binding.manifest_path.read_text(encoding="utf-8"))
    bound_profile = json.loads(STOP_PROFILE.read_text(encoding="utf-8"))
    assert bound_manifest["validation_profile_binding"]["quote_prices_sizes_timestamps_and_market_calibration_changed"] is False
    assert bound_manifest["validation_profile_binding"]["production_policy_approval"] is False
    assert bound_profile["U18_exit_policy"]["stop_loss_ratio"] == "-0.40"
    assert bound_profile["execution_enabled"] is False
    assert bound_profile["order_submission_enabled"] is False
    assert bound_profile["live_api_enabled"] is False
    assert bound_profile["real_vts_api_enabled"] is False
