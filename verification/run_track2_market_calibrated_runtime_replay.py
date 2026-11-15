from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated Track2 market-calibrated validation-only Virtual Runtime replay."
    )
    parser.add_argument("--dataset", type=Path, required=True,
                        help="Accepted Runtime v2 dataset directory containing its manifest and partitions.")
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Accepted Runtime v2 manifest.json.")
    parser.add_argument("--profile", type=Path, required=True,
                        help="Validation-only Track2 synthetic scenario profile.")
    parser.add_argument("--quote-scenario-manifest", type=Path, required=True,
                        help="Manifest for the market-calibrated four-leg quote sidecar.")
    parser.add_argument("--trace-output", type=Path, required=True,
                        help="New detailed JSONL trace path; existing files are never overwritten.")
    parser.add_argument("--run-id", required=True,
                        help="Stable run ID for deterministic trace comparison.")
    args = parser.parse_args(argv)

    dataset = args.dataset.resolve()
    manifest = args.manifest.resolve()
    profile = args.profile.resolve()
    quote_manifest = args.quote_scenario_manifest.resolve()
    trace_output = args.trace_output.resolve()
    if not dataset.is_dir():
        parser.error(f"DATASET_DIRECTORY_REQUIRED:{dataset}")
    for label, path in (("MANIFEST", manifest), ("PROFILE", profile),
                        ("QUOTE_SCENARIO_MANIFEST", quote_manifest)):
        if not path.is_file():
            parser.error(f"{label}_FILE_REQUIRED:{path}")
    if manifest.parent != dataset:
        parser.error("MANIFEST_MUST_BE_LOCAL_TO_DATASET_DIRECTORY")
    if trace_output.exists():
        parser.error(f"TRACE_OUTPUT_MUST_BE_NEW:{trace_output}")
    trace_output.parent.mkdir(parents=True, exist_ok=True)

    report = HighSpeedVirtualRuntimeReplayRunner(
        dataset,
        run_id=args.run_id,
        strategy_keys=(("track2_asymmetric_trap", "1.0"),),
        validation_only_synthetic=True,
        validation_only_track2_manifest=manifest,
        validation_only_track2_risk_profile=profile,
        validation_only_track2_quote_scenario_manifest=quote_manifest,
        log_mode="detailed",
        trace_output=trace_output,
    ).run()
    if not trace_output.is_file():
        raise RuntimeError("TRACK2_RUNTIME_TRACE_NOT_CREATED")

    result = {
        "run_id": report.run_id,
        "dataset": str(dataset),
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "exhausted": report.exhausted,
        "realized_pnl": report.realized_pnl,
        "unrealized_pnl": report.unrealized_pnl,
        "net_pnl": report.net_pnl,
        "trace_status": report.trace_status,
        "trace_output": str(trace_output),
        "trace_sha256": _sha256(trace_output),
        "validation_only": True,
        "live_api_enabled": False,
        "real_vts_api_enabled": False,
        "order_submission_enabled": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())