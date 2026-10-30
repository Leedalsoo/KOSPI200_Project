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
