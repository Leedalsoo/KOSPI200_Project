"""Q25 A4 S6 Runtime matrix: first_rank x timeout_split, Fast/Detailed paired runs."""
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.strategy.track6_order_lifecycle import Track6LifecycleConfig
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.high_speed.track6_validation_state_store import Track6ValidationStateStore

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path("data/derived_scenario/q25_a2_1_strategy6")
MANIFEST = Path("reports/synth/Q25_A3_2_S6_ORIGINAL_DATA_SYNTHETIC_CAL_MANIFEST_20261105.json")
RISK_PROFILE = Path("config/validation_only/q25_s6_v1/risk_profile.json")
MAX_EVENTS = 37056
OUTPUT = Path("reports/synth/Q25_A4_S6_RUNTIME_MATRIX_20261106.json")
if OUTPUT.exists() or OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_EXISTING_MATRIX_REPORT")
if not DATASET.is_dir() or not MANIFEST.is_file() or not RISK_PROFILE.is_file():
    raise SystemExit("S6_MATRIX_VERIFIED_INPUTS_MISSING")

manifest_hash = hashlib.sha256((ROOT / MANIFEST).read_bytes()).hexdigest()
risk_hash = hashlib.sha256((ROOT / RISK_PROFILE).read_bytes()).hexdigest()
cases = []
comparison_fields = (
    "events", "signals", "approved", "routed", "filled", "rejected",
    "execution_ids", "multi_leg_decisions", "strategy_signal_counts",
    "strategy_status", "realized_pnl", "unrealized_pnl", "net_pnl",
)

for first_rank in (5, 6):
    for timeout_split in ("per_order", "shared_elapsed"):
        pair = {}
        state_summaries = {}
        for mode in ("FAST", "DETAILED"):
            run_id = f"Q25-A4-S6-R{first_rank}-{timeout_split}-{mode}-v3"
            state_path = ROOT / "reports/synth/q25_s6_runtime_state" / f"{run_id}.jsonl"
            trace_path = (
                Path("reports/synth") / f"Q25_A4_S6_R{first_rank}_{timeout_split}_{mode}_v3.trace.jsonl"
                if mode == "DETAILED" else None
            )
            if state_path.exists() or (trace_path is not None and (ROOT / trace_path).exists()):
                raise SystemExit(f"REFUSE_OVERWRITE_EXISTING_RUN_ARTIFACT:{run_id}")
            runner = HighSpeedVirtualRuntimeReplayRunner(
                DATASET,
                run_id=run_id,
                strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
                validation_only_synthetic=True,
                validation_only_synthetic_manifest=MANIFEST,
                validation_only_track6_execution_mode=True,
                validation_only_track6_lifecycle_config=Track6LifecycleConfig(
                    first_rank=first_rank,
                    timeout_split=timeout_split,
                ),
                validation_only_track6_risk_profile=RISK_PROFILE,
                log_mode=ReplayLogMode[mode],
                trace_output=trace_path,
            )
            report = runner.run(max_events=MAX_EVENTS)
            pair[mode] = asdict(report)
            store = Track6ValidationStateStore(
                ROOT / "reports/synth/q25_s6_runtime_state", run_id=run_id,
            )
            latest = store.load_latest()
            state_summaries[mode] = (
                {
                    "sequence": latest["sequence"],
                    "record_sha256": latest["record_sha256"],
                    "status": latest["snapshot"]["status"],
                    "selected_rank": latest["snapshot"]["selected_rank"],
                    "available_candidate_ranks": latest["snapshot"]["available_candidate_ranks"],
                    "open_quantity": latest["snapshot"]["open_quantity"],
                    "last_reason": latest["snapshot"]["last_reason"],
                } if latest else None
            )

        fast = pair["FAST"]
        detailed = pair["DETAILED"]
        equivalent = all(fast.get(field) == detailed.get(field) for field in comparison_fields)
        final_state = state_summaries["FAST"]
        flat = bool(final_state and final_state["status"] == "FLAT_CONFIRMED"
                    and final_state["open_quantity"] == {"put": 0, "call": 0})
        no_rejects = fast["rejected"] == 0 and detailed["rejected"] == 0
        no_runtime_failures = all(
            row.get("runtime_failures", 0) == 0
            for row in fast["strategy_status"] + detailed["strategy_status"]
            if row.get("strategy_id") == "track6_daily_tail_insurance"
        )
        verdict = "PSB_PASS" if equivalent and flat and no_rejects and no_runtime_failures and fast["filled"] > 0 else (
            "PSB_FAIL" if not equivalent or not no_rejects or not no_runtime_failures else "PSB_UNVERIFIED"
        )
        cases.append({
            "first_rank": first_rank,
            "timeout_split": timeout_split,
            "verdict": verdict,
            "fast_detailed_equivalent": equivalent,
            "flat_confirmed": flat,
            "no_rejected_orders": no_rejects,
            "no_runtime_failures": no_runtime_failures,
            "state": state_summaries,
            "comparison_fields": list(comparison_fields),
            "fast": fast,
            "detailed": detailed,
        })
        print(json.dumps({
            "case": [first_rank, timeout_split],
            "verdict": verdict,
            "equivalent": equivalent,
            "fast": {k: fast[k] for k in ("events", "signals", "routed", "filled", "rejected", "net_pnl")},
            "state": state_summaries,
        }, ensure_ascii=False, default=str), flush=True)

payload = {
    "schema_version": 1,
    "authority": "VALIDATION_ONLY_SYNTHETIC_NON_AUTHORITATIVE",
    "matrix": "first_rank(5|6) x timeout_split(per_order|shared_elapsed)",
    "fast_detailed_comparison_fields": list(comparison_fields),
    "dataset": str(DATASET),
    "dataset_sha256": json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))["output_sha256"],
    "manifest": str(MANIFEST),
    "manifest_sha256": manifest_hash,
    "risk_profile": str(RISK_PROFILE),
    "risk_profile_sha256": risk_hash,
    "max_events": MAX_EVENTS,
    "cases": cases,
}
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
print(json.dumps({"output": str(OUTPUT), "sha256": digest,
                  "case_verdicts": [item["verdict"] for item in cases]}, ensure_ascii=False), flush=True)
