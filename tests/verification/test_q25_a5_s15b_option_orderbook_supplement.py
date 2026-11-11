from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
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


def test_s15b_orderbook_flows_into_virtual_runtime_data_provider():
    adapter = S15BOptionValidationAdapter(QUOTE_MANIFEST, order_book_manifest_path=ORDERBOOK_MANIFEST)
    market = SimpleNamespace(
        recent_ticks=[SimpleNamespace(last_price=Decimal("43.15"))],
        underlying_history=[],
        scenario=SimpleNamespace(
            active_config=lambda: {"base_volatility": 1.0, "shock_interval_days": 999999}
        ),
    )
    tick = SimpleNamespace(
        timestamp="2026-11-09T15:45:00+09:00",
        last_price=Decimal("43.15"),
        strike_price=Decimal("885.00"),
        seq_id=1,
        symbol="B01611885",
        underlying_symbol="KOSPI200",
        underlying_price=Decimal("900.00"),
        expiry="2026-11-12",
        option_type="CALL",
        validation_only=True,
        dte_trading_days=3,
        delta=None,
        gamma=None,
    )

    runtime_data = VirtualRuntimeDataProvider(
        market, option_orderbook_source=adapter
    ).snapshot(tick)

    assert runtime_data.status["option_orderbook"].available is True
    assert runtime_data.status["option_orderbook"].fresh is True
    assert runtime_data.status["option_orderbook"].source == "SYNTHETIC:DERIVED_SCENARIO:fresh_two_sided"
    assert len(runtime_data.option_bid_qtys) == 5
    assert len(runtime_data.option_ask_qtys) == 5


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
