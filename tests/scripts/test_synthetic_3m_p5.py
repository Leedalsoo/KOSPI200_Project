from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import scripts.generate_synthetic_3m_p5 as p5
from scripts.generate_synthetic_3m_p5 import generate_p5
from scripts.validate_synthetic_3m_p5 import validate_dataset
from scripts.generate_authoritative_option_synthetic_3m import Calendar, calculate_synthetic_monthly_option_expiry, calculate_synthetic_weekly_option_expiry


def test_generator_refuses_existing_output_without_modifying_it(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "evidence.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(RuntimeError, match="OUTPUT_ALREADY_EXISTS"):
        generate_p5(tmp_path, output, "trend_up", 7)
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_synthetic_expiry_policy_uses_calendar_and_records_non_runtime_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master_path = tmp_path / "data" / "historical" / "krx_raw" / "20261008_options_daily.json"
    master_path.parent.mkdir(parents=True)
    master_path.write_text("{}", encoding="utf-8")
    calendar = Calendar(set())
    monkeypatch.setattr(p5, "latest_master_snapshot", lambda root: (master_path, date(2026, 10, 8)))
    monkeypatch.setattr(p5, "load_calendar", lambda root, years: calendar)
    monkeypatch.setattr(
        p5,
        "parse_master",
        lambda root, cal, path: (
            {"fixture-contract": {}},
            "a" * 64,
            "STANDARD",
            {"202611": "20261112"},
            {"202611W1": "20261105"},
        ),
    )
    monkeypatch.setattr(p5, "sha256_file", lambda path: "b" * 64)
    result = p5.validate_synthetic_expiry_inputs(tmp_path)
    assert result["policy_version"] == "synthetic-expiry-krx-calendar-v1"
    assert result["monthly_expiry_count"] > 0
    assert result["calendar_sha256"]


def test_synthetic_expiry_rules_apply_holiday_adjustments() -> None:
    monthly_holiday = Calendar({date(2026, 11, 12)})
    assert calculate_synthetic_monthly_option_expiry(2026, 11, monthly_holiday) == "20261111"
    monday_holiday = Calendar({date(2026, 10, 12)})
    assert calculate_synthetic_weekly_option_expiry(2026, 10, 2, monday_holiday, weekday=0) == "20261013"
    thursday_holiday = Calendar({date(2026, 11, 19)})
    assert calculate_synthetic_weekly_option_expiry(2026, 11, 3, thursday_holiday, weekday=3) == "20261118"


def test_validator_blocks_missing_manifest(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with pytest.raises(RuntimeError, match="MANIFEST_REQUIRED"):
        validate_dataset(tmp_path, dataset)


def test_validator_blocks_missing_synthetic_provenance(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(json.dumps({
        "synthetic": False,
        "provenance": "REAL_VTS",
        "generator_version": "wrong",
        "identity_source_status": "unknown",
        "production_runtime_eligible": True,
        "validation_only": False,
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="MANIFEST_FIELD:synthetic"):
        validate_dataset(tmp_path, dataset)
