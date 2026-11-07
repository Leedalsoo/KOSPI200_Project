from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
DATA_ROOT = ROOT / "data" / "derived_scenario" / "q25_a5_s09_s8_exit_scenarios"
CONFIG_ROOT = ROOT / "config" / "validation_only" / "q25_a5_s09_s8_exit_scenarios"
REPORT_PATH = ROOT / "reports" / "synth" / "Q25_A5_S09_S8_EXIT_SCENARIO_GENERATION_20261107.json"

KST = timezone(timedelta(hours=9))
EXPIRY = "20261119"
ENTRY_DATE = "2026-11-05"
MULTIPLIER = Decimal("250000")
STRIKES = (("PUT", Decimal("485")), ("CALL", Decimal("515")),
           ("PUT", Decimal("500")), ("CALL", Decimal("500")))
DTE_BY_DATE = {
    "2026-11-05": 10,
    "2026-11-06": 9,
    "2026-11-09": 8,
    "2026-11-10": 7,
    "2026-11-11": 6,
    "2026-11-12": 5,
    "2026-11-13": 4,
    "2026-11-16": 3,
    "2026-11-17": 2,
    "2026-11-18": 1,
    "2026-11-19": 0,
}
TRADING_DAYS = list(DTE_BY_DATE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def write_or_verify(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"Existing S09 artifact differs; refusing to overwrite: {path}")
        return
    write_exclusive(path, data)


def write_json_exclusive(path: Path, value: Any) -> str:
    raw = json_bytes(value)
    write_or_verify(path, raw)
    digest = sha256(raw)
    write_or_verify(path.with_name(path.name + ".sha256"), f"{digest}  {path.name}\n".encode("ascii"))
    return digest


def kst_timestamp(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}+09:00")


SCENARIOS = (
    {
        "key": "stop",
        "scenario_id": "Q25_A5_S09_S8_STOP_20261107",
        "group_id": "S8_A5_S09_STOP_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:10:00"): {"CALL": Decimal("0.40"), "PUT": Decimal("1.00")},
        },
        "expectation": {
            "trigger_timestamp": "2026-11-05T09:10:00+09:00",
            "expected_exit_reason": "CALL_LEG_50PCT_ENTRY_FILL_STOP",
            "selected_leg": "CALL",
            "scenario_reference_entry_ask": "1.05",
            "scenario_reference_stop_threshold": "0.525",
            "trigger_mark": "0.40",
            "formula": "actual_call_mark <= actual_call_entry_fill_price * 0.50",
            "actual_virtual_fill_price_required_in_s10": True,
        },
    },
    {
        "key": "trailing",
        "scenario_id": "Q25_A5_S09_S8_TRAILING_20261107",
        "group_id": "S8_A5_S09_TRAILING_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("0.90"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:10:00"): {"CALL": Decimal("2.20"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:20:00"): {"CALL": Decimal("2.50"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:30:00"): {"CALL": Decimal("2.20"), "PUT": Decimal("1.00")},
        },
        "expectation": {
            "activation_timestamp": "2026-11-05T09:10:00+09:00",
            "high_water_timestamp": "2026-11-05T09:20:00+09:00",
            "trigger_timestamp": "2026-11-05T09:30:00+09:00",
            "expected_exit_reason": "CALL_LEG_2X_ARMED_10PCT_DRAWDOWN",
            "selected_leg": "CALL",
            "scenario_reference_entry_ask": "0.95",
            "scenario_reference_activation_threshold": "1.90",
            "activation_mark": "2.20",
            "high_water_mark": "2.50",
            "scenario_reference_drawdown_threshold": "2.25",
            "trigger_mark": "2.20",
            "drawdown_fraction_from_high_water": "0.12",
            "formula": "actual_call_mark >= actual_call_entry_fill_price * 2.0, then actual_call_mark <= high_water_mark * 0.90",
            "actual_virtual_fill_price_required_in_s10": True,
        },
    },
    {
        "key": "expiry",
        "scenario_id": "Q25_A5_S09_S8_EXPIRY_20261107",
        "group_id": "S8_A5_S09_EXPIRY_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:10:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-19", "15:09:59"): {"CALL": Decimal("1.10"), "PUT": Decimal("1.10")},
            ("2026-11-19", "15:10:00"): {"CALL": Decimal("1.10"), "PUT": Decimal("1.10")},
        },
        "expectation": {
            "pre_cutoff_timestamp": "2026-11-19T15:09:59+09:00",
            "trigger_timestamp": "2026-11-19T15:10:00+09:00",
            "expected_exit_reason": "MONTHLY_EXPIRY_15:10_FORCE_CLOSE",
            "expiry": EXPIRY,
            "both_legs_expected_open_before_cutoff": True,
            "mark_at_cutoff": "1.10",
            "scenario_reference_entry_ask": "1.05",
            "no_stop_or_trailing_at_cutoff": True,
            "formula": "expiry_date == KST market date and KST time >= 15:10:00",
            "actual_virtual_fill_price_required_in_s10": True,
        },
    },
)


def build_rows(scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], bytes]:
    rows: list[dict[str, Any]] = []
    seq = 0
    for (day, clock), selected_marks in sorted(scenario["event_marks"].items()):
        observed = kst_timestamp(day, clock)
        dte = DTE_BY_DATE[day]
        for option_type, strike in STRIKES:
            seq += 1
            selected_strike = (option_type == "CALL" and strike == Decimal("515")) or (
                option_type == "PUT" and strike == Decimal("485")
            )
            mark = selected_marks[option_type] if selected_strike else Decimal("1.00")
            mark = mark.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            bid = (mark * Decimal("0.95")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ask = (mark * Decimal("1.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            identity = (
                f"SYNTHETIC_CONTRACT:S8A5S09:{scenario['key'].upper()}:"
                f"{EXPIRY}:{option_type}:{strike}"
            )
            rows.append({
                "schema": "reference-canonical-market-tick-v1",
                "provenance": "DERIVED_SCENARIO",
                "synthetic": True,
                "tick": {
                    "timestamp": observed.isoformat(),
                    "underlying_price": 500.0,
                    "underlying_symbol": "KOSPI200_SYNTHETIC",
                    "underlying_observed_hour": observed.strftime("%Y%m%d%H"),
                    "underlying_source": "SYNTHETIC:q25-a5-s09-s8-exit-scenario-generator",
                    "strike_price": float(strike),
                    "option_type": option_type,
                    "contract_multiplier": float(MULTIPLIER),
                    "bid_price": float(bid),
                    "ask_price": float(ask),
                    "last_price": float(mark),
                    "volume": 100 + seq,
                    "seq_id": seq,
                    "expiry": EXPIRY,
                    "symbol": identity,
                    "instrument_id": identity,
                    "synthetic_contract_id": identity,
                    "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
                    "source_instrument_code": identity,
                    "option_source": "SYNTHETIC",
                    "implied_volatility": 0.25,
                    "delta": -0.35 if option_type == "PUT" else 0.35,
                    "gamma": 0.01,
                    "theta": -0.01,
                    "vega": 0.2,
                    "contract_class": "monthly",
                },
                "scenario_metadata": {
                    "instrument_family": "STANDARD",
                    "product_series": "MONTHLY",
                    "source_type": "DERIVED_SCENARIO",
                    "runtime_eligible": False,
                    "validation_only": True,
                    "scenario_id": scenario["scenario_id"],
                    "group_id": scenario["group_id"],
                    "leg_id": option_type.lower(),
                    "regime": "NORMAL",
                    "dte_trading_days": dte,
                    "expiry_is_authoritative": False,
                    "contract_identity_authority": "SYNTHETIC_ONLY",
                    "group_entry_date": ENTRY_DATE,
                    "scenario_phase": "ENTRY_SETUP" if day == ENTRY_DATE else "EXIT_OBSERVATION",
                    "purpose": "S8 stop/trailing/expiry validation-only scenario; not KIS or exchange market data.",
                },
            })
    raw = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    return rows, raw


def validate_rows(scenario: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [row["tick"]["timestamp"] for row in rows]
    seq_ids = [row["tick"]["seq_id"] for row in rows]
    if timestamps != sorted(timestamps):
        raise ValueError(f"{scenario['key']}: timestamps are not ordered")
    if len(seq_ids) != len(set(seq_ids)):
        raise ValueError(f"{scenario['key']}: duplicate seq_id")
    by_time: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tick = row["tick"]
        if row["provenance"] != "DERIVED_SCENARIO" or row["scenario_metadata"]["validation_only"] is not True:
            raise ValueError(f"{scenario['key']}: provenance boundary failed")
        if tick["bid_price"] <= 0 or tick["ask_price"] <= tick["bid_price"] or tick["last_price"] <= 0:
            raise ValueError(f"{scenario['key']}: invalid quote")
        if tick["expiry"] != EXPIRY or tick["contract_multiplier"] != float(MULTIPLIER):
            raise ValueError(f"{scenario['key']}: identity fields inconsistent")
        by_time.setdefault(tick["timestamp"], []).append(row)
    for timestamp, group in by_time.items():
        identities = {row["tick"]["instrument_id"] for row in group}
        if len(group) != 4 or len(identities) != 4:
            raise ValueError(f"{scenario['key']}: incomplete same-timestamp quote set at {timestamp}")
    if scenario["key"] == "stop":
        ref_threshold = Decimal(scenario["expectation"]["scenario_reference_stop_threshold"])
        trigger = Decimal(scenario["expectation"]["trigger_mark"])
        if trigger > ref_threshold:
            raise ValueError("stop scenario does not cross the 50% reference threshold")
    elif scenario["key"] == "trailing":
        e = scenario["expectation"]
        if Decimal(e["activation_mark"]) < Decimal(e["scenario_reference_activation_threshold"]):
            raise ValueError("trailing scenario does not reach 2x activation")
        if Decimal(e["trigger_mark"]) > Decimal(e["scenario_reference_drawdown_threshold"]):
            raise ValueError("trailing scenario does not reach 10% drawdown")
    elif scenario["key"] == "expiry":
        pre = datetime.fromisoformat(scenario["expectation"]["pre_cutoff_timestamp"])
        cutoff = datetime.fromisoformat(scenario["expectation"]["trigger_timestamp"])
        if pre.date().strftime("%Y%m%d") != EXPIRY or cutoff.date().strftime("%Y%m%d") != EXPIRY:
            raise ValueError("expiry scenario date mismatch")
        if pre.time() >= time(15, 10) or cutoff.time() != time(15, 10):
            raise ValueError("expiry scenario cutoff boundary mismatch")
        if any(datetime.fromisoformat(ts).date().strftime("%Y%m%d") > EXPIRY for ts in timestamps):
            raise ValueError("post-expiry rows are not allowed")
    return {
        "row_count": len(rows),
        "event_timestamp_count": len(by_time),
        "unique_seq_ids": len(set(seq_ids)),
        "same_timestamp_quote_sets_complete": True,
        "quote_values_valid": True,
        "scenario_trigger_design_check": "PASS",
    }


def main() -> None:
    if REPORT_PATH.exists():
        raise FileExistsError("S09 report already exists; refusing to overwrite prior artifacts")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        key = scenario["key"]
        data_folder = DATA_ROOT / key
        risk_folder = CONFIG_ROOT / key
        data_folder.mkdir(exist_ok=True)
        risk_folder.mkdir(exist_ok=True)

        rows, raw = build_rows(scenario)
        validation = validate_rows(scenario, rows)
        dataset_name = "20261107.jsonl"
        dataset_path = data_folder / dataset_name
        dataset_rel = dataset_path.relative_to(ROOT).as_posix()
        manifest_path = data_folder / "manifest.json"
        manifest_rel = manifest_path.relative_to(ROOT).as_posix()
        risk_path = risk_folder / "risk_profile.json"
        risk_rel = risk_path.relative_to(ROOT).as_posix()

        write_or_verify(dataset_path, raw)
        dataset_hash = sha256(raw)
        write_or_verify(dataset_path.with_name(dataset_name + ".sha256"),
                        f"{dataset_hash}  {dataset_name}\n".encode("ascii"))

        manifest = {
            "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
            "scenario_id": scenario["scenario_id"],
            "strategy_id": "strategy8_monthly",
            "source_type": "DERIVED_SCENARIO",
            "provenance": "DERIVED_SCENARIO",
            "synthetic": True,
            "validation_only": True,
            "runtime_eligible": False,
            "production_runtime_eligible": False,
            "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "validation_identity_namespace": f"SYNTHETIC_CONTRACT:S8A5S09:{key.upper()}:",
            "expiry_is_authoritative": False,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "dataset_path": dataset_rel,
            "dataset_sha256": dataset_hash,
            "output_sha256": dataset_hash,
            "output_bytes": len(raw),
            "output_path": dataset_rel,
            "rows": len(rows),
            "groups": [scenario["group_id"]],
            "scenario_regime": "NORMAL",
            "scenario_kind": f"S8_{key.upper()}_EXIT",
            "seed": 20261107,
            "date_start": ENTRY_DATE,
            "date_end": EXPIRY[:4] + "-" + EXPIRY[4:6] + "-" + EXPIRY[6:8],
            "date_end_exclusive": "2026-11-20",
            "trading_calendar": {
                "calendar_id": f"S8_A5_S09_{key.upper()}_SYNTHETIC_CALENDAR",
                "source_type": "SYNTHETIC",
                "authoritative": False,
                "timezone": "Asia/Seoul",
                "trading_days": TRADING_DAYS,
                "provenance": "Explicit validation-only schedule; not KIS or KRX authoritative calendar.",
            },
            "session_times_kst": sorted({datetime.fromisoformat(row["tick"]["timestamp"]).strftime("%H:%M:%S") for row in rows}),
            "strategy_policy_inputs": {
                "strategy8_min_entry_dte_trading_days": 10,
                "strategy8_stop_loss_fraction": 0.50,
                "strategy8_trailing_activation_multiple": 2.0,
                "strategy8_trailing_drawdown_fraction": 0.10,
                "strategy8_expiry_force_close_time_kst": "15:10:00",
                "strategy8_expiry_close_priority": "BEFORE_PER_LEG_STOP_AND_TRAILING",
                "strategy8_entry_timeout_minutes": 10,
                "strategy8_entry_retry_window_trading_days": 3,
                "strategy8_third_day_cutoff_kst": "15:00:00",
                "strategy8_retry_interval_minutes": None,
                "strategy8_max_attempts_per_leg": None,
                "policy_scope": "VALIDATION_ONLY_SCENARIO_ASSUMPTIONS; not production configuration.",
            },
            "policy_sources": [
                "No.1169: DTE >= 10 trading days; 200,000 KRW minimum-budget gate retired; 10-minute timeout timer; 3-trading-day retry window; third-day 15:00 KST cutoff. Retry interval and attempt count remain UNSET.",
                "No.1235 Strategy 8 v0.3: 50% per-leg stop, 2x activation then 10% high-water drawdown, monthly expiry 15:10 close are user-intent scenario assumptions; document remains draft/unapproved.",
            ],
            "scenario_expectations": scenario["expectation"],
            "scenario_reference_only": {
                "selected_call_strike": "515",
                "selected_put_strike": "485",
                "contract_multiplier": "250000",
                "entry_reference_is_ask_not_actual_fill": True,
                "actual_virtual_fill_and_exit_reason_must_be_checked_in_s10": True,
            },
            "risk_profile_path": risk_rel,
            "market_rule_limitations": [
                "All prices and quotes are synthetic validation inputs.",
                "0.01 price quantization is for deterministic scenario construction only; exchange tick/price-limit compliance is not asserted.",
                "Contract identity, multiplier, expiry and trading calendar remain non-authoritative synthetic values.",
                "No KIS, REAL_VTS, Live, account, or order API evidence is included.",
            ],
        }

        risk_profile = {
            "allow_kis_api": False,
            "allow_live_orders": False,
            "allow_real_account": False,
            "audit_fields_required": [
                "computed_gross_premium_krw", "computed_max_loss_krw",
                "computed_concurrent_exposure_krw", "operational_reference_overage_krw",
                "validation_budget_overage_krw", "run_id", "scenario_id",
                "manifest_sha256", "dataset_sha256",
            ],
            "currency": "KRW",
            "enforcement_mode": "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT",
            "operational_config_mutated": False,
            "operational_config_path": "config/risk/option-hedge-risk.v1.json",
            "profiles": {
                "track8_monthly_strangle": {
                    "budget_basis": "one CALL + one PUT BUY pair; max loss capped at premium paid; validation-only reference cap copied from existing S8 V3 profile",
                    "dataset_manifest": manifest_rel,
                    "entry_policy": "No.1169 DTE >= 10 trading days; 200,000 KRW minimum-budget gate retired.",
                    "max_concurrent_groups": 1,
                    "max_gross_premium_outlay_krw": 2300000,
                    "max_loss_krw": 2300000,
                    "operational_reference_limit_krw": 250000,
                }
            },
            "risk_checks_enabled": True,
            "runtime_eligible": False,
            "schema_version": "q25-validation-only-risk-profile-v1",
            "validation_only": True,
            "fee_model_status": "NOT_DEFINED_BY_S09_DATASET_GENERATION",
        }
        risk_hash = write_json_exclusive(risk_path, risk_profile)
        manifest["risk_profile_sha256"] = risk_hash
        manifest_hash = write_json_exclusive(manifest_path, manifest)

        # Re-open through the production-shaped validation-only adapter. This checks
        # manifest/dataset/risk-profile binding without running Strategy/Runtime E2E.
        from environments.high_speed.validation_only_s8_runtime_adapter import S8ValidationOnlyRuntimeAdapter
        adapter = S8ValidationOnlyRuntimeAdapter(
            dataset=data_folder,
            manifest_path=manifest_path,
            risk_profile_path=risk_path,
        )
        validation["adapter_manifest_profile_binding"] = "PASS"
        validation["adapter_scenario_id"] = adapter.evidence.scenario_id
        validation["adapter_dataset_sha256"] = adapter.evidence.dataset_sha256

        results.append({
            "scenario_key": key,
            "scenario_id": scenario["scenario_id"],
            "group_id": scenario["group_id"],
            "dataset_path": dataset_rel,
            "dataset_sha256": dataset_hash,
            "dataset_sha256_sidecar": dataset_path.name + ".sha256",
            "manifest_path": manifest_rel,
            "manifest_sha256": manifest_hash,
            "manifest_sha256_sidecar": "manifest.json.sha256",
            "risk_profile_path": risk_rel,
            "risk_profile_sha256": risk_hash,
            "risk_profile_sha256_sidecar": "risk_profile.json.sha256",
            "validation": validation,
            "expectation": scenario["expectation"],
        })

    report = {
        "report_id": "Q25_A5_S09_S8_EXIT_SCENARIO_GENERATION_20261107",
        "stage": "S09",
        "status": "PASS_DATA_GENERATION_AND_MANIFEST_BINDING_ONLY",
        "runtime_exit_e2e_status": "NOT_RUN",
        "strategy_exit_behavior_status": "NOT_VERIFIED_BY_S09",
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "created_at_kst": datetime.now(KST).isoformat(),
        "scenario_count": len(results),
        "scenario_results": results,
        "limitations": [
            "S09 validates generated dataset structure, scenario thresholds and manifest/risk-profile hash binding only.",
            "Actual Virtual fill prices, StrategyHub exit signals, OMS close orders, Position/PnL and Fast/Detailed equivalence are deferred to S10.",
            "Scenario reference entry asks are not actual fill prices; S10 must evaluate thresholds against observed Virtual executions.",
            "S8 v0.3 exit values are represented as validation-only scenario assumptions, not production-approved configuration.",
            "No.1169 retry interval and maximum attempt count remain UNSET and are not exercised.",
            "Synthetic expiry, contract identity, multiplier and trading calendar are not authoritative.",
        ],
        "safety": {
            "kis_api_called": False,
            "real_vts_used": False,
            "live_used": False,
            "real_account_used": False,
            "real_order_api_called": False,
            "operational_risk_config_changed": False,
            "existing_dataset_overwritten": False,
        },
    }
    report_hash = write_json_exclusive(REPORT_PATH, report)
    print(json.dumps({
        "status": report["status"],
        "report_path": REPORT_PATH.relative_to(ROOT).as_posix(),
        "report_sha256": report_hash,
        "scenarios": results,
        "runtime_exit_e2e_status": report["runtime_exit_e2e_status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()