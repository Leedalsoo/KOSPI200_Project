from __future__ import annotations

from pathlib import Path

import pytest

from contracts.market_data_freshness import FreshnessStatus
from environments.high_speed.validation_only_s15b_option_adapter import (
    S15BOptionValidationAdapter,
    S15BValidationAdapterError,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"


def test_s15b_maps_only_kis_shrn_iscd_to_validation_identity():
    adapter = S15BOptionValidationAdapter(MANIFEST)
    identity = adapter.identity("B01611885", "fresh_two_sided")
    assert identity is not None
    assert identity.instrument_id == "B01611885"
    assert identity.symbol == "B01611885"
    assert identity.identity_source.startswith("KIS_OPTION_MASTER:shrn_iscd:VALIDATION_ONLY:")
    assert identity.contract_multiplier is None


def test_s15b_quote_adapter_preserves_provenance_and_freshness_scenarios():
    adapter = S15BOptionValidationAdapter(MANIFEST)
    quote = adapter.quote("B01611885", "fresh_two_sided")
    assert quote is not None and quote.bid is not None and quote.ask is not None
    assert quote.ask > quote.bid
    assert quote.provenance == "SYNTHETIC:DERIVED_SCENARIO"
    assert adapter.freshness("B01611885", "fresh_two_sided").status is FreshnessStatus.FRESH
    assert adapter.freshness("B01611885", "stale_two_sided").status is FreshnessStatus.STALE
    assert adapter.freshness("B01611885", "missing_source_time").status is FreshnessStatus.UNKNOWN
    assert adapter.freshness("B01611885", "future_source_time").status is FreshnessStatus.UNKNOWN
    assert adapter.freshness("B01611885", "identity_conflict").status is FreshnessStatus.IDENTITY_CONFLICT


def test_missing_quote_anchor_stays_unavailable_and_orderbook_depth_is_not_fabricated():
    adapter = S15BOptionValidationAdapter(MANIFEST)
    assert adapter.identity("C01611880") is None
    assert adapter.quote("C01611880") is None
    assert adapter.order_book("B01611885", "fresh_two_sided") is None
    assert adapter.order_book("C01611880") is None


def test_adapter_rejects_manifest_that_enables_orders(tmp_path):
    import json

    original = json.loads(MANIFEST.read_text(encoding="utf-8"))
    original["orders_allowed"] = True
    altered = tmp_path / "manifest.json"
    altered.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(S15BValidationAdapterError, match="S15B_SAFETY_FLAG_NOT_FALSE"):
        S15BOptionValidationAdapter(altered, project_root=ROOT)


def test_adapter_rejects_wrong_master_hash_binding(tmp_path):
    import json

    original = json.loads(MANIFEST.read_text(encoding="utf-8"))
    original["target_kis_master_sha256"] = "0" * 64
    altered = tmp_path / "manifest.json"
    altered.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(S15BValidationAdapterError, match="S15B_ROW_MASTER_HASH_MISMATCH"):
        S15BOptionValidationAdapter(altered, project_root=ROOT)
