from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from decimal import Decimal

from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources

KST = timezone(timedelta(hours=9))


def tick(instrument_id, bid, ask, last, seq_id):
    return SimpleNamespace(
        instrument_id=instrument_id,
        timestamp=datetime(2026, 11, 2, 10, 0, tzinfo=KST).isoformat(),
        underlying_price=Decimal("500"),
        last_price=Decimal(str(last)),
        bid_price=Decimal(str(bid)),
        ask_price=Decimal(str(ask)),
        volume=100,
        seq_id=seq_id,
        expiry="20261105",
        strike_price=Decimal("487.5"),
        option_type="PUT",
    )


def test_synthetic_orderbook_is_bound_to_exact_contract_identity():
    source = SyntheticRuntimeSources()
    first = "SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5"
    second = "SYNTHETIC_CONTRACT:SYNTH-S6-2-20261102-PUT-487.5"
    source.set_tick(tick(first, "0.8", "0.9", "0.85", 1))
    source.set_tick(tick(second, "0.5", "0.6", "0.55", 2))

    first_book = source.get_order_book(first)
    second_book = source.get_order_book(second)
    assert first_book is not None and second_book is not None
    assert first_book.bid_levels[0].price == Decimal("0.8")
    assert first_book.ask_levels[0].price == Decimal("0.9")
    assert second_book.bid_levels[0].price == Decimal("0.5")
    assert second_book.ask_levels[0].price == Decimal("0.6")


def test_synthetic_orderbook_does_not_fall_back_when_identity_quote_is_missing():
    source = SyntheticRuntimeSources()
    source.set_tick(tick("SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5", "0.8", "0.9", "0.85", 1))
    assert source.get_order_book("SYNTHETIC_CONTRACT:SYNTH-S6-9-20261102-PUT-487.5") is None
