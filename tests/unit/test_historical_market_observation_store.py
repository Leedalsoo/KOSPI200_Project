import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
    RawMarketDataReference,
)
from environments.virtual.market.historical_market_store import HistoricalMarketStore


def make_observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-1",
        observed_at=None,
        collected_at=datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc),
        source="kis_vts_rest",
        provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1",
        run_id="run-1",
        contract=OptionInstrumentIdentity(
            instrument_id="B01610C41", symbol="B01610C41", expiry="202610",
            option_type="CALL", strike=Decimal("1595.0"),
        ),
        quote=MarketQuote(last=Decimal("0.08"), bid=Decimal("0.08"), ask=Decimal("0.09")),
        order_book=MarketOrderBook(),
        analytics=MarketAnalytics(),
        provenance=MarketDataProvenance(tr_ids=("FHMIF10000000",)),
        raw_reference=RawMarketDataReference(raw_id="raw-1", content_hash="hash-1"),
    )


def test_observation_uses_separate_schema_and_legacy_ticks_remain_loadable(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    observation = make_observation()

    store.append_observation(observation)
    loaded = store.load_observations()

    assert len(loaded) == 1
    assert loaded[0].observation_id == "obs-1"
    assert loaded[0].quote.last == Decimal("0.08")
    assert store.records() is not None


def test_raw_record_rejects_credentials(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")

    with pytest.raises(ValueError, match="RAW_MARKET_DATA_CREDENTIAL_FORBIDDEN"):
        store.append_raw_record(
            raw_id="raw-1",
            source="kis_vts_rest",
            provider="KISOptionRestAdapter",
            endpoint="/uapi/test",
            tr_id="TEST",
            collected_at=datetime.now(timezone.utc),
            run_id="run-1",
            request_metadata={"appkey": "secret-value"},
            response_metadata={"rt_cd": "0"},
            payload={"output": {"futs_shrn_iscd": "B01610C41"}},
            http_status=200,
        )


def test_raw_record_round_trip_and_provenance_link(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    store.append_raw_record(
        raw_id="raw-1",
        source="kis_vts_rest",
        provider="KISOptionRestAdapter",
        endpoint="/uapi/test",
        tr_id="TEST",
        collected_at=datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc),
        run_id="run-1",
        request_metadata={"FID_INPUT_ISCD": "B01610C41"},
        response_metadata={"rt_cd": "0", "msg_cd": "MCA00000"},
        payload={"output": {"futs_shrn_iscd": "B01610C41", "optn_prpr": "0.08"}},
        http_status=200,
    )
    records = store.raw_records()
    assert len(records) == 1
    assert records[0]["raw_id"] == "raw-1"
    assert records[0]["payload"]["output"]["optn_prpr"] == "0.08"
    assert "appkey" not in json.dumps(records[0]).lower()
