from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from environments.high_speed.validation_only_option_risk_budget import (
    SyntheticLongOptionLeg,
    evaluate_validation_budget,
    load_validation_profile,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly/20261103.jsonl"
MANIFEST = ROOT / "data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly/manifest.json"
OPERATIONAL_RISK = ROOT / "config/risk/option-hedge-risk.v1.json"
PROFILE = ROOT / "config/validation_only/q25_s05_1_s7_v2/risk_profile.json"
PROFILE_SHA = PROFILE.with_suffix(PROFILE.suffix + ".sha256")
REPORT = ROOT / "reports/synth/Q25_A5_S05_1_S7_VALIDATION_RISK_BASIS_20261107.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for path in (DATASET, MANIFEST, OPERATIONAL_RISK):
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    operational = json.loads(OPERATIONAL_RISK.read_text(encoding="utf-8"))
    dataset_hash = sha256(DATASET)
    manifest_hash = sha256(MANIFEST)
    if manifest.get("dataset_sha256") != dataset_hash:
        raise SystemExit("BLOCKED_DATASET_HASH_MISMATCH")
    if manifest.get("validation_only") is not True or manifest.get("runtime_eligible") is not False:
        raise SystemExit("BLOCKED_DATASET_NOT_VALIDATION_ONLY")
    if manifest.get("contract_identity_authority") != "SYNTHETIC_ONLY":
        raise SystemExit("BLOCKED_SYNTHETIC_AUTHORITY_MISMATCH")
    if manifest.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED":
        raise SystemExit("BLOCKED_EXPECTED_IDENTITY_BOUNDARY_CHANGED")
    if manifest.get("expiry_is_authoritative") is not False:
        raise SystemExit("BLOCKED_EXPIRY_AUTHORITY_CHANGED")
    if operational.get("activation_mode") != "DISABLED_UNTIL_RUNTIME_INTEGRATION":
        raise SystemExit("BLOCKED_OPERATIONAL_RISK_CONFIG_STATE_CHANGED")
    operational_track7 = operational.get("strategies", {}).get("track7_weekly_insurance", {})
    if int(operational_track7.get("max_gross_premium_outlay_krw", -1)) != 250000:
        raise SystemExit("BLOCKED_OPERATIONAL_REFERENCE_CHANGED")

    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != int(manifest.get("rows", -1)):
        raise SystemExit("BLOCKED_DATASET_ROW_COUNT_MISMATCH")
    if any(row.get("synthetic") is not True or row.get("provenance") != "DERIVED_SCENARIO" for row in rows):
        raise SystemExit("BLOCKED_NON_SYNTHETIC_ROW")

    maxima: dict[tuple[str, str], dict] = {}
    rows_by_group: dict[str, int] = defaultdict(int)
    for row in rows:
        metadata = row["scenario_metadata"]
        tick = row["tick"]
        if metadata.get("validation_only") is not True or metadata.get("runtime_eligible") is not False:
            raise SystemExit("BLOCKED_ROW_VALIDATION_BOUNDARY_MISMATCH")
        if metadata.get("contract_identity_authority") != "SYNTHETIC_ONLY":
            raise SystemExit("BLOCKED_ROW_IDENTITY_AUTHORITY_MISMATCH")
        group_id = str(metadata["group_id"])
        leg_id = str(metadata["leg_id"]).lower()
        if leg_id not in {"call", "put"}:
            raise SystemExit("BLOCKED_UNEXPECTED_LEG")
        if Decimal(str(tick["ask_price"])) <= 0 or Decimal(str(tick["contract_multiplier"])) <= 0:
            raise SystemExit("BLOCKED_INVALID_PREMIUM_INPUT")
        rows_by_group[group_id] += 1
        key = (group_id, leg_id)
        premium = Decimal(str(tick["ask_price"])) * Decimal(str(tick["contract_multiplier"]))
        if key not in maxima or premium > maxima[key]["premium"]:
            maxima[key] = {
                "ask_price": Decimal(str(tick["ask_price"])),
                "contract_multiplier": Decimal(str(tick["contract_multiplier"])),
                "premium": premium,
                "timestamp": tick["timestamp"],
                "instrument_id": tick.get("instrument_id"),
            }

    expected_groups = set(manifest.get("groups", []))
    if set(rows_by_group) != expected_groups or len(expected_groups) != 2:
        raise SystemExit("BLOCKED_GROUP_SET_MISMATCH")
    expected_legs = {(group, leg) for group in expected_groups for leg in ("call", "put")}
    if set(maxima) != expected_legs:
        raise SystemExit("BLOCKED_GROUP_LEG_COVERAGE_MISMATCH")

    group_exposure = {
        group: int(sum(maxima[(group, leg)]["premium"] for leg in ("call", "put")))
        for group in sorted(expected_groups)
    }
    concurrent_exposure = sum(group_exposure.values())
    # Reuse the existing Q25 synthetic budget convention: 25% headroom,
    # rounded upward to the next KRW 100,000. This is a test budget only.
    validation_cap = int(
        (Decimal(concurrent_exposure) * Decimal("1.25") / Decimal("100000"))
        .to_integral_value(rounding=ROUND_CEILING)
        * Decimal("100000")
    )
    max_group = max(group_exposure.values())
    operational_reference = int(operational_track7["max_gross_premium_outlay_krw"])

    profile = {
        "schema_version": "q25-validation-only-risk-profile-v1",
        "strategy_id": "track7_volatility_skew_weekly_insurance",
        "scenario_id": manifest["scenario_id"],
        "currency": "KRW",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "risk_checks_enabled": True,
        "enforcement_mode": "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT",
        "operational_config_path": "config/risk/option-hedge-risk.v1.json",
        "operational_config_activation_mode": operational["activation_mode"],
        "operational_config_mutated": False,
        "dataset_path": str(DATASET.relative_to(ROOT)).replace("\\", "/"),
        "dataset_manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": dataset_hash,
        "manifest_sha256": manifest_hash,
        "contract_identity_authority": "SYNTHETIC_ONLY",
        "identity_source_status": manifest["identity_source_status"],
        "expiry_is_authoritative": False,
        "max_concurrent_groups": 2,
        "group_ids": sorted(expected_groups),
        "group_gross_premium_krw": group_exposure,
        "max_group_gross_premium_krw": max_group,
        "max_concurrent_gross_premium_krw": concurrent_exposure,
        "max_gross_premium_outlay_krw": validation_cap,
        "max_loss_krw": validation_cap,
        "max_loss_basis": "premium_paid_only_before_fees; fees are excluded and must be separately modeled",
        "budget_derivation": {
            "method": "ceil(max_concurrent_synthetic_premium * 1.25 / 100000) * 100000",
            "headroom_ratio": "1.25",
            "rounding_unit_krw": 100000,
            "source": "existing Q25 synthetic dataset generator convention; not an operational risk approval",
        },
        "operational_reference_limit_krw": operational_reference,
        "operational_reference_status": operational["activation_mode"],
        "fees": {
            "included_in_premium_cap": False,
            "source_status": "NOT_PRESENT_IN_S7_V2_DATASET",
            "treatment": "separate fee accounting required; do not claim fee-inclusive max loss",
        },
        "audit_fields_required": [
            "computed_gross_premium_krw",
            "computed_max_loss_krw",
            "computed_concurrent_exposure_krw",
            "operational_reference_overage_krw",
            "validation_budget_overage_krw",
            "run_id",
            "scenario_id",
            "manifest_sha256",
            "dataset_sha256",
        ],
    }
    profile["profiles"] = {"track7_weekly_insurance": {
        "max_concurrent_groups": profile["max_concurrent_groups"],
        "max_gross_premium_outlay_krw": profile["max_gross_premium_outlay_krw"],
        "max_loss_krw": profile["max_loss_krw"],
        "operational_reference_limit_krw": profile["operational_reference_limit_krw"],
        "budget_basis": "sum of both BUY legs across two independent expiry groups; premium-only before fees",
    }}
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    profile_hash = sha256(PROFILE)
    PROFILE_SHA.write_text(f"{profile_hash}  {PROFILE.name}\n", encoding="ascii")

    loaded = load_validation_profile(PROFILE, "track7_weekly_insurance")
    risk_legs = [
        SyntheticLongOptionLeg(
            leg_id=f"{group}:{leg}",
            side="BUY",
            quantity=1,
            ask_price=maxima[(group, leg)]["ask_price"],
            contract_multiplier=maxima[(group, leg)]["contract_multiplier"],
        )
        for group in sorted(expected_groups)
        for leg in ("call", "put")
    ]
    risk_result = evaluate_validation_budget(risk_legs, loaded)
    if risk_result.computed_gross_premium_krw != concurrent_exposure:
        raise SystemExit("BLOCKED_RISK_CALCULATION_MISMATCH")
    if risk_result.validation_budget_overage_krw != 0:
        raise SystemExit("BLOCKED_VALIDATION_BUDGET_EXCEEDED")
    if risk_result.verdict != "VALIDATION_ONLY_ALLOW":
        raise SystemExit("BLOCKED_VALIDATION_RISK_VERDICT")

    report = {
        "report_id": "Q25_A5_S05_1_S7_VALIDATION_RISK_BASIS_20261107",
        "verdict": "PSB_UNVERIFIED",
        "scope": "S05-1 validation-only synthetic risk-input and budget basis; no Runtime enablement",
        "dataset_path": str(DATASET.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": dataset_hash,
        "manifest_path": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": manifest_hash,
        "profile_path": str(PROFILE.relative_to(ROOT)).replace("\\", "/"),
        "profile_sha256": profile_hash,
        "profile_sha256_sidecar": str(PROFILE_SHA.relative_to(ROOT)).replace("\\", "/"),
        "row_count": len(rows),
        "rows_by_group": dict(sorted(rows_by_group.items())),
        "group_gross_premium_krw": group_exposure,
        "max_group_gross_premium_krw": max_group,
        "max_concurrent_gross_premium_krw": concurrent_exposure,
        "validation_budget_cap_krw": validation_cap,
        "budget_derivation": profile["budget_derivation"],
        "risk_calculation": {
            "verdict": risk_result.verdict,
            "computed_gross_premium_krw": risk_result.computed_gross_premium_krw,
            "computed_max_loss_krw": risk_result.computed_max_loss_krw,
            "computed_concurrent_exposure_krw": risk_result.computed_concurrent_exposure_krw,
            "validation_budget_overage_krw": risk_result.validation_budget_overage_krw,
            "reference_baseline_overage_krw": risk_result.operational_reference_overage_krw,
        },
        "operational_reference": {
            "gross_premium_reference_krw": operational_reference,
            "activation_mode": operational["activation_mode"],
            "active_enforcement": False,
            "config_mutated": False,
        },
        "fees": profile["fees"],
        "authority_boundary": {
            "validation_only": True,
            "runtime_eligible": False,
            "production_runtime_eligible": False,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "identity_source_status": manifest["identity_source_status"],
            "expiry_is_authoritative": False,
            "allow_kis_api": False,
            "allow_live_orders": False,
            "allow_real_account": False,
        },
        "remaining_blockers": [
            "Synthetic contract identity owner remains unresolved; expiry and multiplier are non-authoritative.",
            "Fee schedule is absent; the premium-only maximum-loss basis is not fee-inclusive.",
            "This profile is not wired to the Strategy 7 Runtime readiness/risk gate; runtime_config_verified and risk_limits_available remain fail-closed.",
            "The 3,300,000 KRW cap is a scenario-derived validation budget, not a user-approved or operational trading limit.",
        ],
        "changes": {
            "created": [
                str(PROFILE.relative_to(ROOT)).replace("\\", "/"),
                str(PROFILE_SHA.relative_to(ROOT)).replace("\\", "/"),
                str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
                str(REPORT.relative_to(ROOT)).replace("\\", "/"),
            ],
            "existing_dataset_or_manifest_modified": False,
            "operational_risk_config_modified": False,
            "strategy_runtime_flags_enabled": False,
            "kis_or_live_api_called": False,
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()