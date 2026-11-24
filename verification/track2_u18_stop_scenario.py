from __future__ import annotations
import copy, hashlib, json
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_file(root: Path, descriptor: dict, label: str) -> Path:
    name = str(descriptor.get("path") or "").strip()
    if not name or Path(name).name != name:
        raise ValueError(f"{label}_PATH_INVALID")
    path = (root / name).resolve()
    if path.parent != root.resolve() or not path.is_file():
        raise ValueError(f"{label}_FILE_REQUIRED")
    if _sha(path.read_bytes()) != str(descriptor.get("sha256") or "").lower():
        raise ValueError(f"{label}_HASH_MISMATCH")
    return path


def build_validation_only_track2_u18_stop_scenario(
    *,
    source_manifest_path: str | Path,
    source_profile_path: str | Path,
    accepted_dataset_path: str | Path,
    output_dir: str | Path,
) -> dict:
    source_manifest_path, source_profile_path, accepted_dataset_path, output_dir = map(
        Path,
        (source_manifest_path, source_profile_path, accepted_dataset_path, output_dir),
    )
    source_manifest_path, source_profile_path, accepted_dataset_path, output_dir = (
        p.resolve()
        for p in (
            source_manifest_path,
            source_profile_path,
            accepted_dataset_path,
            output_dir,
        )
    )
    if output_dir.exists():
        raise FileExistsError(f"U18_STOP_OUTPUT_MUST_BE_NEW:{output_dir}")
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(source_profile_path.read_text(encoding="utf-8"))
    if manifest.get("profile_id") != profile.get("profile_id") or str(
        manifest.get("profile_sha256") or ""
    ).lower() != _sha(source_profile_path.read_bytes()):
        raise ValueError("U18_STOP_SOURCE_PROFILE_BINDING_MISMATCH")
    accepted_manifest_path, accepted_partition_path = (
        accepted_dataset_path / "manifest.json",
        accepted_dataset_path / "20261012.jsonl",
    )
    if not accepted_manifest_path.is_file() or not accepted_partition_path.is_file():
        raise ValueError("U18_STOP_ACCEPTED_SOURCE_FILES_REQUIRED")
    accepted_manifest_bytes = accepted_manifest_path.read_bytes()
    if (
        _sha(accepted_manifest_bytes)
        != str(manifest.get("base_manifest_sha256") or "").lower()
    ):
        raise ValueError("U18_STOP_ACCEPTED_MANIFEST_HASH_MISMATCH")
    accepted_manifest = json.loads(accepted_manifest_bytes.decode("utf-8"))
    part = next(
        (x for x in accepted_manifest.get("days", []) if x.get("date") == "20261012"),
        None,
    )
    if (
        part is None
        or _sha(accepted_partition_path.read_bytes())
        != str(part.get("sha256") or "").lower()
    ):
        raise ValueError("U18_STOP_ACCEPTED_PARTITION_HASH_MISMATCH")
    source_root = source_manifest_path.parent
    quote_path = _local_file(source_root, manifest["quote_file"], "SOURCE_QUOTES")
    candidate_path = _local_file(
        source_root, manifest["candidate_input_file"], "SOURCE_CANDIDATES"
    )
    quote_bytes, candidate_bytes = quote_path.read_bytes(), candidate_path.read_bytes()
    rows = [
        json.loads(x) for x in quote_bytes.decode("utf-8").splitlines() if x.strip()
    ]
    candidates = json.loads(candidate_bytes.decode("utf-8"))
    if (
        len(rows) != len(candidates) * 4
        or len(rows) != manifest.get("quote_rows")
        or len(candidates) != manifest.get("candidate_count")
    ):
        raise ValueError("U18_STOP_SOURCE_ROW_COUNTS_INVALID")
    anchor_ts, target_ts = "2026-10-12T09:26:00+09:00", "2026-10-12T09:26:21+09:00"
    base_candidates = [x for x in candidates if x.get("observed_at") == anchor_ts]
    base_rows = [x for x in rows if x.get("timestamp") == anchor_ts]
    roles = {"inner_put", "inner_call", "outer_put", "outer_call"}
    if (
        len(base_candidates) != 1
        or len(base_rows) != 4
        or {x.get("leg_role") for x in base_rows} != roles
    ):
        raise ValueError("U18_STOP_ANCHOR_FOUR_LEG_REQUIRED")
    base_candidate = base_candidates[0]
    anchor_hash = _sha(
        json.dumps(
            base_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    underlying_rows = []
    for line in accepted_partition_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            tick = item.get("tick") or {}
            if (
                tick.get("timestamp") == target_ts
                and tick.get("underlying_source") == "KIS:H0UPCNT0"
            ):
                underlying_rows.append(item)
    values = {str(Decimal(str(x["tick"]["underlying_price"]))) for x in underlying_rows}
    if not underlying_rows or len(values) != 1:
        raise ValueError("U18_STOP_EXACT_TIMESTAMP_KIS_UNDERLYING_ANCHOR_REQUIRED")
    underlying = Decimal(next(iter(values)))
    underlying_ids = sorted(
        {
            str(x.get("scenario_metadata", {}).get("source_observation_id") or "")
            for x in underlying_rows
            if x.get("scenario_metadata", {}).get("source_observation_id")
        }
    )
    if not underlying_ids:
        raise ValueError("U18_STOP_UNDERLYING_SOURCE_OBSERVATION_ID_REQUIRED")
    age = int(
        (
            datetime.fromisoformat(target_ts) - datetime.fromisoformat(anchor_ts)
        ).total_seconds()
    )
    max_anchor_age = max(
        int(x["market_calibration"]["source_anchor_max_age_seconds"]) for x in base_rows
    )
    if age <= 0 or max_anchor_age + age > 900:
        raise ValueError("U18_STOP_SOURCE_ANCHOR_AGE_INVALID")
    shift, candidate_id = Decimal("2.00"), "S2-U18-STOP-LOSS"
    generation = {
        "namespace": "SYNTHETIC:DERIVED_SCENARIO",
        "purpose": "U18_STOP_LOSS_EXIT_RUNTIME_VALIDATION_ONLY",
        "rule": "POSITION_AWARE_MID_STRESS_PRESERVE_SOURCE_SPREAD_AND_DEPTH",
        "source_anchor_timestamp": anchor_ts,
        "source_anchor_quote_sha256": anchor_hash,
        "generated_quote_timestamp": target_ts,
        "source_anchor_age_seconds": age,
        "underlying_anchor_source": "KIS:H0UPCNT0",
        "underlying_anchor_timestamp": target_ts,
        "underlying_anchor_observation_ids": underlying_ids,
        "underlying_anchor_price": format(underlying, ".2f"),
        "inner_long_mid_shift_points": "-2.00",
        "outer_short_mid_shift_points": "+2.00",
        "deterministic": True,
        "validation_only": True,
        "market_observation_claim": False,
        "production_policy_approval": False,
    }
    candidate = copy.deepcopy(base_candidate)
    candidate.update(
        {
            "candidate_id": candidate_id,
            "observed_at": target_ts,
            "underlying_price": format(underlying, ".2f"),
            "source_observation_id": f"accepted-runtime-v2-event:{target_ts}",
            "source_anchor_observation_id": base_candidate.get("source_observation_id"),
            "source_anchor_timestamp": anchor_ts,
            "generated_quote_timestamp": target_ts,
            "source_anchor_quote_sha256": anchor_hash,
            "underlying_anchor_source": "KIS:H0UPCNT0",
            "underlying_anchor_observation_ids": underlying_ids,
            "synthetic_generation": generation,
        }
    )
    new_rows = []
    for original in base_rows:
        row = copy.deepcopy(original)
        signed_shift = (
            -shift if row["leg_role"] in {"inner_put", "inner_call"} else shift
        )
        for field in ("bid", "ask", "last"):
            value = Decimal(str(row[field])) + signed_shift
            if value <= 0 or value % Decimal("0.05") != 0:
                raise ValueError("U18_STOP_GENERATED_PRICE_INVALID")
            row[field] = format(value, ".2f")
        if Decimal(row["ask"]) <= Decimal(row["bid"]):
            raise ValueError("U18_STOP_GENERATED_BOOK_INVALID")
        row.update(
            {
                "candidate_id": candidate_id,
                "timestamp": target_ts,
                "source_anchor_observation_id": base_candidate.get(
                    "source_observation_id"
                ),
                "source_anchor_timestamp": anchor_ts,
                "generated_quote_timestamp": target_ts,
                "source_anchor_quote_sha256": anchor_hash,
                "underlying_anchor_source": "KIS:H0UPCNT0",
                "underlying_anchor_observation_ids": underlying_ids,
                "synthetic_generation": generation,
                "validation_profile_binding": "U18_STOP_PATH_SYNTHETIC_SUPPLEMENT_V1",
                "limitations": list(row.get("limitations") or [])
                + [
                    "Supplemental bid/ask mids are a deterministic stress shock, not observed option quotes or a Black-Scholes reprice."
                ],
            }
        )
        calibration = copy.deepcopy(row["market_calibration"])
        calibration["candidate_underlying_price"] = format(underlying, ".2f")
        calibration["candidate_underlying_provenance"] = (
            "KIS:H0UPCNT0_OBSERVED_SPOT_ANCHOR"
        )
        calibration["source_anchor_max_age_seconds"] = (
            int(calibration["source_anchor_max_age_seconds"]) + age
        )
        for key in ("iv_anchor_ages_seconds", "spread_anchor_ages_seconds"):
            calibration[key] = [int(v) + age for v in calibration[key]]
        calibration["target_quote_age_seconds"] = 0
        calibration["supplemental_price_generation_rule"] = generation["rule"]
        row["market_calibration"] = calibration
        new_rows.append(row)
    output_dir.mkdir(parents=True, exist_ok=False)
    all_candidates, all_rows = candidates + [candidate], rows + new_rows
    candidate_out, quote_out = (
        output_dir / "candidate_inputs.json",
        output_dir / "four_leg_quotes.u18_stop_supplement.v1.jsonl",
    )
    candidate_out.write_text(
        json.dumps(all_candidates, ensure_ascii=False, sort_keys=True, indent=2)
        + chr(10),
        encoding="utf-8",
    )
    quote_out.write_text(
        "".join(
            json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + chr(10)
            for x in all_rows
        ),
        encoding="utf-8",
        newline=chr(10),
    )
    result = copy.deepcopy(manifest)
    result["candidate_count"], result["quote_rows"] = len(all_candidates), len(all_rows)
    result["candidate_input_file"] = {
        "path": candidate_out.name,
        "sha256": _sha(candidate_out.read_bytes()),
    }
    result["quote_file"] = {
        "path": quote_out.name,
        "rows": len(all_rows),
        "sha256": _sha(quote_out.read_bytes()),
    }
    result["candidate_calibration"] = list(
        result.get("candidate_calibration") or []
    ) + [
        {
            "candidate_id": candidate_id,
            "cross_type_iv_fallback_legs": 0,
            "max_source_anchor_age_seconds": max_anchor_age + age,
            "quote_rows": 4,
            "timestamp": target_ts,
        }
    ]
    result["u18_stop_supplement"] = {
        "source_manifest_sha256": _sha(source_manifest_path.read_bytes()),
        "source_quote_sha256": _sha(quote_bytes),
        "source_candidate_inputs_sha256": _sha(candidate_bytes),
        "source_anchor_quote_sha256": anchor_hash,
        "generation_rule": generation["rule"],
        "underlying_anchor_source": "KIS:H0UPCNT0",
        "underlying_anchor_timestamp": target_ts,
        "underlying_anchor_observation_ids": underlying_ids,
        "snapshots": [
            {
                "candidate_id": candidate_id,
                "timestamp": target_ts,
                "quote_rows": 4,
                "source_anchor_timestamp": anchor_ts,
                "source_anchor_age_seconds": age,
                "source_anchor_max_age_seconds": max_anchor_age + age,
                "underlying_anchor_price": format(underlying, ".2f"),
                "deterministic": True,
                "validation_only": True,
            }
        ],
        "supplemental_price_model": "POSITION_AWARE_MID_STRESS_V1",
        "market_observation_claim": False,
        "validation_only": True,
        "production_policy_approval": False,
    }
    result["limitations"] = list(result.get("limitations") or []) + [
        "U18 stop supplement uses a deterministic position-aware mid stress shock; it is not an observed option quote or model reprice."
    ]
    manifest_out = output_dir / "manifest.json"
    manifest_out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + chr(10),
        encoding="utf-8",
    )
    if len(all_candidates) != 22 or len(all_rows) != 88:
        raise ValueError("U18_STOP_SUPPLEMENT_OUTPUT_COUNTS_INVALID")
    return {
        "manifest_path": manifest_out,
        "quote_path": quote_out,
        "candidate_inputs_path": candidate_out,
        "source_manifest_sha256": _sha(source_manifest_path.read_bytes()),
        "source_quote_sha256": _sha(quote_bytes),
        "source_candidate_inputs_sha256": _sha(candidate_bytes),
        "source_anchor_quote_sha256": anchor_hash,
        "manifest_sha256": _sha(manifest_out.read_bytes()),
        "quote_sha256": _sha(quote_out.read_bytes()),
        "candidate_inputs_sha256": _sha(candidate_out.read_bytes()),
        "candidate_count": len(all_candidates),
        "quote_rows": len(all_rows),
        "supplemental_snapshots": result["u18_stop_supplement"]["snapshots"],
    }
