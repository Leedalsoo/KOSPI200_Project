"""Synthetic-only freshness threshold sensitivity experiment; never a production policy."""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
from contracts.market_data_freshness import FreshnessEvidence, FreshnessPolicy, FreshnessStatus, evaluate_freshness

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "R4_SYNTHETIC_FRESHNESS_THRESHOLD_SWEEP_20261028.json"
BASE = datetime(2026, 10, 28, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
THRESHOLDS = (300, 600, 900, 1800)
AGES = (-3, -1, 0, 1, 30, 59, 60, 299, 300, 301, 599, 600, 601, 899, 900, 901, 1799, 1800, 1801)


def evidence(age_seconds: int, **overrides) -> FreshnessEvidence:
    src = BASE - timedelta(seconds=age_seconds)
    values = dict(
        source="SYNTHETIC_FIXTURE_ONLY", endpoint="synthetic://quote-fixture", tr_id="SYNTHETIC_QUOTE",
        environment="SYNTHETIC", instrument_id="SYNTH-OPT-20261029-C-700", symbol="SYNTH-OPT-20261029-C-700",
        raw_source_time=src.isoformat(), source_instant=src, received_at=BASE,
        raw_payload_sha256=sha256(("synthetic-fixture|" + str(age_seconds)).encode()).hexdigest(),
        source_time_semantics_verified=True, capability_verified=True,
        candidate_policy_version="synthetic-fixture-clock-v1", metadata={"provenance":"synthetic=true"},
    )
    values.update(overrides)
    return FreshnessEvidence(**values)


def main() -> int:
    results = []
    for threshold in THRESHOLDS:
        policy = FreshnessPolicy(f"synthetic-age-{threshold}s-v1", True, timedelta(seconds=threshold), timedelta(0))
        counts = {status.value: 0 for status in FreshnessStatus}
        cases = []
        for age in AGES:
            verdict = evaluate_freshness(evidence(age), policy=policy, expected_environment="SYNTHETIC")
            counts[verdict.status.value] += 1
            cases.append({"age_seconds": age, "status": verdict.status.value, "reason": verdict.reason})
        # Threshold boundary: equal is accepted by current contract; +1s is stale.
        at = evaluate_freshness(evidence(threshold), policy=policy)
        over = evaluate_freshness(evidence(threshold + 1), policy=policy)
        future_over = evaluate_freshness(evidence(-1), policy=policy)
        assert at.status is FreshnessStatus.FRESH, (threshold, at)
        assert over.status is FreshnessStatus.STALE, (threshold, over)
        assert future_over.status is FreshnessStatus.UNKNOWN, (threshold, future_over)
        results.append({"max_age_seconds": threshold, "max_future_skew_seconds": 0,
                        "case_count": len(cases), "status_counts": counts,
                        "boundary_equal": at.status.value, "boundary_plus_1s": over.status.value,
                        "future_plus_1s": future_over.status.value, "cases": cases})
    # Failure controls: missing evidence, identity mismatch, missing capability never FRESH.
    policy = FreshnessPolicy("synthetic-guard-controls-v1", True, timedelta(seconds=600), timedelta(0))
    controls = {}
    controls["missing_evidence"] = evaluate_freshness(None, policy=policy).status.value
    controls["identity_mismatch"] = evaluate_freshness(evidence(0), policy=policy, expected_symbol="OTHER").status.value
    controls["capability_missing"] = evaluate_freshness(evidence(0, capability_verified=False), policy=policy).status.value
    controls["source_semantics_missing"] = evaluate_freshness(evidence(0, source_time_semantics_verified=False), policy=policy).status.value
    assert controls == {"missing_evidence":"UNKNOWN", "identity_mismatch":"IDENTITY_CONFLICT",
                        "capability_missing":"BLOCKED_SOURCE_CAPABILITY", "source_semantics_missing":"UNKNOWN"}, controls
    payload = {
        "experiment":"R4_SYNTHETIC_FRESHNESS_THRESHOLD_SWEEP",
        "status":"PASS_SYNTHETIC_CONTRACT_BOUNDARY_TEST_ONLY",
        "timestamp":"2026-10-28",
        "provenance":{"synthetic":True,"generator_version":"hand-authored-fixture-v1","seed":20261028,
                      "runtime_or_production_policy_modified":False,"real_data_accessed":False},
        "assumptions":{"dataset_resolution_seconds":300,"candidate_thresholds_seconds":list(THRESHOLDS),
                       "candidate_baseline_seconds":600,"max_future_skew_seconds":0,
                       "reason":"600s is two synthetic 5-minute intervals; a sensitivity candidate only, not a market-calibrated threshold."},
        "limitations":["The cases are deterministic hand-authored synthetic timestamp offsets, not sampled REAL_VTS observations.",
                       "This validates the existing freshness contract's boundary semantics only.",
                       "It does not validate KIS source timestamp semantics, source capability, latency distribution, or production eligibility.",
                       "Do not copy any candidate into production configuration without separate evidence and approval."],
        "failure_controls":controls,"sweeps":results,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(encoded, encoding="utf-8")
    print("EXPERIMENT=R4_SYNTHETIC_FRESHNESS_THRESHOLD_SWEEP")
    print("STATUS=PASS_SYNTHETIC_CONTRACT_BOUNDARY_TEST_ONLY")
    print(f"THRESHOLDS_SECONDS={','.join(map(str, THRESHOLDS))}")
    print(f"CASE_COUNT_PER_THRESHOLD={len(AGES)}")
    print("BOUNDARY_RULE=age==threshold:FRESH; age==threshold+1s:STALE; source_future+1s:UNKNOWN")
    print("FAILURE_CONTROLS=" + json.dumps(controls, sort_keys=True))
    print("PRODUCTION_POLICY_MODIFIED=False")
    print("REAL_DATA_ACCESSED=False")
    print(f"OUTPUT={OUT}")
    print(f"OUTPUT_SHA256={sha256(OUT.read_bytes()).hexdigest().upper()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
