from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = ROOT / "data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly/20261103.jsonl"
MANIFEST = DATASET.with_name("manifest.json")
PROFILE = ROOT / "config/validation_only/q25_s05_1_s7_v2/risk_profile.json"
REPORT = ROOT / "reports/synth/Q25_A5_S05_2_S7_SYNTHETIC_IDENTITY_BOUNDARY_20261107.json"
EXPECTED_GROUPS = {
    "S7_MON_20261109": {"expiry": "20261109", "series": "MONDAY_WEEKLY", "entry_date": "2026-11-02"},
    "S7_THU_20261112": {"expiry": "20261112", "series": "THURSDAY_WEEKLY", "entry_date": "2026-11-05"},
}
ID_PATTERN = re.compile(r"^SYNTHETIC_CONTRACT:strategy7_weekly:(\d{8}):(CALL|PUT):(\d+(?:\.\d+)?)$")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(f"BLOCKED_{code}")


def main() -> None:
    for path in (DATASET, MANIFEST, PROFILE):
        require(path.is_file(), f"MISSING_{path.name.upper()}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    require(manifest.get("dataset_sha256") == sha(DATASET), "DATASET_HASH_MISMATCH")
    require(profile.get("dataset_sha256") == sha(DATASET), "PROFILE_DATASET_HASH_MISMATCH")
    require(profile.get("manifest_sha256") == sha(MANIFEST), "PROFILE_MANIFEST_HASH_MISMATCH")
    require(manifest.get("identity_source_status") == "BLOCKED_IDENTITY_OWNER_UNRESOLVED", "IDENTITY_BLOCKER_WAS_CHANGED")
    require(manifest.get("contract_identity_authority") == "SYNTHETIC_ONLY", "MANIFEST_AUTHORITY_CHANGED")
    require(manifest.get("expiry_is_authoritative") is False, "MANIFEST_EXPIRY_AUTHORITY_CHANGED")
    require(profile.get("runtime_eligible") is False and profile.get("production_runtime_eligible") is False, "PROFILE_RUNTIME_GATE_CHANGED")
    require(profile.get("allow_kis_api") is False and profile.get("allow_live_orders") is False and profile.get("allow_real_account") is False, "PROFILE_SAFETY_FLAGS_CHANGED")

    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(rows) == 216 == manifest.get("rows"), "ROW_COUNT_MISMATCH")
    ids: dict[str, tuple] = {}
    group_rows = Counter()
    group_legs: dict[str, set[str]] = defaultdict(set)
    identity_counts = Counter()
    multiplier_by_identity = defaultdict(set)
    group_metadata = {}
    timestamp_leg_coverage = defaultdict(set)

    for row in rows:
        tick = row["tick"]
        meta = row["scenario_metadata"]
        require(row.get("synthetic") is True and row.get("provenance") == "DERIVED_SCENARIO", "ROW_NOT_SYNTHETIC")
        require(meta.get("validation_only") is True and meta.get("runtime_eligible") is False, "ROW_RUNTIME_BOUNDARY_CHANGED")
        require(meta.get("contract_identity_authority") == "SYNTHETIC_ONLY", "ROW_AUTHORITY_CHANGED")
        require(meta.get("expiry_is_authoritative") is False, "ROW_EXPIRY_AUTHORITY_CHANGED")
        require(tick.get("instrument_identity_status") == "BLOCKED_IDENTITY_OWNER_UNRESOLVED", "ROW_IDENTITY_STATUS_CHANGED")
        group = meta.get("group_id")
        leg = str(meta.get("leg_id", "")).upper()
        require(group in EXPECTED_GROUPS, "UNKNOWN_GROUP")
        require(leg in {"CALL", "PUT"}, "UNKNOWN_LEG")
        expected = EXPECTED_GROUPS[group]
        require(tick.get("expiry") == expected["expiry"], "GROUP_EXPIRY_MISMATCH")
        require(meta.get("product_series") == expected["series"], "GROUP_SERIES_MISMATCH")
        require(meta.get("group_entry_date") == expected["entry_date"], "GROUP_ENTRY_DATE_MISMATCH")
        require(tick.get("option_type") == leg, "OPTION_TYPE_MISMATCH")
        require(tick.get("contract_multiplier") == 250000.0, "SYNTHETIC_MULTIPLIER_MISMATCH")
        require(tick.get("contract_class") == "weekly", "CONTRACT_CLASS_MISMATCH")

        instrument_id = tick.get("instrument_id")
        symbol = tick.get("symbol")
        synthetic_id = tick.get("synthetic_contract_id")
        source_code = tick.get("source_instrument_code")
        require(isinstance(instrument_id, str) and instrument_id, "INSTRUMENT_ID_MISSING")
        require(instrument_id == symbol == synthetic_id == source_code, "SYNTHETIC_ID_FIELDS_DIVERGE")
        match = ID_PATTERN.fullmatch(instrument_id)
        require(match is not None, "SYNTHETIC_ID_FORMAT_INVALID")
        id_expiry, id_leg, id_strike = match.groups()
        require(id_expiry == expected["expiry"] and id_leg == leg, "SYNTHETIC_ID_COMPONENT_MISMATCH")
        require(float(id_strike) == float(tick.get("strike_price", 0)), "SYNTHETIC_ID_STRIKE_MISMATCH")
        identity_tuple = (group, id_expiry, leg, id_strike, tick["contract_multiplier"])
        if instrument_id in ids:
            require(ids[instrument_id] == identity_tuple, "SYNTHETIC_ID_COLLISION")
        ids[instrument_id] = identity_tuple
        identity_counts[instrument_id] += 1
        multiplier_by_identity[instrument_id].add(tick["contract_multiplier"])
        group_rows[group] += 1
        group_legs[group].add(leg)
        group_metadata[group] = {"expiry": expected["expiry"], "product_series": expected["series"], "entry_date": expected["entry_date"]}
        timestamp_leg_coverage[(group, tick["timestamp"])].add(leg)

    require(set(group_rows) == set(EXPECTED_GROUPS), "GROUP_SET_MISMATCH")
    require(all(group_rows[group] == 108 and group_legs[group] == {"CALL", "PUT"} for group in EXPECTED_GROUPS), "GROUP_LEG_COVERAGE_MISMATCH")
    require(len(ids) == 4 and all(count == 54 for count in identity_counts.values()), "IDENTITY_CARDINALITY_MISMATCH")
    require(all(values == {250000.0} for values in multiplier_by_identity.values()), "MULTIPLIER_NOT_STABLE")
    require(len(timestamp_leg_coverage) == 108 and all(legs == {"CALL", "PUT"} for legs in timestamp_leg_coverage.values()), "TIMESTAMP_PAIR_COVERAGE_MISMATCH")

    # This proves only deterministic, scenario-local synthetic labels. It deliberately
    # does not resolve scenario_contract_key -> KIS shrn_iscd -> authoritative registry.
    report = {
        "report_id": "Q25_A5_S05_2_S7_SYNTHETIC_IDENTITY_BOUNDARY_20261107",
        "verdict": "PSB_UNVERIFIED",
        "scope": "S7 synthetic identity consistency and authority-boundary audit only",
        "dataset_sha256": sha(DATASET),
        "manifest_sha256": sha(MANIFEST),
        "profile_sha256": sha(PROFILE),
        "rows": len(rows),
        "groups": {group: {"rows": group_rows[group], **group_metadata[group], "legs": sorted(group_legs[group])} for group in sorted(group_rows)},
        "synthetic_identity_count": len(ids),
        "observations_per_identity": sorted(identity_counts.values()),
        "synthetic_identity_components": ["scenario-local prefix", "synthetic expiry", "CALL/PUT", "strike"],
        "multiplier_per_identity": 250000,
        "internal_consistency": "PASS",
        "authoritative_identity": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "scenario_contract_key_mapping": "NOT_CREATED: no authoritative shrn_iscd registry mapping for the 20261109/20261112 scenario contracts",
        "expiry_authority": "SYNTHETIC_ONLY_NON_AUTHORITATIVE",
        "production_runtime_eligible": False,
        "kis_api_called": False,
        "live_order_or_real_account_used": False,
        "blockers": [
            "Synthetic IDs are generated labels, not externally owned Standard instrument_id values.",
            "The local KIS master/expiry evidence is historical and does not establish authoritative November 9/12 mappings for these scenario strikes.",
            "KIS shrn_iscd and stnd_iscd cannot be promoted to Standard instrument_id under the identity owner matrix.",
            "The V2 scenario multiplier is synthetic and not an authoritative contract-master multiplier for these expiry groups.",
            "Expiry values are scenario metadata, not authoritative exchange/KIS expiry records.",
        ],
        "changes": {
            "dataset_or_manifest_modified": False,
            "identity_owner_matrix_modified": False,
            "authoritative_mapping_created": False,
            "runtime_gate_enabled": False,
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()