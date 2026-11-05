from __future__ import annotations

import json
from pathlib import Path

import pytest

from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import build_synthetic_option_master
from environments.high_speed.replay_runner import HighSpeedReplayRunner


def make_dataset(root: Path, *, standard_assigned: bool = False) -> Path:
    root.mkdir(parents=True)
    manifest = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "identity_policy": {
            "mode": "SYNTHETIC_ONLY",
            "synthetic_contract_id_namespace": "SYNTHETIC_CONTRACT:",
            "production_standard_instrument_id_assigned": standard_assigned,
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    tick = {
        "timestamp": "2026-10-08T08:45:00+09:00",
        "underlying_price": 1044.5,
        "strike_price": 1030.0,
        "option_type": "CALL",
        "contract_multiplier": 250000.0,
        "bid_price": 14.55,
        "ask_price": 14.75,
        "last_price": 14.6,
        "expiry": "20261008",
        "symbol": "KOSPI200",
        "synthetic_contract_id": "SYNTHETIC_CONTRACT:0123456789abcdef01234567",
        "source_instrument_code": "B016AA12",
        "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
    }
    record = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "tick": tick,
    }
    (root / "20261008.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return root


def test_adapter_keeps_synthetic_id_separate_and_namespaced(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    record = json.loads((dataset / "20261008.jsonl").read_text(encoding="utf-8"))
    adapted = adapter.adapt_record(record)
    assert adapted["tick"]["synthetic_contract_id"].startswith("SYNTHETIC_CONTRACT:")
    assert adapted["tick"]["instrument_id"] == adapted["tick"]["synthetic_contract_id"]
    assert record["tick"].get("instrument_id") is None  # source row is not mutated


def test_adapter_rejects_standard_identity_promotion_in_manifest(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset", standard_assigned=True)
    with pytest.raises(ValueError, match="STANDARD_ID_ASSIGNMENT_FORBIDDEN"):
        SyntheticReplayAdapter(dataset)


def test_adapter_rejects_missing_or_non_namespaced_synthetic_id(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    with pytest.raises(ValueError, match="CONTRACT_ID_REQUIRED"):
        adapter.adapt_tick({"source_instrument_code": "B016AA12", "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED"})
    tick = {
        "synthetic_contract_id": "B016AA12",
        "source_instrument_code": "B016AA12",
        "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
    }
    with pytest.raises(ValueError, match="CONTRACT_ID_REQUIRED"):
        adapter.adapt_tick(tick)

def test_adapter_rejects_real_vts_provenance(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    record = json.loads((dataset / "20261008.jsonl").read_text(encoding="utf-8"))
    record["provenance"] = "REAL_VTS"
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        adapter.adapt_record(record)

def test_option_master_never_promotes_synthetic_id_to_standard_id(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    master = build_synthetic_option_master(dataset, validation_only_adapter=adapter)
    identity = master.get_contract_identity("SYNTHETIC_CONTRACT:0123456789abcdef01234567")
    assert identity is not None
    assert identity.shrn_iscd == "SYNTHETIC_CONTRACT:0123456789abcdef01234567"
    assert identity.stnd_iscd is None

def test_replay_runner_adapts_only_when_explicitly_enabled(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    tick = next(HighSpeedReplayRunner(dataset, synthetic_adapter=adapter).events())
    assert tick.instrument_id == tick.synthetic_contract_id
    assert tick.instrument_identity_status == "BLOCKED_IDENTITY_OWNER_UNRESOLVED"


def test_adapter_refuses_real_vts_manifest(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"] = "REAL_VTS"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        SyntheticReplayAdapter(dataset)


def test_adapter_refuses_conflicting_instrument_id(tmp_path: Path) -> None:
    dataset = make_dataset(tmp_path / "dataset")
    adapter = SyntheticReplayAdapter(dataset)
    tick = {
        "synthetic_contract_id": "SYNTHETIC_CONTRACT:0123456789abcdef01234567",
        "instrument_id": "B016AA12",
        "source_instrument_code": "B016AA12",
        "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
    }
    with pytest.raises(ValueError, match="PRODUCTION_ID_FIELD_FORBIDDEN"):
        adapter.adapt_tick(tick)

def test_external_manifest_validates_output_hash_bytes_and_rows(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    dataset = project / "data" / "derived_scenario" / "q25_a2_1_strategy6"
    dataset.mkdir(parents=True)
    monkeypatch.chdir(project)
    row = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "tick": {
            "timestamp": "2026-11-02T08:45:00+09:00",
            "synthetic_contract_id": "SYNTHETIC_CONTRACT:0123456789abcdef01234567",
            "source_instrument_code": "B016AA12",
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        },
    }
    data_path = dataset / "20261102.jsonl"
    data_path.write_text(json.dumps(row), encoding="utf-8")
    import hashlib

    raw = data_path.read_bytes()
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "output_path": "data\\\\derived_scenario\\\\q25_a2_1_strategy6\\\\20261102.jsonl",
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "output_bytes": len(raw),
        "rows": 1,
    }
    manifest_path = project / "Q25_A2_1_S6_SYN_EVT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SyntheticReplayAdapter(dataset, manifest_path=manifest_path)
    assert adapter.manifest["rows"] == 1

    manifest["rows"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="MANIFEST_ROWS_MISMATCH"):
        SyntheticReplayAdapter(dataset, manifest_path=manifest_path)



def test_external_manifest_accepts_dataset_scenario_ids_list(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    project = tmp_path
    dataset = project / "data" / "derived_scenario" / "q25_a2_1_strategy6"
    dataset.mkdir(parents=True)
    monkeypatch.chdir(project)
    record = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "tick": {
            "timestamp": "2026-11-02T08:45:00+09:00",
            "underlying_price": 500.0,
            "strike_price": 487.5,
            "option_type": "PUT",
            "contract_multiplier": 250000.0,
            "bid_price": 0.8,
            "ask_price": 0.9,
            "last_price": 0.85,
            "expiry": "20261102",
            "symbol": "KOSPI200",
            "synthetic_contract_id": "SYNTHETIC_CONTRACT:0123456789abcdef01234567",
            "source_instrument_code": "B016AA12",
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        },
        "scenario_metadata": {
            "scenario_id": "premium_2x_drawdown_10pct",
            "validation_only": True,
            "regime": "NORMAL",
            "contract_identity_authority": "SYNTHETIC_ONLY",
        },
    }
    data_path = dataset / "20261102.jsonl"
    data_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    raw = data_path.read_bytes()
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "scenario_count": 2,
        "scenario_ids": ["volatility_1_3x", "premium_2x_drawdown_10pct"],
        "output_path": "data\\\\derived_scenario\\\\q25_a2_1_strategy6\\\\20261102.jsonl",
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "output_bytes": len(raw),
        "rows": 1,
    }
    manifest_path = project / "Q25_A2_1_S6_SYN_EVT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SyntheticReplayAdapter(dataset, manifest_path=manifest_path)
    adapted = adapter.adapt_record(record)
    assert adapted["tick"]["scenario_id"] == "premium_2x_drawdown_10pct"
    assert adapted["scenario_metadata"]["dte_trading_days"] == 0
    assert adapted["scenario_metadata"]["dte_provenance"] == "DERIVED_EXACT_SAME_DAY_EXPIRY"

    unknown = dict(record)
    unknown["scenario_metadata"] = dict(record["scenario_metadata"], scenario_id="unknown_scenario")
    with pytest.raises(ValueError, match="SCENARIO_ID_MISMATCH"):
        adapter.adapt_record(unknown)

    future_expiry = dict(record)
    future_expiry["tick"] = dict(record["tick"], expiry="20261103")
    with pytest.raises(ValueError, match="TRADING_DAY_DTE_REQUIRED"):
        adapter.adapt_record(future_expiry)



def test_adapter_derives_future_expiry_dte_only_from_explicit_synthetic_calendar(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    project = tmp_path
    dataset = project / "data" / "derived_scenario" / "q25_a2_1_strategy6"
    dataset.mkdir(parents=True)
    monkeypatch.chdir(project)
    record = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "tick": {
            "timestamp": "2026-11-02T08:45:00+09:00",
            "underlying_price": 500.0,
            "strike_price": 487.5,
            "option_type": "PUT",
            "contract_multiplier": 250000.0,
            "bid_price": 0.8,
            "ask_price": 0.9,
            "last_price": 0.85,
            "expiry": "20261105",
            "symbol": "KOSPI200",
            "synthetic_contract_id": "SYNTHETIC_CONTRACT:0123456789abcdef01234567",
            "source_instrument_code": "B016AA12",
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        },
        "scenario_metadata": {
            "scenario_id": "premium_2x_drawdown_10pct",
            "validation_only": True,
            "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        },
    }
    data_path = dataset / "20261102.jsonl"
    data_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    raw = data_path.read_bytes()
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "scenario_id": "Q25_SYNTHETIC_MULTI_SCENARIO_CALENDAR",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "production_runtime_eligible": False,
        "runtime_eligible": False,
        "expiry_is_authoritative": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "scenario_count": 2,
        "scenario_ids": ["volatility_1_3x", "premium_2x_drawdown_10pct"],
        "scenario_regimes": {"volatility_1_3x": "HIGH_VOL", "premium_2x_drawdown_10pct": "NORMAL"},
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "trading_calendar": {
            "calendar_id": "Q25_SYNTHETIC_CALENDAR_20261102_05",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"],
        },
        "output_path": "data\\\\derived_scenario\\\\q25_a2_1_strategy6\\\\20261102.jsonl",
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "output_bytes": len(raw),
        "rows": 1,
    }
    manifest_path = project / "Q25_A2_1_S6_SYN_EVT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SyntheticReplayAdapter(dataset, manifest_path=manifest_path)
    adapted = adapter.adapt_record(record)
    assert adapted["scenario_metadata"]["dte_trading_days"] == 3
    assert adapted["scenario_metadata"]["dte_provenance"] == "DERIVED_SYNTHETIC_VALIDATION_CALENDAR"
    assert adapted["scenario_metadata"]["regime"] == "NORMAL"
    assert adapted["scenario_metadata"]["regime_provenance"] == "DERIVED_FROM_MANIFEST_SCENARIO_REGIME"
    assert adapted["scenario_metadata"]["contract_identity_authority"] == "SYNTHETIC_ONLY"
    assert adapted["scenario_metadata"]["identity_authority_provenance"] == "DERIVED_FROM_BLOCKED_IDENTITY_STATUS"
