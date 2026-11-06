"""Hash and gzip S6 detailed traces, then bind their archive evidence into result manifests."""
import gzip
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE_FILES = [
    Path("reports/synth/Q25_A4_S6_RANK6_R5_per_order_DETAILED_v2.trace.jsonl"),
    Path("reports/synth/Q25_A4_S6_RANK6_R5_shared_elapsed_DETAILED_v2.trace.jsonl"),
    Path("reports/synth/Q25_A4_S6_RANK6_R6_per_order_DETAILED_v2.trace.jsonl"),
    Path("reports/synth/Q25_A4_S6_RANK6_R6_shared_elapsed_DETAILED_v2.trace.jsonl"),
    Path("reports/synth/Q25_A4_S6_SEQUENTIAL_EXIT_DETAILED_20261106.trace.jsonl"),
]
OUT_DIR = ROOT / "reports/synth/q25_a4_s6_trace_archive_v2"
MANIFEST = ROOT / "reports/synth/Q25_A4_S6_TRACE_ARCHIVE_MANIFEST_20261106.json"
if OUT_DIR.exists() or MANIFEST.exists() or MANIFEST.with_suffix(".json.sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_S6_TRACE_ARCHIVE")
for path in TRACE_FILES:
    if not (ROOT / path).is_file():
        raise SystemExit(f"S6_TRACE_MISSING:{path}")

OUT_DIR.mkdir(parents=True, exist_ok=False)
artifacts = []
for relative in TRACE_FILES:
    source = ROOT / relative
    compressed_relative = Path("reports/synth/q25_a4_s6_trace_archive_v2") / f"{source.name}.gz"
    target = ROOT / compressed_relative
    raw_hash = hashlib.sha256()
    compressed_hash = hashlib.sha256()
    with source.open("rb") as src, target.open("xb") as raw_target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_target, compresslevel=6, mtime=0) as gz:
            while chunk := src.read(1024 * 1024):
                raw_hash.update(chunk)
                gz.write(chunk)
        raw_target.flush()
    with target.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            compressed_hash.update(chunk)
    artifacts.append({
        "raw_path": relative.as_posix(),
        "raw_bytes": source.stat().st_size,
        "raw_sha256": raw_hash.hexdigest(),
        "compressed_path": compressed_relative.as_posix(),
        "compressed_bytes": target.stat().st_size,
        "compressed_sha256": compressed_hash.hexdigest(),
        "compression": "gzip-level-6-mtime-0",
    })
    print(json.dumps(artifacts[-1], ensure_ascii=False), flush=True)

payload = {
    "schema_version": 1,
    "authority": "VALIDATION_ONLY_SYNTHETIC_NON_AUTHORITATIVE",
    "purpose": "Q25_A4_S6_DETAILED_TRACE_EVIDENCE",
    "artifacts": artifacts,
}
MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
MANIFEST.with_suffix(".json.sha256").write_text(f"{manifest_hash}  {MANIFEST.name}\n", encoding="ascii")

for report_relative in (
    Path("reports/synth/Q25_A4_S6_RUNTIME_MATRIX_RANK6_20261106_v2.json"),
    Path("reports/synth/Q25_A4_S6_SEQUENTIAL_EXIT_E2E_20261106.json"),
):
    report_path = ROOT / report_relative
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["detailed_trace_archive_manifest"] = MANIFEST.relative_to(ROOT).as_posix()
    report["detailed_trace_archive_manifest_sha256"] = manifest_hash
    report["detailed_trace_artifacts"] = artifacts
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    report_path.with_suffix(report_path.suffix + ".sha256").write_text(
        f"{report_hash}  {report_path.name}\n", encoding="ascii"
    )
    print(json.dumps({"report": report_relative.as_posix(), "sha256": report_hash}, ensure_ascii=False), flush=True)
print(json.dumps({"manifest": MANIFEST.relative_to(ROOT).as_posix(), "sha256": manifest_hash}, ensure_ascii=False), flush=True)
