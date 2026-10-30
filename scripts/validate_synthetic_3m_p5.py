from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from contracts.trading_date import parse_trading_date


GENERATOR_VERSION = "p5-deterministic-synthetic-3m-v1"
PROVENANCE = "DERIVED_SCENARIO"
IDENTITY_STATUS = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset(root: Path, dataset: Path) -> dict:
    manifest_path = dataset / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:MANIFEST_REQUIRED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "synthetic": True,
        "provenance": PROVENANCE,
        "generator_version": GENERATOR_VERSION,
        "identity_source_status": IDENTITY_STATUS,
        "production_runtime_eligible": False,
        "validation_only": True,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:MANIFEST_FIELD:{key}")
    if not isinstance(manifest.get("seed"), int) or not manifest.get("scenario_id") or not manifest.get("run_id"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:SEED_SCENARIO_RUN_REQUIRED")
    if manifest.get("date_end_exclusive") <= manifest.get("date_start"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:DATE_WINDOW_INVALID")
    identity_policy = manifest.get("identity_policy", {})
    if (identity_policy.get("mode") != "SYNTHETIC_ONLY"
            or identity_policy.get("production_standard_instrument_id_assigned") is not False
            or identity_policy.get("runtime_use") != "PROHIBITED"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:IDENTITY_POLICY_UNSAFE")
    expiry_policy = manifest.get("expiry_policy", {})
    rule_sources = expiry_policy.get("rule_source_urls", [])
    if (expiry_policy.get("mode") != "SYNTHETIC_CALENDAR_DERIVED"
            or expiry_policy.get("policy_version") != "synthetic-expiry-krx-calendar-v1"
            or expiry_policy.get("calendar_source_role") != "SCENARIO_ONLY_NOT_RUNTIME_AUTHORITY"
            or not rule_sources
            or any(not str(url).startswith("https://") or "krx.co.kr/" not in str(url) for url in rule_sources)):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:EXPIRY_POLICY_UNSAFE")

    master_path = root / Path(manifest["option_master_path"])
    underlying_path = root / Path(manifest["underlying_spot_source_path"])
    if not master_path.is_file() or sha256_file(master_path) != manifest.get("option_master_source_sha256"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:OPTION_MASTER_HASH_MISMATCH")
    if not underlying_path.is_file() or sha256_file(underlying_path) != manifest.get("underlying_source_sha256"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:UNDERLYING_HASH_MISMATCH")
    holiday_dates = set()
    recorded_calendar_hashes = {}
    for source in manifest.get("calendar_sources", []):
        path = root / Path(source["path"])
        if not path.is_file() or sha256_file(path) != source.get("sha256"):
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:CALENDAR_HASH_MISMATCH:{source.get('path')}")
        recorded_calendar_hashes[source["path"]] = source["sha256"]
        calendar_payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if calendar_payload.get("source") != "KRX":
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:CALENDAR_SOURCE_INVALID:{source.get('path')}")
        holiday_dates.update(parse_trading_date(value) for value in calendar_payload.get("holidays", []))
    if expiry_policy.get("calendar_sha256") != recorded_calendar_hashes:
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:EXPIRY_POLICY_CALENDAR_HASH_MAP_MISMATCH")
    if (expiry_policy.get("source_master_sha256") != manifest.get("option_master_sha256")
            or manifest.get("option_master_source_sha256") != manifest.get("option_master_sha256")):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:EXPIRY_POLICY_MASTER_HASH_MISMATCH")

    trading_dates = set()
    for day in manifest.get("days", []):
        day_value = parse_trading_date(day["date"])
        if day_value.weekday() >= 5 or day_value in holiday_dates:
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:DATA_ON_HOLIDAY:{day['date']}")
        trading_dates.add(day_value)
    if len(trading_dates) != manifest.get("trading_days"):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:TRADING_DAY_COUNT_MISMATCH")

    files = manifest.get("output_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:OUTPUT_FILE_LIST_REQUIRED")
    file_by_name = {item.get("path"): item for item in files}
    if len(file_by_name) != len(files):
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:DUPLICATE_OUTPUT_FILE")
    row_total = 0
    previous_timestamp = None
    seen_event_ids = set()
    for item in files:
        path = dataset / str(item.get("path", ""))
        if not path.is_file():
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:OUTPUT_FILE_MISSING:{path.name}")
        if path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get("sha256"):
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:OUTPUT_FILE_HASH_MISMATCH:{path.name}")
        if path.name == "manifest.json":
            continue
        if path.name == "control_tower_replay.jsonl":
            continue
        rows = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                for key, expected in {
                    "synthetic": True,
                    "provenance": PROVENANCE,
                    "generator_version": GENERATOR_VERSION,
                    "seed": manifest["seed"],
                    "scenario_id": manifest["scenario_id"],
                    "run_id": manifest["run_id"],
                    "identity_status": IDENTITY_STATUS,
                    "dataset": manifest["dataset"],
                }.items():
                    if record.get(key) != expected:
                        raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:ROW_FIELD:{path.name}:{line_number}:{key}")
                if "instrument_id" in record.get("tick", {}):
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:PRODUCTION_ID_ALIAS_FORBIDDEN:{path.name}:{line_number}")
                tick = record.get("tick", {})
                if not tick.get("source_instrument_code") or tick.get("instrument_identity_status") != IDENTITY_STATUS:
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:SOURCE_IDENTITY_REQUIRED:{path.name}:{line_number}")
                synthetic_contract_id = tick.get("synthetic_contract_id")
                if not isinstance(synthetic_contract_id, str) or not synthetic_contract_id.startswith("SYNTHETIC_CONTRACT:"):
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:SYNTHETIC_CONTRACT_ID_REQUIRED:{path.name}:{line_number}")
                expiry_date = parse_trading_date(str(tick.get("expiry", "")))
                if expiry_date.weekday() >= 5 or expiry_date in holiday_dates:
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:EXPIRY_ON_HOLIDAY:{path.name}:{line_number}")
                if expiry_date not in trading_dates and not (manifest.get("date_start") <= expiry_date.isoformat() < manifest.get("date_end_exclusive")):
                    # Expiry may be outside the generated trading-day rows, but must be within covered calendar years.
                    calendar_years = {int(json.loads((root / Path(source["path"])).read_text(encoding="utf-8-sig"))["year"]) for source in manifest.get("calendar_sources", [])}
                    if expiry_date.year not in calendar_years:
                        raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:EXPIRY_OUTSIDE_CALENDAR_COVERAGE:{expiry_date.isoformat()}")
                event_id = record.get("event_id")
                if not isinstance(event_id, str) or len(event_id) != 64 or event_id in seen_event_ids:
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:EVENT_ID_INVALID_OR_DUPLICATE:{path.name}:{line_number}")
                seen_event_ids.add(event_id)
                timestamp = datetime.fromisoformat(str(tick.get("timestamp", "")))
                if previous_timestamp is not None and timestamp < previous_timestamp:
                    raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:TIMESTAMP_ORDER:{path.name}:{line_number}")
                previous_timestamp = timestamp
                rows += 1
        if rows != item.get("rows"):
            raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:ROW_COUNT:{path.name}:{rows}:{item.get('rows')}")
        row_total += rows

    replay = dataset / "control_tower_replay.jsonl"
    replay_entry = file_by_name.get(replay.name)
    if replay_entry is None or replay_entry.get("rows") != row_total:
        raise RuntimeError("BLOCKED_DATASET_VALIDATION:REPLAY_REFERENCE_INVALID")
    if row_total != manifest.get("event_rows") or row_total != manifest.get("events"):
        raise RuntimeError(f"BLOCKED_DATASET_VALIDATION:TOTAL_ROW_COUNT:{row_total}")
    return {
        "status": "PASS_WITH_LIMITATION",
        "dataset": manifest["dataset"],
        "event_rows": row_total,
        "output_files_checked": len(files),
        "identity_source_status": IDENTITY_STATUS,
        "production_runtime_eligible": False,
        "limitation": "Scenario data only; unresolved production identity blocks runtime/order/position use.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate P5 synthetic dataset integrity and provenance")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = root / dataset
    print(json.dumps(validate_dataset(root, dataset), ensure_ascii=False))


if __name__ == "__main__":
    main()
