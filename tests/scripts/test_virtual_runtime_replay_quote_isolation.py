from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from environments.high_speed.virtual_runtime_replay import (
    _publish_contract_scoped_replay_quote,
)


@dataclass(frozen=True)
class FakeIdentity:
    shrn_iscd: str
    stnd_iscd: str | None
    expiry: str
    option_type: str
    strike: float
    contract_multiplier: float


class FakeOptionMaster:
    def __init__(self, identities):
        self.identities = {item.shrn_iscd: item for item in identities}

    def get_contract_identity(self, instrument_id):
        return self.identities.get(instrument_id)


class FakeMarket:
    def __init__(self):
        self.quotes = {}

    def register_replay_option_quote(self, **kwargs):
        key = (kwargs["option_type"], kwargs["strike"], kwargs["expiry"])
        self.quotes[key] = dict(kwargs)


class FakeOrderBook:
    def __init__(self):
        self.quotes = {}

    def update_bid_ask(self, bid, ask, *, instrument_id):
        self.quotes[instrument_id] = (bid, ask)


def make_pair():
    first_id = "SYNTHETIC_CONTRACT:first"
    second_id = "SYNTHETIC_CONTRACT:second"
    identities = [
        FakeIdentity(first_id, None, "20261008", "CALL", 1030.0, 250000.0),
        FakeIdentity(second_id, None, "20261008", "PUT", 1045.0, 250000.0),
    ]
    ticks = [
        SimpleNamespace(
            synthetic_contract_id=first_id, instrument_id=first_id,
            expiry="20261008", option_type="CALL", strike_price=1030.0,
            bid_price=14.55, ask_price=14.75, last_price=14.60,
            timestamp="2026-10-08T08:45:00+09:00", contract_multiplier=250000.0,
        ),
        SimpleNamespace(
            synthetic_contract_id=second_id, instrument_id=second_id,
            expiry="20261008", option_type="PUT", strike_price=1045.0,
            bid_price=2.10, ask_price=2.30, last_price=2.20,
            timestamp="2026-10-08T08:45:00+09:00", contract_multiplier=250000.0,
        ),
    ]
    return identities, ticks


def publish_all(order):
    identities, ticks = make_pair()
    master, market, book = FakeOptionMaster(identities), FakeMarket(), FakeOrderBook()
    for index in order:
        _publish_contract_scoped_replay_quote(
            ticks[index], option_master=master, market=market, order_book=book
        )
    return market.quotes, book.quotes


def test_same_timestamp_option_ticks_keep_each_contract_quote():
    quotes, book = publish_all([0, 1])

    assert quotes[("CALL", 1030.0, "20261008")]["bid"] == 14.55
    assert quotes[("CALL", 1030.0, "20261008")]["ask"] == 14.75
    assert quotes[("CALL", 1030.0, "20261008")]["last"] == 14.60
    assert quotes[("PUT", 1045.0, "20261008")]["bid"] == 2.10
    assert quotes[("PUT", 1045.0, "20261008")]["ask"] == 2.30
    assert quotes[("PUT", 1045.0, "20261008")]["last"] == 2.20
    assert set(book) == {"SYNTHETIC_CONTRACT:first", "SYNTHETIC_CONTRACT:second"}


def test_quote_result_is_independent_of_input_row_order():
    forward_quotes, forward_book = publish_all([0, 1])
    reverse_quotes, reverse_book = publish_all([1, 0])

    assert forward_quotes == reverse_quotes
    assert forward_book == reverse_book


def test_one_contract_premium_does_not_rewrite_other_contract_quote():
    identities, ticks = make_pair()
    master, market, book = FakeOptionMaster(identities), FakeMarket(), FakeOrderBook()
    _publish_contract_scoped_replay_quote(
        ticks[0], option_master=master, market=market, order_book=book
    )
    _publish_contract_scoped_replay_quote(
        ticks[1], option_master=master, market=market, order_book=book
    )
    put_before = dict(market.quotes[("PUT", 1045.0, "20261008")])

    changed_call = SimpleNamespace(**{
        **vars(ticks[0]), "bid_price": 100.0, "ask_price": 101.0, "last_price": 100.5,
    })
    _publish_contract_scoped_replay_quote(
        changed_call, option_master=master, market=market, order_book=book
    )

    assert market.quotes[("PUT", 1045.0, "20261008")] == put_before


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"ask_price": 14.50}, "BID_ASK_INVALID"),
        ({"expiry": "202610"}, "EXACT_EXPIRY_REQUIRED"),
        ({"instrument_id": "B016AA12"}, "INSTRUMENT_ID_MISMATCH"),
        ({"strike_price": 1032.5}, "STRIKE_IDENTITY_MISMATCH"),
    ],
)
def test_invalid_or_mismatched_contract_quote_fails_closed(updates, error):
    identities, ticks = make_pair()
    tick = SimpleNamespace(**{**vars(ticks[0]), **updates})
    market, book = FakeMarket(), FakeOrderBook()

    with pytest.raises(ValueError, match=error):
        _publish_contract_scoped_replay_quote(
            tick, option_master=FakeOptionMaster(identities),
            market=market, order_book=book,
        )

    assert market.quotes == {}
    assert book.quotes == {}


def test_synthetic_identity_must_not_be_promoted_to_standard_id():
    identities, ticks = make_pair()
    identities[0] = FakeIdentity(
        identities[0].shrn_iscd, "REAL_STANDARD_ID", "20261008",
        "CALL", 1030.0, 250000.0,
    )
    with pytest.raises(ValueError, match="STANDARD_ID_PROMOTION_FORBIDDEN"):
        _publish_contract_scoped_replay_quote(
            ticks[0], option_master=FakeOptionMaster(identities),
            market=FakeMarket(), order_book=FakeOrderBook(),
        )
