from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot
from environments.high_speed.validation_only_s15b_option_adapter import S15BOptionValidationAdapter

ROOT = Path(__file__).resolve().parents[2]
QUOTE_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"
ORDERBOOK_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_orderbook_supplement/manifest.json"


def test_s15b_synthetic_orderbook_positive_and_negative_scenarios():
    adapter = S15BOptionValidationAdapter(QUOTE_MANIFEST, order_book_manifest_path=ORDERBOOK_MANIFEST)
    for symbol in ("B01611885", "B01611887"):
        valid = adapter.order_book(symbol, "fresh_two_sided")
        assert valid is not None
        assert len(valid.ask_levels) == len(valid.bid_levels) == 5
        assert adapter.is_complete_order_book_snapshot(valid)

        stale = adapter.order_book(symbol, "stale_two_sided")
        assert stale is not None and adapter.is_complete_order_book_snapshot(stale)

        assert not adapter.is_complete_order_book_snapshot(adapter.order_book(symbol, "one_sided_book"))
        assert not adapter.is_complete_order_book_snapshot(adapter.order_book(symbol, "zero_quantity"))
        assert not adapter.is_complete_order_book_snapshot(adapter.order_book(symbol, "crossed_book"))
        assert not adapter.is_complete_order_book_snapshot(adapter.order_book(symbol, "insufficient_depth"))
        assert not adapter.is_complete_order_book_snapshot(adapter.order_book(symbol, "nonfinite_price"))

    assert adapter.order_book("C01611880", "fresh_two_sided") is None
    assert adapter.order_book("C01611882", "fresh_two_sided") is None
    assert adapter.order_book("B01611880", "fresh_two_sided") is None


def test_s15b_orderbook_positive_case_has_monotonic_ladders_and_spread():
    adapter = S15BOptionValidationAdapter(QUOTE_MANIFEST, order_book_manifest_path=ORDERBOOK_MANIFEST)
    snapshot = adapter.order_book("B01611885", "fresh_two_sided")
    assert snapshot is not None
    asks = [level.price for level in snapshot.ask_levels]
    bids = [level.price for level in snapshot.bid_levels]
    assert asks == sorted(asks)
    assert bids == sorted(bids, reverse=True)
    assert bids[0] < asks[0]
    assert all(level.quantity > 0 for level in (*snapshot.ask_levels, *snapshot.bid_levels))


def test_s15b_orderbook_manifest_rejects_production_eligibility_and_wrong_quote_binding(tmp_path):
    import json
    import pytest

    original = json.loads(ORDERBOOK_MANIFEST.read_text(encoding="utf-8"))
    enabled = dict(original)
    enabled["production_runtime_eligible"] = True
    enabled_path = tmp_path / "enabled.json"
    enabled_path.write_text(json.dumps(enabled), encoding="utf-8")
    with pytest.raises(ValueError, match="S15B_ORDERBOOK_SAFETY_FLAG_NOT_FALSE"):
        S15BOptionValidationAdapter(QUOTE_MANIFEST, order_book_manifest_path=enabled_path)

    wrong_binding = dict(original)
    wrong_binding["source_quote_dataset_sha256"] = "0" * 64
    wrong_path = tmp_path / "wrong_binding.json"
    wrong_path.write_text(json.dumps(wrong_binding), encoding="utf-8")
    with pytest.raises(ValueError, match="S15B_ORDERBOOK_QUOTE_DATASET_HASH_MISMATCH"):
        S15BOptionValidationAdapter(QUOTE_MANIFEST, order_book_manifest_path=wrong_path)
