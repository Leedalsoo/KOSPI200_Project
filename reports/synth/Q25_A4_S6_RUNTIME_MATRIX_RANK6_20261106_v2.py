"""Run the full Q25 A4 S6 first-rank x timeout-split matrix with both synthetic candidates listed."""
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
DATASET = Path("data/derived_scenario/q25_a4_s6_rank5_rank6_v2")
MANIFEST = Path("reports/synth/Q25_A4_S6_RANK5_RANK6_MANIFEST_20261106_v2.json")
RISK_PROFILE = Path("config/validation_only/q25_s6_a4_rank6_v2/risk_profile.json")
MAX_EVENTS = 43232
OUTPUT = Path("reports/synth/Q25_A4_S6_RUNTIME_MATRIX_RANK6_20261106_v2.json")
if OUTPUT.exists() or OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_RANK6_MATRIX_REPORT")
manifest_hash = hashlib.sha256((ROOT / MANIFEST).read_bytes()).hexdigest()
risk_hash = hashlib.sha256((ROOT / RISK_PROFILE).read_bytes()).hexdigest()
dataset_hash = hashlib.sha256((ROOT / DATASET / "20261102.jsonl").read_bytes()).hexdigest()
cases = []
fields = (
    "events", "signals", "approved", "routed", "filled", "rejected",
    "execution_ids", "multi_leg_decisions", "strategy_signal_counts",
    "strategy_status", "realized_pnl", "unrealized_pnl", "net_pnl",
)
for first_rank in (5, 6):
    for timeout_split in ("per_order", "shared_elapsed"):
        pair, states = {}, {}
        for mode in ("FAST", "DETAILED"):
            run_id = f"Q25-A4-S6-RANK6-V2-R{first_rank}-{timeout_split}-{mode}-v2"
            state_file = ROOT / "reports/synth/q25_s6_runtime_state" / f"{run_id}.jsonl"
            trace_file = Path("reports/synth") / f"Q25_A4_S6_RANK6_R{first_rank}_{timeout_split}_{mode}_v2.trace.jsonl" if mode == "DETAILED" else None
            if state_file.exists() or (trace_file and (ROOT / trace_file).exists()):
                raise SystemExit(f"REFUSE_OVERWRITE_RANK6_RUN:{run_id}")
            runner = HighSpeedVirtualRuntimeReplayRunner(
                DATASET, run_id=run_id,
                strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
                validation_only_synthetic=True,
                validation_only_synthetic_manifest=MANIFEST,
                validation_only_track6_execution_mode=True,
                validation_only_track6_lifecycle_config=Track6LifecycleConfig(
                    first_rank=first_rank, timeout_split=timeout_split,
                ),
                validation_only_track6_risk_profile=RISK_PROFILE,
                log_mode=ReplayLogMode[mode], trace_output=trace_file,
            )
            report = runner.run(max_events=MAX_EVENTS)
            pair[mode] = asdict(report)
            latest = Track6ValidationStateStore(
                ROOT / "reports/synth/q25_s6_runtime_state", run_id=run_id,
            ).load_latest()
            states[mode] = ({
                "sequence": latest["sequence"],
                "record_sha256": latest["record_sha256"],
                "status": latest["snapshot"]["status"],
                "selected_rank": latest["snapshot"]["selected_rank"],
                "available_candidate_ranks": latest["snapshot"]["available_candidate_ranks"],
                "open_quantity": latest["snapshot"]["open_quantity"],
                "last_reason": latest["snapshot"]["last_reason"],
            } if latest else None)
        fast, detailed = pair["FAST"], pair["DETAILED"]
        equivalent = all(fast.get(field) == detailed.get(field) for field in fields)
        state = states["FAST"]
        both_candidates = bool(state and {5, 6}.issubset(set(state["available_candidate_ranks"])))
        rank_selected = bool(state and state["selected_rank"] == first_rank)
        flat = bool(state and state["status"] == "FLAT_CONFIRMED" and state["open_quantity"] == {"put": 0, "call": 0})
        no_rejects = fast["rejected"] == 0 and detailed["rejected"] == 0
        no_failures = all(row.get("runtime_failures", 0) == 0 for row in fast["strategy_status"] + detailed["strategy_status"] if row.get("strategy_id") == "track6_daily_tail_insurance")
        verdict = "PSB_PASS" if all((equivalent, both_candidates, rank_selected, flat, no_rejects, no_failures, fast["filled"] > 0)) else ("PSB_FAIL" if not equivalent or not no_rejects or not no_failures else "PSB_UNVERIFIED")
        cases.append({
            "first_rank": first_rank, "timeout_split": timeout_split, "verdict": verdict,
            "fast_detailed_equivalent": equivalent, "both_rank_candidates_available": both_candidates,
            "configured_rank_selected": rank_selected, "flat_confirmed": flat,
            "no_rejected_orders": no_rejects, "no_runtime_failures": no_failures,
            "state": states, "comparison_fields": list(fields), "fast": fast, "detailed": detailed,
        })
        print(json.dumps({
            "case": [first_rank, timeout_split], "verdict": verdict,
            "equivalent": equivalent, "both_candidates": both_candidates,
            "selected_rank": state.get("selected_rank") if state else None,
            "available_ranks": state.get("available_candidate_ranks") if state else None,
            "events": fast["events"], "signals": fast["signals"], "filled": fast["filled"],
            "rejected": fast["rejected"], "net_pnl": fast["net_pnl"],
        }, ensure_ascii=False, default=str), flush=True)
payload = {
    "schema_version": 1, "authority": "VALIDATION_ONLY_SYNTHETIC_NON_AUTHORITATIVE",
    "matrix": "first_rank(5|6) x timeout_split(per_order|shared_elapsed)",
    "dataset": str(DATASET), "dataset_sha256": dataset_hash,
    "manifest": str(MANIFEST), "manifest_sha256": manifest_hash,
    "risk_profile": str(RISK_PROFILE), "risk_profile_sha256": risk_hash,
    "max_events": MAX_EVENTS, "required_candidate_ranks": [5, 6],
    "rank_selection_required_for_psb_pass": True,
    "fast_detailed_comparison_fields": list(fields), "cases": cases,
}
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
print(json.dumps({"output": str(OUTPUT), "sha256": digest, "case_verdicts": [x["verdict"] for x in cases]}, ensure_ascii=False), flush=True)