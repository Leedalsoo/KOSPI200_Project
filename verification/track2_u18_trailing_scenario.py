from __future__ import annotations

import copy
import hashlib
import json
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


def build_validation_only_track2_u18_trailing_scenario(
    *, source_manifest_path: str | Path, source_profile_path: str | Path, output_dir: str | Path,
) -> dict:
    """Append two deterministic U18 trailing snapshots; source files remain read-only."""
    source_manifest_path = Path(source_manifest_path).resolve()
    source_profile_path = Path(source_profile_path).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"U18_TRAILING_OUTPUT_MUST_BE_NEW:{output_dir}")

    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(source_profile_path.read_text(encoding="utf-8"))
    if manifest.get("profile_id") != profile.get("profile_id"):
        raise ValueError("U18_TRAILING_SOURCE_PROFILE_ID_MISMATCH")
    if str(manifest.get("profile_sha256") or "").lower() != _sha(source_profile_path.read_bytes()):
        raise ValueError("U18_TRAILING_SOURCE_PROFILE_HASH_MISMATCH")

    root = source_manifest_path.parent
    quote_path = _local_file(root, manifest["quote_file"], "SOURCE_QUOTES")
    candidate_path = _local_file(root, manifest["candidate_input_file"], "SOURCE_CANDIDATES")
    source_quote_bytes, source_candidate_bytes = quote_path.read_bytes(), candidate_path.read_bytes()
    rows = [json.loads(x) for x in source_quote_bytes.decode("utf-8").splitlines() if x.strip()]
    candidates = json.loads(source_candidate_bytes.decode("utf-8"))
    if len(rows) != len(candidates) * 4 or len(rows) != manifest.get("quote_rows") or len(candidates) != manifest.get("candidate_count"):
        raise ValueError("U18_TRAILING_SOURCE_ROW_COUNTS_INVALID")

    anchor_ts = "2026-10-12T09:26:00+09:00"
    base_candidates = [x for x in candidates if x.get("observed_at") == anchor_ts]
    base_rows = [x for x in rows if x.get("timestamp") == anchor_ts]
    if len(base_candidates) != 1 or len(base_rows) != 4:
        raise ValueError("U18_TRAILING_ANCHOR_FOUR_LEG_REQUIRED")
    base_candidate = base_candidates[0]
    if {x.get("leg_role") for x in base_rows} != {"inner_put", "inner_call", "outer_put", "outer_call"}:
        raise ValueError("U18_TRAILING_ANCHOR_LEG_SET_INVALID")
    anchor_hash = _sha(json.dumps(base_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())

    new_candidates, new_rows, additions = [], [], []
    snapshots = (
        ("2026-10-12T09:26:21+09:00", "1034.97", "2.00", "PEAK"),
        ("2026-10-12T09:26:30+09:00", "1034.76", "1.50", "PULLBACK"),
    )
    for timestamp, underlying, shift_text, phase in snapshots:
        anchor_dt, observed_dt = datetime.fromisoformat(anchor_ts), datetime.fromisoformat(timestamp)
        age = int((observed_dt - anchor_dt).total_seconds())
        shift = Decimal(shift_text)
        if observed_dt.tzinfo is None or age <= 0 or shift <= 0 or shift % Decimal("0.05") != 0:
            raise ValueError("U18_TRAILING_SNAPSHOT_TIME_OR_TICK_INVALID")
        max_anchor_age = max(int(x["market_calibration"]["source_anchor_max_age_seconds"]) for x in base_rows)
        if max_anchor_age + age > 900:
            raise ValueError("U18_TRAILING_SOURCE_ANCHOR_AGE_EXCEEDS_900_SECONDS")

        candidate_id = f"S2-U18-TRAILING-{phase}"
        generation = {
            "namespace": "SYNTHETIC:DERIVED_SCENARIO",
            "purpose": "U18_TRAILING_EXIT_RUNTIME_VALIDATION_ONLY",
            "rule": "POSITION_AWARE_MID_SHIFT_PRESERVE_SOURCE_SPREAD_AND_DEPTH",
            "source_anchor_timestamp": anchor_ts,
            "source_anchor_quote_sha256": anchor_hash,
            "generated_quote_timestamp": timestamp,
            "source_anchor_age_seconds": age,
            "inner_long_mid_shift_points": shift_text,
            "outer_short_mid_shift_points": f"-{shift_text}",
            "target_path_phase": phase,
            "target_net_pnl_ratio_rounded": "0.5829" if phase == "PEAK" else "0.3313",
            "deterministic": True,
            "validation_only": True,
            "market_observation_claim": False,
        }
        candidate = copy.deepcopy(base_candidate)
        candidate.update({
            "candidate_id": candidate_id, "observed_at": timestamp, "underlying_price": underlying,
            "source_observation_id": f"accepted-runtime-v2-event:{timestamp}",
            "source_anchor_observation_id": base_candidate.get("source_observation_id"),
            "source_anchor_timestamp": anchor_ts, "generated_quote_timestamp": timestamp,
            "source_anchor_quote_sha256": anchor_hash, "synthetic_generation": generation,
        })
        new_candidates.append(candidate)

        for original in base_rows:
            row = copy.deepcopy(original)
            signed_shift = shift if row["leg_role"] in {"inner_put", "inner_call"} else -shift
            for field in ("bid", "ask", "last"):
                row[field] = format(Decimal(str(row[field])) + signed_shift, ".2f")
            row.update({
                "candidate_id": candidate_id, "timestamp": timestamp,
                "source_anchor_observation_id": base_candidate.get("source_observation_id"),
                "source_anchor_timestamp": anchor_ts, "generated_quote_timestamp": timestamp,
                "source_anchor_quote_sha256": anchor_hash, "synthetic_generation": generation,
                "validation_profile_binding": "U18_TRAILING_PATH_SYNTHETIC_SUPPLEMENT_V1",
            })
            calibration = copy.deepcopy(row["market_calibration"])
            calibration["candidate_underlying_price"] = underlying
            calibration["source_anchor_max_age_seconds"] = int(calibration["source_anchor_max_age_seconds"]) + age
            for key in ("iv_anchor_ages_seconds", "spread_anchor_ages_seconds"):
                calibration[key] = [int(v) + age for v in calibration[key]]
            calibration["target_quote_age_seconds"] = 0
            row["market_calibration"] = calibration
            new_rows.append(row)

        additions.append({
            "candidate_id": candidate_id, "timestamp": timestamp, "quote_rows": 4,
            "source_anchor_timestamp": anchor_ts, "source_anchor_age_seconds": age,
            "source_anchor_max_age_seconds": max_anchor_age + age, "phase": phase,
            "deterministic": True, "validation_only": True,
        })

    output_dir.mkdir(parents=True, exist_ok=False)
    all_candidates, all_rows = candidates + new_candidates, rows + new_rows
    candidate_out = output_dir / "candidate_inputs.json"
    quote_out = output_dir / "four_leg_quotes.u18_trailing_supplement.v1.jsonl"
    candidate_out.write_text(json.dumps(all_candidates, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    quote_out.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for x in all_rows), encoding="utf-8", newline="\n")

    result_manifest = copy.deepcopy(manifest)
    if "validation_profile_binding" in result_manifest:
        result_manifest["source_validation_profile_binding"] = result_manifest.pop("validation_profile_binding")
    result_manifest["candidate_count"], result_manifest["quote_rows"] = len(all_candidates), len(all_rows)
    result_manifest["candidate_input_file"] = {"path": candidate_out.name, "sha256": _sha(candidate_out.read_bytes())}
    result_manifest["quote_file"] = {"path": quote_out.name, "rows": len(all_rows), "sha256": _sha(quote_out.read_bytes())}
    result_manifest["candidate_calibration"] = list(result_manifest.get("candidate_calibration") or []) + [
        {"candidate_id": c["candidate_id"], "cross_type_iv_fallback_legs": 0,
         "max_source_anchor_age_seconds": a["source_anchor_max_age_seconds"],
         "quote_rows": 4, "timestamp": c["observed_at"]}
        for c, a in zip(new_candidates, additions, strict=True)
    ]
    result_manifest["u18_trailing_supplement"] = {
        "source_manifest_sha256": _sha(source_manifest_path.read_bytes()),
        "source_quote_sha256": _sha(source_quote_bytes),
        "source_candidate_inputs_sha256": _sha(source_candidate_bytes),
        "source_anchor_quote_sha256": anchor_hash,
        "generation_rule": "POSITION_AWARE_MID_SHIFT_PRESERVE_SOURCE_SPREAD_AND_DEPTH",
        "snapshots": additions, "validation_only": True, "production_policy_approval": False,
    }
    manifest_out = output_dir / "manifest.json"
    manifest_out.write_text(json.dumps(result_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if len(all_candidates) != 23 or len(all_rows) != 92:
        raise ValueError("U18_TRAILING_SUPPLEMENT_OUTPUT_COUNTS_INVALID")
    return {
        "manifest_path": manifest_out, "quote_path": quote_out, "candidate_inputs_path": candidate_out,
        "source_manifest_sha256": _sha(source_manifest_path.read_bytes()),
        "source_quote_sha256": _sha(source_quote_bytes), "source_candidate_inputs_sha256": _sha(source_candidate_bytes),
        "source_anchor_quote_sha256": anchor_hash, "manifest_sha256": _sha(manifest_out.read_bytes()),
        "quote_sha256": _sha(quote_out.read_bytes()), "candidate_inputs_sha256": _sha(candidate_out.read_bytes()),
        "candidate_count": len(all_candidates), "quote_rows": len(all_rows), "supplemental_snapshots": additions,
    }
