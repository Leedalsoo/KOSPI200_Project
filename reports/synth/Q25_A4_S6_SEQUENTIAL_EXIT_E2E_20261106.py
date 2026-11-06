"""Sequential S6 natural-signal E2E for take-profit/trailing and 15:10 forced close."""
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
DATASET = Path("data/derived_scenario/q25_a3_1_s6_budget_fit")
MANIFEST = Path("reports/synth/Q25_A3_1_S6_BUDGET_FIT_MANIFEST_20261105.json")
RISK_PROFILE = Path("config/validation_only/q25_s6_v1/risk_profile.json")
MAX_EVENTS = 4632
OUTPUT = Path("reports/synth/Q25_A4_S6_SEQUENTIAL_EXIT_E2E_20261106.json")
if OUTPUT.exists() or OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_S6_EXIT_E2E_REPORT")
if not DATASET.is_dir() or not MANIFEST.is_file() or not RISK_PROFILE.is_file():
    raise SystemExit("S6_EXIT_E2E_VALIDATION_INPUT_MISSING")

fields = ("events", "signals", "approved", "routed", "filled", "rejected",
          "execution_ids", "multi_leg_decisions", "strategy_signal_counts",
          "strategy_status", "realized_pnl", "unrealized_pnl", "net_pnl")
runs = {}
states = {}
for mode in ("FAST", "DETAILED"):
    run_id = f"Q25-A4-S6-SEQUENTIAL-EXIT-{mode}-20261106"
    state_file = ROOT / "reports/synth/q25_s6_runtime_state" / f"{run_id}.jsonl"
    trace_file = Path("reports/synth") / f"Q25_A4_S6_SEQUENTIAL_EXIT_{mode}_20261106.trace.jsonl" if mode == "DETAILED" else None
    if state_file.exists() or (trace_file and (ROOT / trace_file).exists()):
        raise SystemExit(f"REFUSE_OVERWRITE_S6_EXIT_RUN:{run_id}")
    runner = HighSpeedVirtualRuntimeReplayRunner(
        DATASET, run_id=run_id,
        strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=MANIFEST,
        validation_only_track6_execution_mode=True,
        validation_only_track6_lifecycle_config=Track6LifecycleConfig(
            first_rank=5, timeout_split="per_order",
        ),
        validation_only_track6_risk_profile=RISK_PROFILE,
        log_mode=ReplayLogMode[mode], trace_output=trace_file,
    )
    runs[mode] = asdict(runner.run(max_events=MAX_EVENTS))
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

trace_text = (ROOT / trace_file).read_text(encoding="utf-8") if trace_file else ""
tag_counts = {
    "trailing_close_put": trace_text.count("DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT"),
    "trailing_close_call": trace_text.count("DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL"),
    "force_close_1510": trace_text.count("DAILY_TAIL_INSURANCE_FORCE_CLOSE"),
}
equivalent = all(runs["FAST"].get(field) == runs["DETAILED"].get(field) for field in fields)
state = states["FAST"]
flat = bool(state and state["status"] == "FLAT_CONFIRMED"
            and state["open_quantity"] == {"put": 0, "call": 0})
no_rejects = runs["FAST"]["rejected"] == 0 and runs["DETAILED"]["rejected"] == 0
no_runtime_failures = all(
    row.get("runtime_failures", 0) == 0
    for report in runs.values() for row in report["strategy_status"]
    if row.get("strategy_id") == "track6_daily_tail_insurance"
)
trailing_seen = tag_counts["trailing_close_put"] + tag_counts["trailing_close_call"] > 0
force_close_seen = tag_counts["force_close_1510"] > 0
verdict = "PSB_PASS" if all((equivalent, flat, no_rejects, no_runtime_failures,
                             trailing_seen, force_close_seen, runs["FAST"]["filled"] > 0)) else (
    "PSB_FAIL" if not equivalent or not no_rejects or not no_runtime_failures else "PSB_UNVERIFIED"
)
payload = {
    "schema_version": 1,
    "authority": "VALIDATION_ONLY_SYNTHETIC_NON_AUTHORITATIVE",
    "verdict": verdict,
    "dataset": str(DATASET),
    "manifest": str(MANIFEST),
    "risk_profile": str(RISK_PROFILE),
    "max_events": MAX_EVENTS,
    "matrix": "FAST vs DETAILED; first_rank=5; timeout_split=per_order",
    "comparison_fields": list(fields),
    "fast_detailed_equivalent": equivalent,
    "flat_confirmed": flat,
    "no_rejected_orders": no_rejects,
    "no_runtime_failures": no_runtime_failures,
    "trailing_exit_observed": trailing_seen,
    "force_close_1510_observed": force_close_seen,
    "detailed_trace_tag_counts": tag_counts,
    "state": states,
    "runs": runs,
}
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
print(json.dumps({
    "output": str(OUTPUT), "sha256": digest, "verdict": verdict,
    "equivalent": equivalent, "flat": flat, "trailing_tags": tag_counts,
    "events": runs["FAST"]["events"], "signals": runs["FAST"]["signals"],
    "filled": runs["FAST"]["filled"], "rejected": runs["FAST"]["rejected"],
}, ensure_ascii=False), flush=True)
