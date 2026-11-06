"""Create a fresh rank-5/rank-6 synthetic S6 scenario dataset without mutating source inputs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = ROOT / "data/derived_scenario/q25_a2_1_strategy6/20261102.jsonl"
SOURCE_MANIFEST = ROOT / "reports/synth/Q25_A4_S6_SYN_EVT_MANIFEST_20261106_v3.json"
OUT_DIR = ROOT / "data/derived_scenario/q25_a4_s6_rank5_rank6_v2"
OUT_DATA = OUT_DIR / "20261102.jsonl"
OUT_MANIFEST = ROOT / "reports/synth/Q25_A4_S6_RANK5_RANK6_MANIFEST_20261106_v2.json"
if any(path.exists() for path in (OUT_DATA, OUT_MANIFEST, OUT_MANIFEST.with_suffix(".json.sha256"))):
    raise SystemExit("REFUSE_OVERWRITE_RANK5_RANK6_DERIVED_ARTIFACT")
if not SOURCE_DATA.is_file() or not SOURCE_MANIFEST.is_file():
    raise SystemExit("SOURCE_SYNTHETIC_DATA_OR_MANIFEST_MISSING")

def write_group(handle, rows, seq):
    templates = {}
    for row in rows:
        tick = row["tick"]
        templates[(str(tick["option_type"]).upper(), float(tick["strike_price"]))] = row
    put_base = templates.get(("PUT", 487.5))
    call_base = templates.get(("CALL", 512.5))
    if put_base is None or call_base is None:
        raise ValueError("RANK5_REFERENCE_QUOTES_MISSING_FOR_TIMESTAMP")
    for row in rows:
        seq += 1
        row["tick"]["seq_id"] = seq
        row["scenario_metadata"]["event_sequence"] = seq
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    spot = float(rows[0]["tick"]["underlying_price"])
    for base, option_type, strike in ((put_base, "PUT", 485.0), (call_base, "CALL", 515.0)):
        row = json.loads(json.dumps(base))
        tick = row["tick"]
        tick["strike_price"] = strike
        tick["option_type"] = option_type
        code = f"SYNTH-S6-1-20261102-{option_type}-{strike:g}"
        synthetic_id = f"SYNTHETIC_CONTRACT:{code}"
        tick["symbol"] = code
        tick["source_instrument_code"] = code
        tick["synthetic_contract_id"] = synthetic_id
        tick["instrument_id"] = ""
        tick["instrument_identity_status"] = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
        intrinsic = max(0.0, strike - spot) if option_type == "PUT" else max(0.0, spot - strike)
        time_value = max(0.01, float(base["tick"].get("time_value", base["tick"]["last_price"])))
        mid = max(0.01, intrinsic + time_value)
        tick["intrinsic_value"] = round(intrinsic, 6)
        tick["time_value"] = round(time_value, 6)
        tick["last_price"] = round(mid, 6)
        tick["theoretical_mid_price"] = round(mid, 6)
        tick["bid_price"] = round(max(0.01, mid - 0.05), 6)
        tick["ask_price"] = round(mid + 0.05, 6)
        seq += 1
        tick["seq_id"] = seq
        meta = row["scenario_metadata"]
        meta["event_sequence"] = seq
        meta["scenario_event_id"] = hashlib.sha256(
            f"Q25-A4-RANK6|{meta['scenario_id']}|{tick['timestamp']}|{option_type}|{strike}".encode()
        ).hexdigest()
        meta["generator_version"] = "q25-a4-s6-rank5-rank6-extension-v2"
        meta["field_origin"] = "synthetic"
        meta["identity_source_status"] = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
        meta["execution_evidence"] = "NOT_GENERATED"
        meta["rank6_extension"] = True
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return seq

OUT_DIR.mkdir(parents=True, exist_ok=False)
seq = 0
rows_written = 0
group = []
group_key = None
with SOURCE_DATA.open(encoding="utf-8") as source, OUT_DATA.open("x", encoding="utf-8", newline="\n") as target:
    for line in source:
        row = json.loads(line)
        tick = row["tick"]
        key = (str(row["scenario_metadata"]["scenario_id"]), str(tick["timestamp"]))
        if group and key != group_key:
            seq = write_group(target, group, seq)
            rows_written += len(group) + 2
            group = []
        group_key = key
        group.append(row)
    if group:
        seq = write_group(target, group, seq)
        rows_written += len(group) + 2

dataset_hash = hashlib.sha256(OUT_DATA.read_bytes()).hexdigest()
source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
payload = dict(source_manifest)
payload["output_path"] = "data/derived_scenario/q25_a4_s6_rank5_rank6_v2/20261102.jsonl"
payload["output_sha256"] = dataset_hash
payload["dataset_sha256"] = dataset_hash
payload["output_bytes"] = OUT_DATA.stat().st_size
payload["rows"] = rows_written
payload["strike_candidates"] = sorted(set(float(x) for x in source_manifest["strike_candidates"]) | {485.0, 515.0})
payload["scenario_id"] = "q25_a4_s6_rank5_rank6_v2_runtime_matrix"
payload["a4_validation_extension"] = {
    **source_manifest.get("a4_validation_extension", {}),
    "purpose": "Q25_A4_S6_RANK5_RANK6_NATURAL_RUNTIME_MATRIX",
    "source_manifest": SOURCE_MANIFEST.name,
    "source_manifest_sha256": hashlib.sha256(SOURCE_MANIFEST.read_bytes()).hexdigest(),
    "source_dataset_sha256": source_manifest["output_sha256"],
    "added_contracts": [
        {"rank": 6, "option_type": "PUT", "strike": 485.0, "identity": "SYNTHETIC_ONLY"},
        {"rank": 6, "option_type": "CALL", "strike": 515.0, "identity": "SYNTHETIC_ONLY"},
    ],
    "added_rows": rows_written - source_manifest["rows"],
    "authority": "NON_AUTHORITATIVE_VALIDATION_ONLY",
}
OUT_MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
manifest_hash = hashlib.sha256(OUT_MANIFEST.read_bytes()).hexdigest()
OUT_MANIFEST.with_suffix(".json.sha256").write_text(f"{manifest_hash}  {OUT_MANIFEST.name}\n", encoding="ascii")
print(json.dumps({
    "dataset": str(OUT_DATA.relative_to(ROOT)),
    "rows": rows_written,
    "bytes": OUT_DATA.stat().st_size,
    "dataset_sha256": dataset_hash,
    "manifest": str(OUT_MANIFEST.relative_to(ROOT)),
    "manifest_sha256": manifest_hash,
    "authority": "VALIDATION_ONLY_SYNTHETIC_NON_AUTHORITATIVE",
}, ensure_ascii=False))