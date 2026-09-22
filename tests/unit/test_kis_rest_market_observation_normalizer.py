from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.kis_rest_market_observation_normalizer import (
    KISRestMarketObservationNormalizer,
)


PRICE = {
    "rt_cd": "0", "msg_cd": "MCA00000",
    "output1": {
        "futs_shrn_iscd": "B01610C41", "futs_prpr": "0.08", "acml_vol": "1232",
        "delta_val": "0.0185", "gama": "0.0002", "theta": "-0.2423", "vega": "0.1072",
        "hts_ints_vltl": "57.1599", "acpr": "1595.00",
    },
    "output3": {
        "bstp_cls_code": "2001", "hts_kor_isnm": "KOSPI200",
        "bstp_nmix_prpr": "1130.63",
    },
}

ASK = {
    "rt_cd": "0", "msg_cd": "MCA00000",
    "output1": {"futs_shrn_iscd": "B01610C41"},
    "output2": {
        "aspr_acpt_hour": "122603", "futs_askp1": "0.09", "askp_rsqn1": "744",
        "futs_bidp1": "0.08", "bidp_rsqn1": "2740", "total_askp_rsqn": "744",
        "total_bidp_rsqn": "2740",
    },
}


class IdentityLookup:
    def get_contract_identity(self, symbol: str):
        if symbol == "B01610C41":
            return OptionInstrumentIdentity(
                instrument_id=symbol,
                symbol=symbol,
                expiry="202610",
                option_type="CALL",
                strike=Decimal("1595.0"),
                contract_multiplier=Decimal("250000"),
                identity_source="kis_vts_rest",
            )
        return None


def test_normalizer_preserves_quote_orderbook_identity_and_analytics():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    collected_at = datetime(2026, 9, 21, 12, 26, 3, 450000, tzinfo=timezone.utc)

    observation = normalizer.normalize(
        price_response=PRICE,
        asking_price_response=ASK,
        collected_at=collected_at,
        run_id="run-1",
    )

    assert observation.contract.symbol == "B01610C41"
    assert observation.contract.strike == Decimal("1595.0")
    assert observation.quote.last == Decimal("0.08")
    assert observation.quote.bid == Decimal("0.08")
    assert observation.quote.ask == Decimal("0.09")
    assert observation.quote.volume == Decimal("1232")
    assert observation.order_book.asks[0].quantity == Decimal("744")
    assert observation.order_book.bids[0].quantity == Decimal("2740")
    assert observation.analytics.implied_volatility == Decimal("57.1599")
    assert observation.analytics.delta == Decimal("0.0185")
    assert observation.underlying_price == Decimal("1130.63")
    assert observation.underlying_symbol == "KOSPI200"
    assert observation.underlying_observed_hour == "122603"
    assert observation.underlying_source == "kis_vts_rest:price.output3"
    assert observation.provenance.tr_ids == (
        "FHMIF10000000",
        "FHMIF10010000",
    )
    assert observation.collected_at == collected_at


def test_normalizer_does_not_invent_observed_at_when_rest_has_no_timestamp():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    observation = normalizer.normalize(
        price_response=PRICE,
        asking_price_response=ASK,
        collected_at=datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc),
        run_id="run-1",
    )

    assert observation.observed_at is None
    assert "122603" in observation.provenance.source_timestamps


def test_normalizer_fails_closed_without_authoritative_underlying():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    price = {**PRICE, "output3": {"bstp_cls_code": "2001", "hts_kor_isnm": "KOSPI200"}}

    with pytest.raises(ValueError, match="AUTHORITATIVE_KOSPI200_UNDERLYING_REQUIRED"):
        normalizer.normalize(
            price_response=price,
            asking_price_response=ASK,
            collected_at=datetime.now(timezone.utc),
            run_id="run-1",
        )


def test_normalizer_fails_closed_for_unknown_contract():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    price = {**PRICE, "output1": {**PRICE["output1"], "futs_shrn_iscd": "UNKNOWN"}}

    with pytest.raises(ValueError, match="AUTHORITATIVE_OPTION_IDENTITY_REQUIRED"):
        normalizer.normalize(
            price_response=price,
            asking_price_response=ASK,
            collected_at=datetime.now(timezone.utc),
            run_id="run-1",
        )


def test_normalizer_does_not_zero_fill_missing_book_levels():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    ask = {"rt_cd": "0", "msg_cd": "MCA00000", "output": {"futs_shrn_iscd": "B01610C41"}}

    observation = normalizer.normalize(
        price_response=PRICE,
        asking_price_response=ask,
        collected_at=datetime.now(timezone.utc),
        run_id="run-1",
    )

    assert observation.order_book.asks == ()
    assert observation.order_book.bids == ()
    assert observation.order_book.total_ask_quantity is None
    assert observation.order_book.total_bid_quantity is None


def test_normalizer_rejects_non_success_kis_response():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    failed = {**PRICE, "rt_cd": "1", "msg_cd": "ERROR", "output1": {}}

    with pytest.raises(ValueError, match="KIS_REST_RESPONSE_NOT_SUCCESS"):
        normalizer.normalize(
            price_response=failed,
            asking_price_response=ASK,
            collected_at=datetime.now(timezone.utc),
            run_id="run-1",
        )


def test_normalizer_rejects_conflicting_source_timestamps():
    normalizer = KISRestMarketObservationNormalizer(IdentityLookup())
    ask = {**ASK, "output2": {**ASK["output2"], "aspr_acpt_hour": "122604"}}

    with pytest.raises(ValueError, match="KIS_REST_SOURCE_TIMESTAMP_MISMATCH"):
        normalizer.normalize(
            price_response={**PRICE, "output1": {**PRICE["output1"], "aspr_acpt_hour": "122603"}},
            asking_price_response=ask,
            collected_at=datetime.now(timezone.utc),
            run_id="run-1",
        )
