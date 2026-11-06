"""Build a fresh validation-only manifest extension with explicit synthetic regimes and calendar."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reports/synth/Q25_A2_1_S6_SYN_EVT_MANIFEST_20261102.json"
TARGET = ROOT / "reports/synth/Q25_A4_S6_SYN_EVT_MANIFEST_20261106_v3.json"
if TARGET.exists() or TARGET.with_suffix(TARGET.suffix + ".sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_A4_MANIFEST_V3")
manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
dataset = (ROOT / manifest["output_path"].replace("\\", "/")).resolve()
if not dataset.is_file():
    raise SystemExit("SOURCE_DERIVED_SCENARIO_MISSING")
digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
if digest != manifest["output_sha256"] or dataset.stat().st_size != manifest["output_bytes"]:
    raise SystemExit("SOURCE_DERIVED_SCENARIO_HASH_OR_SIZE_MISMATCH")
first = date.fromisoformat(manifest["first_timestamp"][:10])
expiry = date(2026, 11, 5)
days = []
cursor = first
while cursor <= expiry:
    if cursor.weekday() < 5:
        days.append(cursor.isoformat())
    cursor += timedelta(days=1)
if not days or days[0] != first.isoformat() or days[-1] != expiry.isoformat():
    raise SystemExit("VALIDATION_CALENDAR_RANGE_INVALID")

scenario_ids = manifest["scenario_ids"]
regimes = {
    scenario_id: ("HIGH_VOL" if scenario_id in {
        "volatility_1_3x", "premium_2x_drawdown_10pct"
    } else "NORMAL")
    for scenario_id in scenario_ids
}
manifest.update({
    "runtime_eligible": False,
    "expiry_is_authoritative": False,
    "dataset_sha256": digest,
    "scenario_id": "q25_a4_s6_runtime_matrix",
    "scenario_regimes": regimes,
})
manifest["trading_calendar"] = {
    "calendar_id": "SYNTHETIC-Q25-A4-S6-WEEKDAYS",
    "source_type": "SYNTHETIC",
    "authoritative": False,
    "timezone": "Asia/Seoul",
    "trading_days": days,
    "derivation": "WEEKDAYS_ONLY_VALIDATION_ASSUMPTION_NOT_KRX_HOLIDAY_CALENDAR",
}
manifest["a4_validation_extension"] = {
    "purpose": "Q25_A4_S6_RUNTIME_MATRIX",
    "source_manifest": SOURCE.name,
    "source_manifest_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "dataset_sha256_verified": digest,
    "scenario_regimes": "DERIVED_FROM_SYNTHETIC_SCENARIO_INVARIANT_LABELS_ONLY",
    "calendar_authority": "NON_AUTHORITATIVE_VALIDATION_ONLY",
}
TARGET.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
target_hash = hashlib.sha256(TARGET.read_bytes()).hexdigest()
TARGET.with_suffix(TARGET.suffix + ".sha256").write_text(
    f"{target_hash}  {TARGET.name}\n", encoding="ascii",
)
print(json.dumps({
    "manifest": str(TARGET.relative_to(ROOT)),
    "sha256": target_hash,
    "scenario_regimes": regimes,
    "trading_days": days,
    "dataset_sha256": digest,
    "authority": "NON_AUTHORITATIVE_VALIDATION_ONLY",
}, ensure_ascii=False))
