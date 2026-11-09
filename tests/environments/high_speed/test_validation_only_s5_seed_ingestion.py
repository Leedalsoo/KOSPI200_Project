from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.strategy.track5_gap_divergence import Track5GapDivergence
from environments.high_speed.validation_only_s5_seed_ingestion import (
    S5SeedInputBlocked,
    S5ValidatedSeed,
    S5ValidationOnlySeedAdapter,
)
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore


def _write_seed(tmp_path, *, safety=True):
    dataset = tmp_path / "events.jsonl"
    event = {
        "schema": "q25-a5-validation-only-position-seed-v1",
        "event_type": "SYNTHETIC_PREEXISTING_POSITION_SEED",
        "event_id": "S5-S23-SEED-EXEC-000001",
        "provenance": "SYNTHETIC:DERIVED_SCENARIO",
        "validation_only": True,
        "production_runtime_eligible": False,
        "run_id": "Q25-A5-S23-S5-VALIDATION-SEED-20261109",
        "strategy_id": "track5_gap_divergence",
        "group_id": "S5-S23-SYNTHETIC-OPEN-OPTION-ONLY",
        "leg_id": "S5_SYNTHETIC_PREEXISTING_CALL_000001",
        "client_order_id": "S5-S23-SEED-ORDER-000001",
        "execution_id": "S5-S23-SEED-EXEC-000001",
        "instrument_id": "B01611887",
        "side": "BUY",
        "opened_quantity": 1,
        "remaining_quantity": 1,
        "execution_price": None,
        "timestamp": "2026-11-09T09:00:00+09:00",
        "instrument_identity": {
            "instrument_id": "B01611887",
            "expiry": "20261112",
            "option_type": "CALL",
            "strike": "887.50",
            "contract_multiplier": "250000",
            "identity_source": "KIS_OFFICIAL_MASTER|KRX_VALIDATION_ONLY",
        },
    }
    dataset.write_text(json.dumps(event) + "\n", encoding="utf-8")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    manifest = {
        "schema": "q25-a5-validation-only-position-seed-manifest-v1",
        "provenance": "SYNTHETIC:DERIVED_SCENARIO",
        "validation_only": True,
        "production_runtime_eligible": False,
        "execution_enabled": False,
        "orders_allowed": False,
        "kis_api_allowed": False,
        "real_vts_api_allowed": False,
        "live_api_allowed": False,
        "account_api_allowed": False,
        "strategy_id": event["strategy_id"],
        "run_id": event["run_id"],
        "group_id": event["group_id"],
        "instrument_id": event["instrument_id"],
        "event_count": 1,
        "events_file": "events.jsonl",
        "events_sha256": digest,
    }
    if not safety:
        manifest["orders_allowed"] = True
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, dataset


def test_current_shape_fails_closed_without_promoting_seed(tmp_path):
    manifest, dataset = _write_seed(tmp_path)
    adapter = S5ValidationOnlySeedAdapter(
        manifest_path=manifest,
        dataset_path=dataset,
    )

    with pytest.raises(S5SeedInputBlocked) as exc:
        adapter.validate()

    reasons = set(exc.value.reasons)
    assert "EVENT_SCHEMA_INVALID" in reasons
    assert "EXACT_EXPIRY_REQUIRED" in reasons
    assert "EXECUTION_PRICE_REQUIRED_OR_INVALID" in reasons
    assert "FEE_REQUIRED_OR_INVALID" in reasons
    assert "TRACK5_STATE_SNAPSHOT_INCOMPLETE" in reasons
    assert "KIS_EXACT_EXPIRY_AUTHORITY_REQUIRED" in reasons


def test_manifest_cannot_enable_order_or_live_access(tmp_path):
    manifest, dataset = _write_seed(tmp_path, safety=False)
    adapter = S5ValidationOnlySeedAdapter(
        manifest_path=manifest,
        dataset_path=dataset,
    )

    with pytest.raises(S5SeedInputBlocked) as exc:
        adapter.validate()

    assert "SAFETY_FLAG_INVALID_ORDERS_ALLOWED" in exc.value.reasons


def test_validated_seed_restores_only_existing_lot_and_active_state():
    timestamp = "2026-11-09T09:00:00+09:00"
    identity_source = "KIS_OFFICIAL_TEST_FIXTURE_ONLY"
    identity = OptionInstrumentIdentity(
        instrument_id="B01611887",
        symbol="B01611887",
        expiry="20261112",
        option_type="CALL",
        strike=Decimal("887.50"),
        contract_multiplier=Decimal("250000"),
        identity_source=identity_source,
    )
    state = {
        "is_active": True,
        "entry_pending": False,
        "direction": "SHORT",
        "entry_price": "10",
        "target_price": "9",
        "stop_loss_price": "12",
        "open_ticks": 1,
        "peak_pnl": "0",
        "trailing_active": False,
        "expected_move_pts": "2",
        "session_start_price": None,
        "session_start_at": None,
        "gap_source": "TEST_FIXTURE",
        "gap_extreme_price": "10",
        "option_type": "CALL",
        "selected_strike": "887.50",
        "futures_side": None,
        "futures_close_requested": False,
        "futures_closed": True,
        "futures_close_error": None,
        "option_close_requested": False,
    }
    event = {
        "run_id": "S5-TEST-RUN",
        "strategy_id": "track5_gap_divergence",
        "group_id": "S5-TEST-GROUP",
        "leg_id": "S5-TEST-LEG",
        "client_order_id": "S5-TEST-ORDER",
        "execution_id": "S5-TEST-EXEC",
        "instrument_id": "B01611887",
        "symbol": "B01611887",
        "side": "BUY",
        "opened_quantity": 1,
        "remaining_quantity": 1,
        "execution_price": "10",
        "fee": "0",
        "execution_timestamp": timestamp,
        "expiry": "20261112",
        "expiry_source_type": "KIS_OFFICIAL_CONTRACT_METADATA",
        "multiplier_source_type": "KIS_OFFICIAL_CONTRACT_METADATA",
        "contract_identity_source": identity_source,
        "option_type": "CALL",
        "strike": "887.50",
        "contract_multiplier": "250000",
        "track5_state_snapshot": state,
        "execution_fills": [{
            "execution_id": "S5-TEST-EXEC",
            "filled_quantity": 1,
            "execution_price": "10",
            "execution_timestamp": timestamp,
            "fee": "0",
        }],
    }
    seed = S5ValidatedSeed({}, event, "fixture-manifest-hash", "fixture-dataset-hash")
    strategy = Track5GapDivergence()
    lots = VirtualPositionLotStore()

    report = seed.restore_existing_position(
        strategy=strategy,
        position_lot_store=lots,
        identity=identity,
    )

    assert report.status == "FILLED"
    assert report.fee == Decimal("0")
    assert report.source_freshness.is_fresh is False
    assert len(lots.open_lots()) == 1
    assert lots.open_lots()[0].remaining_quantity == 1
    assert strategy.state.is_active is True
    assert strategy.CURRENT_EXECUTION_POLICY_APPROVED is False
    assert strategy.runtime_config_verified is False
    assert strategy.risk_limits_available is False
