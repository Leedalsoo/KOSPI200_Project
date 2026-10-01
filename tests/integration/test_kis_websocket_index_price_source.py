from datetime import date, datetime, timezone
from decimal import Decimal
import json

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from contracts.kis_index_price_source import KISIndexPriceObservation
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.websocket_index_price_source import KISWebSocketIndexPriceSource


def test_h0upcnt0_adapter_maps_authoritative_index_fields():
    frame = "0|H0UPCNT0|001|2001^145537^1101.44^2^19.62^99196^12550500^24^3740^1.81^1077.35^1102.88^1068.45^-4.47^5^21.06^2^-13.37^5^-0.41^1.95^-1.24^0^105^8^88^0^0^0^2"
    observation = __import__("contracts.kis_index_price_websocket_adapter", fromlist=["KISIndexPriceWebSocketAdapter"]).KISIndexPriceWebSocketAdapter().adapt(frame)
    assert observation.index_code == "2001"
    assert observation.observed_hour == "145537"
    assert observation.price == Decimal("1101.44")
    assert observation.source == "KIS:H0UPCNT0"


def test_h0upcnt0_source_preserves_observed_and_collected_timestamps():
    frame = "0|H0UPCNT0|001|2001^145537^1101.44^2^19.62^99196^12550500^24^3740^1.81^1077.35^1102.88^1068.45^-4.47^5^21.06^2^-13.37^5^-0.41^1.95^-1.24^0^105^8^88^0^0^0^2"
    received_at = datetime(2026, 10, 1, 5, 55, 37, 267594, tzinfo=timezone.utc)
    source = KISWebSocketIndexPriceSource(session_date=date(2026, 10, 1))
    observation = source.update_frame(frame, received_at=received_at)
    assert observation.observed_at == datetime(2026, 10, 1, 14, 55, 37)
    assert observation.collected_at == received_at
    assert observation.tr_id == "H0UPCNT0"
    assert observation.source == "KIS:H0UPCNT0:2001"


def test_basis_accepts_websocket_index_observation_within_two_seconds():
    basis = KISBasisSource(max_time_delta_seconds=2.0)
    basis.update_futures(
        price=Decimal("1101.50"),
        observed_at=datetime(2026, 10, 1, 14, 55, 37),
        source="KIS:H0IFCNT0",
        contract_symbol="A05610",
    )
    index = KISIndexPriceObservation(
        "KOSPI200", "2001", Decimal("1101.44"),
        datetime(2026, 10, 1, 14, 55, 37),
        "KIS:H0UPCNT0:2001", "H0UPCNT0",
        datetime(2026, 10, 1, 5, 55, 37, 267594, tzinfo=timezone.utc),
    )
    basis.update_index(index)
    assert basis.get_basis("KOSPI200") == Decimal("0.06")
