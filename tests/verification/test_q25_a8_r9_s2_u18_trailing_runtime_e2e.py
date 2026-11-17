from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

import environments.high_speed.virtual_runtime_replay as replay
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from verification.track2_quote_profile_binding import bind_validation_only_track2_quote_scenario_profile
from verification.track2_u18_trailing_scenario import build_validation_only_track2_u18_trailing_scenario


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/accepted_market_data/runtime_v2"
SIDECAR = ROOT / "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
SOURCE_MANIFEST = SIDECAR / "manifest.exit_path_test.v3.rebound.json"
SOURCE_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.exit_path_test.v3.json"
TRAILING_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.trailing_path_test.v4.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_s2_u18_trailing_exit_closes_four_leg_group_in_shared_virtual_runtime(tmp_path, monkeypatch):
    required = (
        DATASET / "manifest.json",
        DATASET / "20261012.jsonl",
        DATASET / "20261013.jsonl",
        SOURCE_MANIFEST,
        SIDECAR / "four_leg_quotes.exit_path_test.v3.rebound.jsonl",
        SIDECAR / "candidate_inputs.json",
        SOURCE_PROFILE,
        TRAILING_PROFILE,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        pytest.skip(
            "No.1534 reuse-first sources are not materialized in this checkout; "
            f"compare the preserved source inventory before classifying them absent: {missing}"
        )

    protected_sources = (
        SOURCE_MANIFEST,
        SIDECAR / "four_leg_quotes.exit_path_test.v3.rebound.jsonl",
        SIDECAR / "candidate_inputs.json",
        DATASET / "manifest.json",
        DATASET / "20261012.jsonl",
        DATASET / "20261013.jsonl",
    )
    source_hashes_before = {path: _sha(path) for path in protected_sources}

    scenario = build_validation_only_track2_u18_trailing_scenario(
        source_manifest_path=SOURCE_MANIFEST,
        source_profile_path=SOURCE_PROFILE,
        output_dir=tmp_path / "u18-trailing-scenario",
    )
    assert scenario["candidate_count"] == 23
    assert scenario["quote_rows"] == 92
    assert [item["source_anchor_age_seconds"] for item in scenario["supplemental_snapshots"]] == [21, 30]
    assert [item["source_anchor_max_age_seconds"] for item in scenario["supplemental_snapshots"]] == [854, 863]

    bound = bind_validation_only_track2_quote_scenario_profile(
        source_manifest_path=scenario["manifest_path"],
        source_profile_path=SOURCE_PROFILE,
        target_profile_path=TRAILING_PROFILE,
        output_dir=tmp_path / "u18-trailing-profile-bound",
        purpose="U18_TRAILING_PATH_VALIDATION_ONLY_PRESERVE_SOURCE_ANCHORS",
    )
    bound_manifest = json.loads(bound.manifest_path.read_text(encoding="utf-8"))
    bound_profile = json.loads(TRAILING_PROFILE.read_text(encoding="utf-8"))
    assert bound_manifest["candidate_count"] == 23
    assert bound_manifest["quote_rows"] == 92
    assert bound_manifest["validation_profile_binding"]["quote_prices_sizes_timestamps_and_market_calibration_changed"] is False
    assert bound_manifest["validation_profile_binding"]["production_policy_approval"] is False
    assert bound_profile["U18_exit_policy"] == {
        "stop_loss_ratio": "-0.90",
        "trailing_activation_ratio": "0.40",
        "trailing_pullback_ratio": "0.25",
        "pnl_basis": "FOUR_LEG_NET_PNL_AFTER_FEES_AND_SLIPPAGE_OVER_INITIAL_NET_PREMIUM",
    }
    assert bound_profile["execution_enabled"] is False
    assert bound_profile["order_submission_enabled"] is False
    assert bound_profile["live_api_enabled"] is False
    assert bound_profile["real_vts_api_enabled"] is False

    captured = {}
    original_attach = replay.attach_standard_automated_loop

    def capture_attach(*args, **kwargs):
        loop = original_attach(*args, **kwargs)
        captured["loop"] = loop
        return loop

    monkeypatch.setattr(replay, "attach_standard_automated_loop", capture_attach)

    evaluations = []
    original_evaluate_trap = Track2AsymmetricTrap.evaluate_trap

    def capture_evaluate_trap(self, current_price, now):
        snapshot = self._group_pnl_snapshot
        signals = original_evaluate_trap(self, current_price, now)
        if snapshot is not None and snapshot.initial_net_premium_received:
            ratio = Decimal(str(snapshot.net_pnl)) / Decimal(str(snapshot.initial_net_premium_received))
            evaluations.append({
                "timestamp": now.isoformat(),
                "ratio": ratio,
                "peak": self._high_pnl_ratio,
                "reasons": tuple(signal.reason for signal in signals),
            })
        return signals

    monkeypatch.setattr(Track2AsymmetricTrap, "evaluate_trap", capture_evaluate_trap)

    trace_path = tmp_path / "s2-u18-trailing-runtime.jsonl"
    report = replay.HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id="Q25-A8-R9-S2-U18-TRAILING-PROBE-20261117",
        strategy_keys=(("track2_asymmetric_trap", "1.0"),),
        validation_only_synthetic=True,
        validation_only_track2_manifest=DATASET / "manifest.json",
        validation_only_track2_risk_profile=TRAILING_PROFILE,
        validation_only_track2_quote_scenario_manifest=bound.manifest_path,
        log_mode="detailed",
        trace_output=trace_path,
    ).run(max_events=120)

    loop = captured["loop"]
    bridge = loop.multi_leg_bridge
    open_lots = tuple(bridge.position_lot_store.open_lots())
    account = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account
    group_ids = tuple(bridge.position_groups.all().keys())
    assert len(group_ids) == 1
    final_group = bridge.position_groups.snapshot(group_ids[0])

    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    order_commands = [item for item in trace if item.get("event_type") == "order_command"]
    fills = [item for item in trace if item.get("event_type") == "fill"]
    purposes = Counter(item["payload"]["command"]["order_purpose"] for item in order_commands)

    assert report.events == 120
    assert report.exhausted is False
    assert report.signals == 2
    assert report.approved == 2
    assert report.routed == report.filled == 8
    assert report.rejected == 0
    assert len(fills) == 8
    assert purposes == {"ASYMMETRIC_TRAP_NARROW": 4, "TRAP_CLOSE": 4}
    assert open_lots == ()
    assert account.positions == {}
    assert float(final_group.initial_net_premium_received) == pytest.approx(1_987_500.0)
    evaluations_by_timestamp = {item["timestamp"]: item for item in evaluations}
    peak = evaluations_by_timestamp["2026-10-12T09:26:21+09:00"]
    pullback = evaluations_by_timestamp["2026-10-12T09:26:30+09:00"]
    assert float(peak["ratio"]) == pytest.approx(0.5828930817610063)
    assert float(pullback["ratio"]) == pytest.approx(0.3313207547169811)
    retracement = (peak["ratio"] - pullback["ratio"]) / peak["ratio"]
    assert float(retracement) == pytest.approx(0.431592, abs=0.00001)
    assert pullback["reasons"] == ("TRAP_GROUP_TRAILING_EXIT",)
    assert report.net_pnl == pytest.approx(-75_000.0)

    assert all(_sha(path) == digest for path, digest in source_hashes_before.items())
    assert _sha(trace_path) == "1f736057fee0d08834bf3a588a24e2b93c879c33161830f0d80155b6e080af23"
