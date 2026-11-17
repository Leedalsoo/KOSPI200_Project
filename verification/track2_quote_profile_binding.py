from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PROFILE_BINDING_FIELDS = {
    "scenario_profile_id",
    "scenario_profile_sha256",
    "source_scenario_profile_id",
    "source_scenario_profile_sha256",
    "validation_profile_binding",
}
_ALLOWED_PROFILE_DIFFERENCES = {"profile_id", "U18_exit_policy", "exit_path_test", "limitations"}


@dataclass(frozen=True)
class Track2QuoteProfileBindingResult:
    manifest_path: Path
    quote_path: Path
    candidate_inputs_path: Path
    source_manifest_sha256: str
    source_quote_sha256: str
    derived_manifest_sha256: str
    derived_quote_sha256: str
    candidate_inputs_sha256: str
    quote_rows: int
    candidates: int
    source_profile_id: str
    target_profile_id: str
    target_profile_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_JSON_INVALID:{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_OBJECT_REQUIRED:{path}")
    return value


def _manifest_local_file(root: Path, descriptor: Any, label: str) -> Path:
    if not isinstance(descriptor, dict):
        raise ValueError(f"{label}_DESCRIPTOR_INVALID")
    name = str(descriptor.get("path") or "").strip()
    if not name or Path(name).name != name:
        raise ValueError(f"{label}_PATH_INVALID")
    path = (root / name).resolve()
    if path.parent != root.resolve() or not path.is_file():
        raise ValueError(f"{label}_FILE_REQUIRED:{path}")
    if _sha256(path.read_bytes()) != str(descriptor.get("sha256") or "").lower():
        raise ValueError(f"{label}_HASH_MISMATCH:{path.name}")
    return path


def bind_validation_only_track2_quote_scenario_profile(
    *,
    source_manifest_path: str | Path,
    source_profile_path: str | Path,
    target_profile_path: str | Path,
    output_dir: str | Path,
    purpose: str,
) -> Track2QuoteProfileBindingResult:
    """Create a new profile-bound sidecar without changing source quote values.

    Only U18/profile-binding metadata may change. The source manifest, quote file,
    candidate inputs, accepted dataset, and their hashes are left untouched.
    """
    source_manifest_path = Path(source_manifest_path).resolve()
    source_profile_path = Path(source_profile_path).resolve()
    target_profile_path = Path(target_profile_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not purpose.strip():
        raise ValueError("VALIDATION_PROFILE_BINDING_PURPOSE_REQUIRED")
    if output_dir.exists():
        raise FileExistsError(f"PROFILE_BINDING_OUTPUT_MUST_BE_NEW:{output_dir}")
    if not source_manifest_path.is_file() or not source_profile_path.is_file() or not target_profile_path.is_file():
        raise ValueError("PROFILE_BINDING_SOURCE_AND_PROFILE_FILES_REQUIRED")

    source_manifest = _read_json(source_manifest_path, "SOURCE_MANIFEST")
    source_profile = _read_json(source_profile_path, "SOURCE_PROFILE")
    target_profile = _read_json(target_profile_path, "TARGET_PROFILE")
    source_manifest_sha = _sha256(source_manifest_path.read_bytes())
    source_profile_sha = _sha256(source_profile_path.read_bytes())
    target_profile_sha = _sha256(target_profile_path.read_bytes())

    if (source_manifest.get("profile_id") != source_profile.get("profile_id")
            or str(source_manifest.get("profile_sha256") or "").lower() != source_profile_sha):
        raise ValueError("SOURCE_MANIFEST_PROFILE_BINDING_MISMATCH")
    if source_profile.get("U21_quote_policy") != target_profile.get("U21_quote_policy"):
        raise ValueError("TARGET_PROFILE_U21_POLICY_MISMATCH")
    if source_profile.get("market_calibration") != target_profile.get("market_calibration"):
        raise ValueError("TARGET_PROFILE_MARKET_CALIBRATION_MISMATCH")
    keys = set(source_profile) | set(target_profile)
    changed = {key for key in keys if source_profile.get(key) != target_profile.get(key)}
    if changed - _ALLOWED_PROFILE_DIFFERENCES:
        raise ValueError(f"TARGET_PROFILE_UNRELATED_FIELDS_CHANGED:{','.join(sorted(changed - _ALLOWED_PROFILE_DIFFERENCES))}")
    if any(target_profile.get(flag) is not False for flag in (
        "execution_enabled", "order_submission_enabled", "live_api_enabled", "real_vts_api_enabled"
    )):
        raise ValueError("TARGET_PROFILE_MUST_REMAIN_VALIDATION_ONLY")
    if not isinstance(target_profile.get("U18_exit_policy"), dict) or not target_profile["U18_exit_policy"]:
        raise ValueError("TARGET_PROFILE_U18_POLICY_REQUIRED")
    if (str(source_manifest.get("u21", {}).get("max_age_seconds")) != str(target_profile["U21_quote_policy"].get("max_age_seconds"))
            or str(source_manifest.get("u21", {}).get("max_spread")) != str(target_profile["U21_quote_policy"].get("max_spread"))
            or str(source_manifest.get("u21", {}).get("tick_size")) != str(target_profile["U21_quote_policy"].get("tick_size"))):
        raise ValueError("SOURCE_MANIFEST_TARGET_PROFILE_U21_MISMATCH")
    if source_manifest.get("price_model") != target_profile.get("market_calibration", {}).get("pricing_model"):
        raise ValueError("SOURCE_MANIFEST_TARGET_PROFILE_PRICE_MODEL_MISMATCH")

    source_root = source_manifest_path.parent.resolve()
    source_quote_path = _manifest_local_file(source_root, source_manifest.get("quote_file"), "SOURCE_QUOTE_FILE")
    source_candidate_path = _manifest_local_file(source_root, source_manifest.get("candidate_input_file"), "SOURCE_CANDIDATE_INPUTS")
    source_rows = [json.loads(line) for line in source_quote_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(source_rows) != int(source_manifest.get("quote_rows", -1)):
        raise ValueError("SOURCE_QUOTE_ROW_COUNT_MISMATCH")
    if len({str(row.get("timestamp")) for row in source_rows}) != int(source_manifest.get("candidate_count", -1)):
        raise ValueError("SOURCE_CANDIDATE_TIMESTAMP_COUNT_MISMATCH")

    bound_rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        if (source_row.get("scenario_profile_id") != source_profile.get("profile_id")
                or str(source_row.get("scenario_profile_sha256") or "").lower() != source_profile_sha):
            raise ValueError("SOURCE_QUOTE_ROW_PROFILE_BINDING_MISMATCH")
        row = copy.deepcopy(source_row)
        row["source_scenario_profile_id"] = row["scenario_profile_id"]
        row["source_scenario_profile_sha256"] = row["scenario_profile_sha256"]
        row["scenario_profile_id"] = target_profile["profile_id"]
        row["scenario_profile_sha256"] = target_profile_sha
        row["validation_profile_binding"] = purpose
        bound_rows.append(row)

    output_dir.mkdir(parents=True, exist_ok=False)
    candidate_dest = output_dir / source_candidate_path.name
    shutil.copyfile(source_candidate_path, candidate_dest)
    quote_dest = output_dir / "four_leg_quotes.profile_bound.jsonl"
    with quote_dest.open("w", encoding="utf-8", newline="\n") as handle:
        for row in bound_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    for before, after in zip(source_rows, bound_rows, strict=True):
        if ({key: value for key, value in before.items() if key not in _PROFILE_BINDING_FIELDS}
                != {key: value for key, value in after.items() if key not in _PROFILE_BINDING_FIELDS}):
            raise ValueError("PROFILE_BINDING_CHANGED_NON_PROFILE_QUOTE_FIELDS")

    manifest = copy.deepcopy(source_manifest)
    manifest["profile_id"] = target_profile["profile_id"]
    manifest["profile_sha256"] = target_profile_sha
    manifest["quote_file"] = dict(manifest["quote_file"])
    manifest["quote_file"]["path"] = quote_dest.name
    manifest["quote_file"]["sha256"] = _sha256(quote_dest.read_bytes())
    manifest["validation_profile_binding"] = {
        "source_manifest_sha256": source_manifest_sha,
        "source_profile_id": source_profile["profile_id"],
        "source_profile_sha256": source_profile_sha,
        "bound_profile_id": target_profile["profile_id"],
        "bound_profile_sha256": target_profile_sha,
        "purpose": purpose,
        "quote_prices_sizes_timestamps_and_market_calibration_changed": False,
        "production_policy_approval": False,
    }
    manifest_dest = output_dir / "manifest.json"
    manifest_dest.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    candidate_hash = _sha256(candidate_dest.read_bytes())
    if candidate_hash != _sha256(source_candidate_path.read_bytes()):
        raise ValueError("PROFILE_BINDING_CHANGED_CANDIDATE_INPUTS")

    return Track2QuoteProfileBindingResult(
        manifest_path=manifest_dest,
        quote_path=quote_dest,
        candidate_inputs_path=candidate_dest,
        source_manifest_sha256=source_manifest_sha,
        source_quote_sha256=_sha256(source_quote_path.read_bytes()),
        derived_manifest_sha256=_sha256(manifest_dest.read_bytes()),
        derived_quote_sha256=_sha256(quote_dest.read_bytes()),
        candidate_inputs_sha256=candidate_hash,
        quote_rows=len(bound_rows),
        candidates=len({str(row.get("timestamp")) for row in bound_rows}),
        source_profile_id=str(source_profile["profile_id"]),
        target_profile_id=str(target_profile["profile_id"]),
        target_profile_sha256=target_profile_sha,
    )