from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "synthetic_market_data" / "20261022_strategy_e2e" / "20261020.jsonl"
OUTPUTS = {
    "s5_daily_boundary": ROOT / "data" / "synthetic_market_data" / "20261022_s5_daily_boundary",
    "s7_weekly_contract": ROOT / "data" / "synthetic_market_data" / "20261022_s7_weekly_contract",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"SYNTHETIC_SOURCE_MISSING:{SOURCE}")
    for target in OUTPUTS.values():
        if target.exists():
            raise SystemExit(f"REFUSE_OVERWRITE_EXISTING_PATH:{target}")

    source_rows = [
        json.loads(line)
        for line in SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(source_rows) != 155:
        raise SystemExit(f"UNEXPECTED_SOURCE_ROW_COUNT:{len(source_rows)}")
    if any(row.get("provenance") != "SYNTHETIC" for row in source_rows):
        raise SystemExit("NON_SYNTHETIC_SOURCE_ROW_DETECTED")

    scenarios = {
        "s5_daily_boundary": {
            "scenario_id": "S5_DAILY_BOUNDARY_SYMBOL_GATE",
            "purpose": "Validate synthetic daily open/previous-close source wiring only.",
            "mutate": lambda row: row["tick"].update(
                underlying_symbol="KOSPI200_SYNTHETIC"
            ),
            "extra": {"daily_boundary_source_type": "SYNTHETIC"},
        },
        "s7_weekly_contract": {
            "scenario_id": "S7_EXPLICIT_WEEKLY_CONTRACT_GATE",
            "purpose": "Validate weekly-contract input classification only; expiry is a synthetic scenario label.",
            "mutate": lambda row: row["tick"].update(
                underlying_symbol="KOSPI200_SYNTHETIC",
                contract_class="weekly",
                expiry="20261026",
            ),
            "extra": {
                "contract_class": "weekly",
                "synthetic_expiry_yyyymmdd": "20261026",
                "expiry_is_authoritative": False,
            },
        },
    }

    for name, target in OUTPUTS.items():
        config = scenarios[name]
        target.mkdir(parents=True, exist_ok=False)
        rows = []
        for original in source_rows:
            row = json.loads(json.dumps(original))
            config["mutate"](row)
            meta = row.setdefault("scenario_metadata", {})
            meta.update(
                {
                    "scenario_id": config["scenario_id"],
                    "purpose": config["purpose"],
                    "source_type": "SYNTHETIC",
                    "runtime_eligible": False,
                    "validation_only": True,
                    **config["extra"],
                }
            )
            row["provenance"] = "SYNTHETIC"
            rows.append(row)
        dataset = target / "20261020.jsonl"
        with dataset.open("x", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        manifest = {
            "schema_version": "synthetic-boundary-fixture-manifest-v1",
            "scenario_id": config["scenario_id"],
            "source_type": "SYNTHETIC",
            "runtime_eligible": False,
            "validation_only": True,
            "source_path": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": sha256(SOURCE),
            "rows": len(rows),
            "dataset_path": str(dataset.relative_to(ROOT)).replace("\\", "/"),
            "dataset_sha256": sha256(dataset),
            **config["extra"],
        }
        manifest_path = target / "manifest.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        manifest["manifest_sha256"] = sha256(manifest_path)
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
