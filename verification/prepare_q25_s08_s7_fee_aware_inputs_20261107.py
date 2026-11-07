from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
TARGET = ROOT / "data/derived_scenario/q25_s08_s7_fee_authority"
PROFILE_SOURCE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"
PROFILE_TARGET = ROOT / "config/validation_only/q25_s08_s7_fee_authority/risk_profile.json"

MODEL = {
    "model_id": "KIS_STANDARD_BRANCH_ONLINE_KOSPI200_OPTION_2025_10_27",
    "source": "KIS public standard branch-account online fee schedule, 2025-10-27",
    "source_url": "https://securities.koreainvestment.com/main/customer/guide/_static/TF04ae010000.jsp?tab=1",
    "tax_source_url": "https://securities.koreainvestment.com/main/customer/guide/_static/TF04ae050000.shtm",
    "session": "DAY",
    "product": "KOSPI200_OPTION_AND_WEEKLY",
    "broker_rate_below_10m": "0.00382900",
    "broker_rate_at_least_10m": "0.00282900",
    "exchange_rate_middle_price_tier": "0.00012654",
    "low_price_threshold_points": "0.42",
    "high_price_threshold_points": "2.47",
    "low_price_exchange_fee_krw_per_contract": 13,
    "high_price_exchange_fee_krw_per_contract": 78,
    "middle_price_total_rate_below_10m": "0.00395554",
    "middle_price_total_rate_at_least_10m": "0.00295554",
    "rounding": "ROUND_HALF_UP_PER_EXECUTION",
    "derivatives_transaction_tax_rate": "0",
    "derivatives_transaction_tax_status": "NO_SECURITIES_TRANSACTION_TAX",
    "included_in_premium_cap": False,
    "included_in_net_pnl": True,
    "account_scope": "REFERENCE_BENCHMARK_ONLY_NOT_USER_ACCOUNT_NEGOTIATED_RATE",
}

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    source_data = SOURCE / "20261103.jsonl"
    output_data = TARGET / "20261103.jsonl"
    if output_data.exists() or (TARGET / "manifest.json").exists() or PROFILE_TARGET.exists():
        raise FileExistsError("S08_FEE_AUTHORITY_OUTPUT_ALREADY_EXISTS")

    rows = []
    with source_data.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.setdefault("scenario_metadata", {})
            meta["validation_identity_owner"] = "Q25_S7_SYNTHETIC_OPTION_MASTER"
            meta["validation_identity_owner_status"] = "CONFIRMED_VALIDATION_ONLY"
            meta["scenario_expiry_authority"] = "STRATEGY7_WEEKLY_SYNTHETIC_CALENDAR_V2"
            meta["scenario_expiry_authority_status"] = "CONFIRMED_VALIDATION_ONLY"
            meta["scenario_expiry_authoritative_within_scenario"] = True
            rows.append(row)

    if len(rows) != 216:
        raise AssertionError(f"EXPECTED_216_ROWS_GOT_{len(rows)}")
    expiries = sorted({str(r["tick"]["expiry"]) for r in rows})
    groups = sorted({str(r["scenario_metadata"]["group_id"]) for r in rows})
    identities = {}
    for row in rows:
        tick = row["tick"]
        key = str(tick["instrument_id"])
        identities[key] = {
            "expiry": str(tick["expiry"]),
            "option_type": str(tick["option_type"]).upper(),
            "strike": str(tick["strike_price"]),
            "contract_multiplier_krw": int(tick["contract_multiplier"]),
        }
    if expiries != ["20261109", "20261112"] or len(identities) != 4:
        raise AssertionError("S7_SYNTHETIC_IDENTITY_COVERAGE_INVALID")
    if any(v["contract_multiplier_krw"] != 250000 for v in identities.values()):
        raise AssertionError("S7_STANDARD_KOSPI200_MULTIPLIER_INVALID")

    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
    output_data.write_bytes(payload)
    dataset_sha = digest(payload)

    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "dataset_path": "data/derived_scenario/q25_s08_s7_fee_authority/20261103.jsonl",
        "output_path": "data/derived_scenario/q25_s08_s7_fee_authority/20261103.jsonl",
        "dataset_sha256": dataset_sha,
        "output_sha256": dataset_sha,
        "output_bytes": len(payload),
        "rows": len(rows),
        "validation_identity_owner": "Q25_S7_SYNTHETIC_OPTION_MASTER",
        "validation_identity_owner_status": "CONFIRMED_VALIDATION_ONLY",
        "validation_identity_registry": "manifest-bound synthetic option master; four exact expiry/type/strike identities; no Standard instrument_id assignment",
        "scenario_expiry_authority": {
            "status": "CONFIRMED_VALIDATION_ONLY",
            "authoritative_within_scenario": True,
            "authority_source": "STRATEGY7_WEEKLY_SYNTHETIC_CALENDAR_V2",
            "timezone": "Asia/Seoul",
            "group_expiry_by_id": {
                "S7_MON_20261109": "20261109",
                "S7_THU_20261112": "20261112"
            },
            "calendar_rule": "Explicit scenario schedule is the sole date authority for this validation dataset; no KRX/KIS holiday calendar or production expiry claim.",
            "production_exchange_expiry_authoritative": False
        },
        "synthetic_contracts": identities,
        "fee_model": MODEL,
        "production_runtime_eligible": False,
        "runtime_eligible": False,
    })
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (TARGET / "manifest.json").write_bytes(manifest_bytes)
    manifest_sha = digest(manifest_bytes)

    profile = json.loads(PROFILE_SOURCE.read_text(encoding="utf-8"))
    profile.update({
        "dataset_manifest": "data/derived_scenario/q25_s08_s7_fee_authority/manifest.json",
        "dataset_path": "data/derived_scenario/q25_s08_s7_fee_authority/20261103.jsonl",
        "dataset_sha256": dataset_sha,
        "manifest_sha256": manifest_sha,
        "validation_identity_owner": "Q25_S7_SYNTHETIC_OPTION_MASTER",
        "validation_identity_owner_status": "CONFIRMED_VALIDATION_ONLY",
        "scenario_expiry_authority": manifest["scenario_expiry_authority"],
        "fee_model": MODEL,
        "fees": {
            **MODEL,
            "source_status": "CONFIGURED_VALIDATION_ONLY_REFERENCE_MODEL",
            "included_in_premium_cap": False,
            "included_in_net_pnl": True,
            "treatment": "Charge every filled BUY and SELL execution separately; deduct all fees from account and expiry-group realized PnL. Premium risk cap remains gross premium; entry fee reserve is separately audited.",
        },
        "max_loss_basis": "premium_paid_only_for_long_option_risk_gate; all entry and exit fees are separately accounted in net PnL",
    })
    PROFILE_TARGET.parent.mkdir(parents=True, exist_ok=True)
    profile_bytes = (json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    PROFILE_TARGET.write_bytes(profile_bytes)

    print(json.dumps({
        "dataset_path": str(output_data.relative_to(ROOT)).replace("\\", "/"),
        "rows": len(rows),
        "dataset_sha256": dataset_sha,
        "manifest_sha256": manifest_sha,
        "profile_path": str(PROFILE_TARGET.relative_to(ROOT)).replace("\\", "/"),
        "profile_sha256": digest(profile_bytes),
        "expiries": expiries,
        "groups": groups,
        "synthetic_contracts": identities,
        "validation_identity_owner_status": manifest["validation_identity_owner_status"],
        "scenario_expiry_authority": manifest["scenario_expiry_authority"],
        "fee_model": MODEL,
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
