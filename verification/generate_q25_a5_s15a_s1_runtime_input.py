from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/derived_scenario/q25_a5_s15a_s1_runtime_input"
CONFIG_DIR = ROOT / "config/validation_only/q25_a5_s15a_s1_runtime_input"
KST = timezone(timedelta(hours=9))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_events() -> list[dict]:
    events: list[dict] = []
    paths = (
        ("S1_S15A_U28_UP", "2026-11-02", (100.0, 102.5, 105.0, 107.5), "UP"),
        ("S1_S15A_U28_DOWN", "2026-11-03", (100.0, 97.5, 95.0, 92.5), "DOWN"),
    )
    for scenario_id, day, prices, direction in paths:
        for index, price in enumerate(prices):
            observed = datetime.fromisoformat(f"{day}T09:00:00").replace(tzinfo=KST) + timedelta(minutes=index)
            if index == 0:
                expected = None
            else:
                expected = {
                    "side": "SELL",
                    "option_type": "PUT" if direction == "UP" else "CALL",
                    "strike": round((prices[index - 1] - 7.5) if direction == "UP" else (prices[index - 1] + 7.5), 1),
                }
            events.append({
                "schema": "q25-s1-validation-input-event-v1",
                "provenance": "DERIVED_SCENARIO",
                "synthetic": True,
                "validation_only": True,
                "runtime_eligible": False,
                "production_runtime_eligible": False,
                "scenario_id": scenario_id,
                "event_index": index,
                "timestamp": observed.isoformat(),
                "underlying_price": price,
                "reference_point_test_input": 100.0,
                "reference_point_basis": "SCENARIO_INITIAL_REFERENCE_ONLY_NOT_U23_POLICY",
                "days_to_expiry_test_value": 10.0,
                "dte_basis": "SCENARIO_GATE_VALUE_ONLY_NOT_U22_CALENDAR_SEMANTICS",
                "open_short_quantity": 0,
                "pending_short_quantity": 0,
                "expected_signal": expected,
                "execution_enabled": False,
                "contract_identity": None,
                "expiry_yyyymmdd": None,
                "contract_multiplier": None,
                "quote": None,
            })
    return events


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    events = build_events()
    raw = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in events).encode("utf-8")
    dataset_path = DATA_DIR / "events.jsonl"
    dataset_path.write_bytes(raw)
    profile = {
        "schema": "q25-s1-validation-signal-risk-profile-v1",
        "profile_id": "Q25_A5_S15A_S1_SIGNAL_ONLY",
        "validation_only": True,
        "signal_generation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "execution_enabled": False,
        "operational_config_mutated": False,
        "contract_identity_authority": "NONE",
        "expiry_is_authoritative": False,
        "limits": {
            "max_open_short_contracts": 10,
            "max_pending_short_contracts": 10,
            "quantity_per_crossing": 1,
            "dte_gate_test_value": 10.0,
        },
        "notes": [
            "Signal-generation test profile only; not an account risk approval.",
            "DTE value and initial reference are explicit scenario inputs, not U22/U23 policy decisions.",
            "No option contract identity, expiry, multiplier, quote, order, or fill is supplied.",
        ],
        "dataset_sha256": digest(raw),
    }
    profile_raw = (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode("utf-8")
    profile_path = CONFIG_DIR / "risk_profile.json"
    profile_path.write_text(profile_raw.decode("utf-8"), encoding="utf-8", newline="\n")
    manifest = {
        "schema": "q25-s1-validation-input-manifest-v1",
        "dataset_id": "Q25_A5_S15A_S1_SIGNAL_INPUT_20261107",
        "strategy_id": "TRACK1_TAIL_DEFENSE",
        "rules_version": "q25-a5-s15a-s1-signal-input-v1",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "signal_generation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "execution_enabled": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "contract_identity_authority": "NONE",
        "expiry_is_authoritative": False,
        "dataset_path": str(dataset_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": digest(raw),
        "event_count": len(events),
        "scenario_ids": ["S1_S15A_U28_UP", "S1_S15A_U28_DOWN"],
        "risk_profile_path": str(profile_path.relative_to(ROOT)).replace("\\", "/"),
        "risk_profile_sha256": digest(profile_raw),
        "notes": [
            "This dataset is for natural StrategyHub signal generation only.",
            "Reference point and DTE are scenario inputs, not monthly-reference or expiry policy.",
            "No contract identity, exact expiry, multiplier, option quote, order, or fill is provided.",
        ],
    }
    manifest_path = CONFIG_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    manifest_sha = digest(manifest_path.read_bytes())
    print(json.dumps({
        "dataset_path": manifest["dataset_path"],
        "dataset_sha256": manifest["dataset_sha256"],
        "risk_profile_path": manifest["risk_profile_path"],
        "risk_profile_sha256": manifest["risk_profile_sha256"],
        "manifest_path": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": manifest_sha,
        "event_count": len(events),
    }, indent=2))


if __name__ == "__main__":
    main()
