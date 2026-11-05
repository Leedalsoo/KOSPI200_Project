from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/derived_scenario/q25_strategy7_8"
PROFILE_PATH = ROOT / "config/validation_only/q25_strategy7_8_risk_profiles.v1.json"
OUT = ROOT / "reports/synth/Q25_STRATEGY7_8_SYNTHETIC_ASSETS_20261103.json"

def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    profiles = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    report = {
        "schema_version": "q25-synthetic-asset-validation-report-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "synthetic datasets and validation-only risk budgets; no Strategy Runtime execution",
        "validation_only": True, "runtime_eligible": False,
        "operational_config_mutated": False,
        "live_or_kis_calls": False,
        "risk_checks_enabled": profiles["risk_checks_enabled"],
        "strategies": {}
    }
    for key, folder_name, profile_key in (
        ("strategy7", "strategy7_weekly", "track7_weekly_insurance"),
        ("strategy8", "strategy8_monthly", "track8_monthly_strangle"),
    ):
        folder = BASE / folder_name
        raw = (folder / "20261103.jsonl").read_bytes()
        manifest_raw = (folder / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        profile = profiles["profiles"][profile_key]
        rows = [json.loads(x) for x in raw.decode("utf-8").splitlines()]
        timeline = {}
        for row in rows:
            t, m = row["tick"], row["scenario_metadata"]
            timeline.setdefault(m["group_id"], {}).setdefault(t["timestamp"], {})[m["leg_id"]] = int(round(t["ask_price"] * t["contract_multiplier"]))
        group_max = {g:max(sum(legs.values()) for legs in times.values() if set(legs)=={"put","call"}) for g,times in timeline.items()}
        if key == "strategy7":
            total_by_time = {}
            for group_times in timeline.values():
                for ts, legs in group_times.items():
                    if set(legs)=={"put","call"}:
                        total_by_time[ts] = total_by_time.get(ts,0)+sum(legs.values())
            peak_exposure = max(total_by_time.values())
        else:
            peak_exposure = max(group_max.values())
        limit = int(profile["max_gross_premium_outlay_krw"])
        reference = int(profile["operational_reference_limit_krw"])
        report["strategies"][key] = {
            "dataset_path": manifest["dataset_path"],
            "dataset_sha256": sha(raw), "manifest_sha256": sha(manifest_raw),
            "rows": len(rows), "groups": manifest["groups"],
            "max_bid_ask_spread_ratio": manifest["max_bid_ask_spread_ratio"],
            "group_peak_gross_premium_krw": group_max,
            "peak_concurrent_exposure_krw": peak_exposure,
            "computed_max_loss_krw": peak_exposure,
            "operational_reference_limit_krw": reference,
            "operational_reference_overage_krw": max(0,peak_exposure-reference),
            "validation_only_budget_krw": limit,
            "validation_budget_overage_krw": max(0,peak_exposure-limit),
            "budget_verdict": "PASS" if peak_exposure <= limit else "BLOCKED_VALIDATION_BUDGET",
            "dataset_verdict": "PASS" if manifest["validation_only"] and not manifest["runtime_eligible"] and float(manifest["max_bid_ask_spread_ratio"]) <= 0.20 else "FAIL"
        }
    all_pass = all(x["budget_verdict"]=="PASS" and x["dataset_verdict"]=="PASS" for x in report["strategies"].values())
    report["asset_and_budget_verdict"] = "PASS" if all_pass else "FAIL"
    report["runtime_lifecycle_verdict"] = "UNVERIFIED_NOT_RUN"
    report["runtime_blockers"] = {
        "strategy7": "Current Strategy 7 state is single-group; independent Monday/Thursday concurrent group lifecycle is not implemented.",
        "strategy8": "Current Strategy 8 DTE_ENTRY/MIN_BUDGET are None and build_execution_plan raises TRACK8_SEQUENTIAL_ENTRY_POLICY_UNRESOLVED. No.1169 confirms DTE>=10 trading days and retires the 200,000 KRW minimum-budget gate, but the strategy code has not been changed in this approved scope."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
