from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
)
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.kis_rest_market_observation_collector import (
    KISRestMarketObservationCollector,
    CollectionTarget,
    ManualClock,
    RateLimiter,
)


def identity(symbol="B01610C41"):
    return OptionInstrumentIdentity(
        instrument_id=symbol,
        symbol=symbol,
        expiry="202610",
        option_type="CALL",
        strike=Decimal("1595.0"),
        contract_multiplier=Decimal("250000"),
        identity_source="KRX_KIS_MASTER",
    )


def responses(symbol="B01610C41", ts="122603"):
    price = {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "output1": {
            "futs_shrn_iscd": symbol,
            "futs_prpr": "0.08",
            "acml_vol": "1232",
            "aspr_acpt_hour": ts,
            "hts_ints_vltl": "56.69",
            "delta_val": "0.0182",
            "gamma_val": "0.001",
            "theta_val": "-0.02",
            "vega_val": "0.11",
        },
    }
    asking = {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "output1": {"futs_shrn_iscd": symbol},
        "output2": {
            "aspr_acpt_hour": ts,
            "futs_askp1": "0.09",
            "futs_bidp1": "0.08",
            "askp_rsqn1": "100",
            "bidp_rsqn1": "200",
            "total_askp_rsqn": "744",
            "total_bidp_rsqn": "2740",
        },
    }
    return price, asking


class FakeTransport:
    def __init__(self, price, asking):
        self.price = price
        self.asking = asking
        self.calls = []

    def request_price(self, symbol):
        self.calls.append(("price", symbol))
        return 200, self.price

    def request_order_book(self, symbol):
        self.calls.append(("order_book", symbol))
        return 200, self.asking


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds

    def now(self):
        return datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc) + timedelta(seconds=self.value)


def test_price_and_orderbook_requests_respect_one_second_interval(tmp_path):
    clock = FakeClock()
    price, asking = responses()
    transport = FakeTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "SUCCESS"
    assert transport.calls == [("price", "B01610C41"), ("order_book", "B01610C41")]
    assert clock.sleeps == [1.0]


def test_missing_identity_is_blocked_without_rest_request(tmp_path):
    clock = FakeClock()
    price, asking = responses()
    transport = FakeTransport(price, asking)
    collector = KISRestMarketObservationCollector(
        identity_source={},
        transport=transport,
        store=HistoricalMarketStore(tmp_path / "market.jsonl"),
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "BLOCKED"
    assert result[0].reason == "AUTHORITATIVE_OPTION_IDENTITY_REQUIRED"
    assert transport.calls == []


def test_raw_and_canonical_observation_share_hash_reference(tmp_path):
    clock = FakeClock()
    price, asking = responses()
    transport = FakeTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "SUCCESS"
    observations = store.load_observations()
    raws = store.raw_records()
    assert len(observations) == 1
    assert len(raws) == 1
    assert observations[0].raw_reference is not None
    assert observations[0].raw_reference.raw_id == raws[0]["raw_id"]
    assert observations[0].raw_reference.content_hash == raws[0]["content_hash"]
    assert "appsecret" not in str(raws[0]).lower()
    assert "access_token" not in str(raws[0]).lower()


def test_rt_cd_failure_does_not_store_observation(tmp_path):
    clock = FakeClock()
    price, asking = responses()
    asking["rt_cd"] = "1"
    transport = FakeTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "BLOCKED"
    assert result[0].reason == "KIS_REST_RESPONSE_NOT_SUCCESS"
    assert store.load_observations() == []


def test_source_timestamp_mismatch_does_not_store_observation(tmp_path):
    clock = FakeClock()
    price, asking = responses(ts="122603")
    asking["output2"]["aspr_acpt_hour"] = "122604"
    transport = FakeTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "BLOCKED"
    assert result[0].reason == "KIS_REST_SOURCE_TIMESTAMP_MISMATCH"
    assert store.load_observations() == []


def test_duplicate_raw_payload_is_not_promoted_twice(tmp_path):
    clock = FakeClock()
    price, asking = responses()
    transport = FakeTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    first = collector.collect_cycle([CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1")
    second = collector.collect_cycle([CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-2")

    assert first[0].status == "SUCCESS"
    assert second[0].status == "DUPLICATE"
    assert len(store.load_observations()) == 1
    assert len(store.raw_records()) == 1


def test_scenario_source_is_separate_from_original_archive(tmp_path):
    observation = MarketObservation(
        observation_id="obs-original",
        observed_at=None,
        collected_at=datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc),
        source="kis_vts_rest",
        provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1",
        run_id="run-original",
        contract=identity(),
        quote=MarketQuote(last=Decimal("0.08"), bid=Decimal("0.08"), ask=Decimal("0.09"), volume=Decimal("1232")),
        order_book=MarketOrderBook(),
        analytics=MarketAnalytics(),
        provenance=MarketDataProvenance(tr_ids=("FHMIF10000000", "FHMIF10010000")),
    )
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    store.append_observation(observation)
    loaded = store.load_observations()
    assert loaded[0].source == "kis_vts_rest"
    assert loaded[0].run_id == "run-original"



def test_transport_uses_official_price_and_orderbook_trs():
    from infrastructure.kis.kis_rest_market_observation_collector import (
        KISRestMarketObservationTransport,
    )

    class Response:
        status = 200

        def read(self):
            return b'{"rt_cd":"0","output1":{}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    class Auth:
        base_url = "https://openapivts.koreainvestment.com:29443"

        def get_auth_headers(self, tr_id):
            return {"authorization": "Bearer TEST", "tr_id": tr_id}

    transport = KISRestMarketObservationTransport(Auth(), urlopen=fake_urlopen)
    transport.request_price("B01610C41")
    transport.request_order_book("B01610C41")

    assert "inquire-price" in requests[0][0].full_url
    assert requests[0][0].headers["Tr_id"] == "FHMIF10000000"
    assert "inquire-asking-price" in requests[1][0].full_url
    assert requests[1][0].headers["Tr_id"] == "FHMIF10010000"


def test_http_failure_is_blocked_without_observation(tmp_path):
    class FailingTransport(FakeTransport):
        def request_price(self, symbol):
            return 500, {"rt_cd": "1", "msg_cd": "HTTP_ERROR"}

    clock = FakeClock()
    price, asking = responses()
    transport = FailingTransport(price, asking)
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    collector = KISRestMarketObservationCollector(
        identity_source={identity().symbol: identity()},
        transport=transport,
        store=store,
        clock=clock,
        limiter=RateLimiter(1.0, clock),
    )

    result = collector.collect_cycle(
        [CollectionTarget(identity())], run_id="run-1", cycle_id="cycle-1"
    )

    assert result[0].status == "BLOCKED"
    assert result[0].reason == "KIS_REST_HTTP_ERROR"
    assert store.load_observations() == []
