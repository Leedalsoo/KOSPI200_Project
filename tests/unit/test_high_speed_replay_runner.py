from __future__ import annotations
import json
from pathlib import Path

import pytest

from environments.high_speed.replay_runner import HighSpeedReplayRunner

def write_dataset(root: Path) -> None:
    root.mkdir()
    manifest = {
        "dataset": "test",
        "provenance": "SYNTHETIC",
        "schema": "reference-canonical-market-tick-v1",
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for day, seq in (("2025-01-02", 1), ("2025-01-03", 2)):
        record = {
            "schema": "reference-canonical-market-tick-v1",
            "source": "synthetic:test",
            "provenance": "SYNTHETIC",
            "tick": {
                "timestamp": f"{day}T09:00:00",
                "seq_id": seq,
                "underlying_price": 1100.0 + seq,
                "underlying_symbol": "KOSPI200_SYNTHETIC",
                "strike_price": 1100.0,
                "option_type": "CALL",
                "contract_multiplier": 250000.0,
                "bid_price": 10.0,
                "ask_price": 10.2,
                "last_price": 10.1,
                "volume": 100,
                "expiry": "202501",
                "symbol": "KOSPI200_SYNTHETIC",
                "option_source": "synthetic:test",
                "instrument_id": f"SYN-{seq}",
            },
        }
        (root / f"{day}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

def test_runner_filters_period_and_runs_fast(tmp_path: Path):
    root = tmp_path / "dataset"
    write_dataset(root)
    seen = []
    report = HighSpeedReplayRunner(root).run(
        start="2025-01-03",
        end="2025-01-03",
        speed=float("inf"),
        on_event=seen.append,
    )
    assert report.events == 1
    assert report.first_timestamp == "2025-01-03T09:00:00"
    assert report.last_timestamp == report.first_timestamp
    assert report.exhausted is True
    assert len(seen) == 1
    assert report.events_per_second > 0

def test_runner_rejects_non_synthetic_provenance(tmp_path: Path):
    root = tmp_path / "dataset"
    write_dataset(root)
    path = root / "2025-01-02.jsonl"
    text = path.read_text(encoding="utf-8").replace("SYNTHETIC", "ORIGINAL")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="SYNTHETIC_DATASET_PROVENANCE_REQUIRED"):
        list(HighSpeedReplayRunner(root).events())

def test_runner_rejects_non_positive_speed(tmp_path: Path):
    root = tmp_path / "dataset"
    write_dataset(root)
    with pytest.raises(ValueError, match="REPLAY_SPEED_MUST_BE_POSITIVE"):
        HighSpeedReplayRunner(root).run(speed=0)
