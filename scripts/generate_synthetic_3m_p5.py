from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.generate_authoritative_option_synthetic_3m import generate as generate_legacy
from scripts.generate_authoritative_option_synthetic_3m import add_calendar_months, load_calendar, latest_master_snapshot, parse_master
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


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_synthetic_expiry_inputs(root: Path) -> dict:
    """Resolve expiry only for DERIVED_SCENARIO using the versioned holiday calendar.

    These computed dates are synthetic scenario policy outputs, never KIS/production
    authoritative contract metadata. Missing calendar coverage or unparseable source
    series blocks generation.
    """
    master_path, snapshot_day = latest_master_snapshot(root)
    horizon_end_exclusive = add_calendar_months(snapshot_day, 3)
    calendar_years = set(range(snapshot_day.year, horizon_end_exclusive.year + 2))
    calendar = load_calendar(root, calendar_years)
    identities, master_sha, selected_product, monthly_expiries, weekly_expiries = parse_master(root, calendar, master_path)
    if not identities or not monthly_expiries:
        raise RuntimeError("BLOCKED_SYNTHETIC_EXPIRY_POLICY_NO_CONTRACTS")
    computed = [parse_trading_date(value) for value in monthly_expiries.values()]
    computed.extend(parse_trading_date(value) for value in weekly_expiries.values())
    for expiry in computed:
        if not calendar.is_trading_day(expiry):
            raise RuntimeError(f"BLOCKED_SYNTHETIC_EXPIRY_NOT_TRADING_DAY:{expiry.isoformat()}")
    return {
        "master_path": str(master_path.relative_to(root)).replace("\\\\", "/"),
        "master_sha256": master_sha,
        "snapshot_date": snapshot_day.isoformat(),
        "calendar_years": sorted(calendar_years),
        "calendar_paths": [f"data/calendar/krx/{year}.json" for year in sorted(calendar_years)],
        "calendar_sha256": {
            f"data/calendar/krx/{year}.json": sha256_file(root / "data" / "calendar" / "krx" / f"{year}.json")
            for year in sorted(calendar_years)
        },
        "monthly_expiry_count": len(monthly_expiries),
        "weekly_series_expiry_count": len(weekly_expiries),
        "contract_identity_count": len(identities),
        "selected_source_product_family": selected_product,
        "policy_version": "synthetic-expiry-krx-calendar-v1",
    }


def decorate_dataset(root: Path, stage: Path, target_name: str, pattern: str, seed: int, expiry_inputs: dict) -> dict:
    manifest_path = stage / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_hash = str(manifest["option_master_sha256"])
    run_key = hashlib.sha256(
        f"{GENERATOR_VERSION}|{source_hash}|{pattern}|{seed}|{manifest['date_start']}|{manifest['date_end_exclusive']}".encode()
    ).hexdigest()[:20]
    file_entries = []
    total_rows = 0

    for day in manifest["days"]:
        path = stage / day["file"]
        rewritten = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                tick = record.get("tick")
                if not isinstance(tick, dict):
                    raise RuntimeError(f"ROW_TICK_REQUIRED:{path.name}")
                source_code = tick.pop("instrument_id", None)
                parsed_timestamp = datetime.fromisoformat(str(tick.get("timestamp", "")))
                if parsed_timestamp.tzinfo is None:
                    parsed_timestamp = parsed_timestamp.replace(tzinfo=ZoneInfo("Asia/Seoul"))
                tick["timestamp"] = parsed_timestamp.isoformat()
                if not isinstance(source_code, str) or not source_code:
                    raise RuntimeError(f"SOURCE_NATIVE_CONTRACT_CODE_REQUIRED:{path.name}")
                tick["source_instrument_code"] = source_code
                tick["instrument_identity_status"] = IDENTITY_STATUS
                synthetic_contract_material = "|".join((
                    GENERATOR_VERSION, str(tick.get("contract_class", "")),
                    str(tick.get("expiry", "")), str(tick.get("option_type", "")),
                    str(tick.get("strike_price", "")), source_code,
                ))
                tick["synthetic_contract_id"] = "SYNTHETIC_CONTRACT:" + hashlib.sha256(
                    synthetic_contract_material.encode()
                ).hexdigest()[:24]
                event_material = "|".join(
                    (run_key, str(tick.get("timestamp", "")), source_code,
                     str(tick.get("option_type", "")), str(tick.get("strike_price", "")),
                     str(tick.get("expiry", "")), str(tick.get("seq_id", "")))
                )
                record.update({
                    "synthetic": True,
                    "provenance": PROVENANCE,
                    "generator_version": GENERATOR_VERSION,
                    "seed": seed,
                    "scenario_id": f"{pattern}-seed-{seed}",
                    "run_id": run_key,
                    "event_id": hashlib.sha256(event_material.encode()).hexdigest(),
                    "identity_status": IDENTITY_STATUS,
                })
                record["dataset"] = target_name
                rewritten.append(canonical_json(record))
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for line in rewritten:
                handle.write(line + "\n")
        total_rows += len(rewritten)
        file_entries.append({
            "path": path.name,
            "rows": len(rewritten),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    replay_path = stage / "control_tower_replay.jsonl"
    with replay_path.open("w", encoding="utf-8", newline="\n") as target:
        for day in manifest["days"]:
            with (stage / day["file"]).open("r", encoding="utf-8") as source:
                shutil.copyfileobj(source, target)
    file_entries.append({
        "path": replay_path.name,
        "rows": total_rows,
        "bytes": replay_path.stat().st_size,
        "sha256": sha256_file(replay_path),
    })

    source_path = root / Path(manifest["option_master_path"])
    underlying_path = root / Path(manifest["underlying_spot_source_path"])
    calendar_paths = [root / Path(item) for item in str(manifest["calendar_source"]).split(";")]
    manifest.update({
        "schema_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "synthetic": True,
        "provenance": PROVENANCE,
        "dataset": target_name,
        "scenario_id": f"{pattern}-seed-{seed}",
        "run_id": run_key,
        "identity_source_status": IDENTITY_STATUS,
        "identity_policy": {
            "mode": "SYNTHETIC_ONLY",
            "synthetic_contract_id_namespace": "SYNTHETIC_CONTRACT:",
            "source_code_field": "source_instrument_code",
            "production_standard_instrument_id_assigned": False,
            "runtime_use": "PROHIBITED",
        },
        "expiry_policy": {
            "mode": "SYNTHETIC_CALENDAR_DERIVED",
            "policy_version": expiry_inputs["policy_version"],
            "rules": [
                "monthly: second Thursday of contract month, moved to previous trading day if holiday",
                "weekly Monday: holiday expiry moved to next trading day",
                "weekly Thursday: holiday expiry moved to previous trading day; second Thursday omitted",
            ],
            "calendar_source_role": "SCENARIO_ONLY_NOT_RUNTIME_AUTHORITY",
            "rule_source_urls": [
                "https://open.krx.co.kr/contents/OPN/01/01040202/OPN01040202.jsp",
                "https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp",
            ],
            "calendar_sha256": expiry_inputs["calendar_sha256"],
            "source_master_sha256": expiry_inputs["master_sha256"],
            "source_snapshot_date": expiry_inputs["snapshot_date"],
            "source_product_family": expiry_inputs["selected_source_product_family"],
            "computed_monthly_expiry_count": expiry_inputs["monthly_expiry_count"],
            "computed_weekly_series_expiry_count": expiry_inputs["weekly_series_expiry_count"],
        },
        "production_runtime_eligible": False,
        "validation_only": True,
        "source_native_contract_codes_only": True,
        "option_master_source_sha256": source_hash,
        "option_master_source_bytes": source_path.stat().st_size,
        "underlying_source_sha256": sha256_file(underlying_path),
        "calendar_sources": [
            {"path": str(path.relative_to(root)).replace("\\", "/"),
             "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in calendar_paths
        ],
        "event_order_policy": "date file order, timestamp ascending, deterministic source order",
        "event_identity_policy": "sha256(run_id|timestamp|source_code|option_type|strike|expiry|seq_id)",
        "event_rows": total_rows,
        "output_files": file_entries,
        "validation_status": "NOT_VALIDATED",
        "blockers": [
            IDENTITY_STATUS,
            "KRX-derived source snapshot is scenario evidence only, not a KIS runtime authority",
        ],
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def generate_p5(root: Path, output: Path, pattern: str, seed: int) -> dict:
    if output.exists():
        raise RuntimeError(f"OUTPUT_ALREADY_EXISTS:{output}")
    if seed is None:
        raise RuntimeError("SEED_REQUIRED")
    expiry_inputs = validate_synthetic_expiry_inputs(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.p5-staging-", dir=output.parent))
    try:
        generate_legacy(root, stage, pattern, seed)
        manifest = decorate_dataset(root, stage, output.name, pattern, seed, expiry_inputs)
        # Validator runs before the stage becomes the published dataset.
        from scripts.validate_synthetic_3m_p5 import validate_dataset
        report = validate_dataset(root, stage)
        manifest["validation_status"] = report["status"]
        manifest["validation_report"] = report
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # The target is never overwritten. Rename is atomic on the same volume.
        if output.exists():
            raise RuntimeError(f"OUTPUT_ALREADY_EXISTS:{output}")
        stage.rename(output)
        return manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="P5 isolated deterministic synthetic 3-month dataset generator")
    parser.add_argument("--output", required=True)
    parser.add_argument("--pattern", choices=("trend_up", "trend_down", "mean_revert", "high_volatility", "low_volatility", "shock"), required=True)
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = (root / output).resolve()
    result = generate_p5(root, output, args.pattern, args.seed)
    print(json.dumps({
        "status": result["validation_status"], "dataset": result["dataset"],
        "date_start": result["date_start"], "date_end": result["date_end"],
        "date_end_exclusive": result["date_end_exclusive"], "trading_days": result["trading_days"],
        "event_rows": result["event_rows"], "identity_source_status": result["identity_source_status"],
        "production_runtime_eligible": result["production_runtime_eligible"],
        "output": str(output), "run_id": result["run_id"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
