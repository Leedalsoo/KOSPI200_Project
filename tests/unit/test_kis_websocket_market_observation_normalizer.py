
from datetime import datetime, timezone
from decimal import Decimal

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from infrastructure.kis.kis_websocket_market_observation_normalizer import (
    KISWebSocketMarketObservationNormalizer,
    WebSocketUnderlyingContext,
)


def _frame(values, count=1):
    return f"0|H0IOCNT0|{count:03d}|{'^'.join(values)}"


class IdentityLookup:
    def get_contract_identity(self, symbol):
        from contracts.types import OptionInstrumentIdentity

        return OptionInstrumentIdentity(
            instrument_id=symbol,
            symbol=symbol,
            expiry="202610",
            option_type="CALL" if symbol.startswith("B") else "PUT",
            strike=Decimal("1100"),
            contract_multiplier=Decimal("250000"),
            identity_source="KIS_INDEX_OPTION_MASTER",
        )


def test_normalizer_projects_actual_h0iocnt0_greeks_into_canonical_observation():
    values = ["0"] * 58
    values[0] = "B01610A34"
    values[1] = "092202"
    values[2] = "11.70"
    values[10] = "238"
    values[28] = "0.46"
    values[29] = "0.00"
    values[31] = "-3.18"
    values[33] = "36.18"
    values[41] = "11.60"
    values[42] = "11.50"

    normalizer = KISWebSocketMarketObservationNormalizer(IdentityLookup())
    observed_at = datetime(2026, 10, 1, 0, 22, 2, tzinfo=timezone.utc)
    observations = normalizer.normalize_frame(
        _frame(values),
        received_at=observed_at,
        run_id="run-1",
        raw_id="2026-10-01:1",
        raw_content_hash="abc",
        underlying=WebSocketUnderlyingContext(
            price=Decimal("1075.44"),
            symbol="KOSPI200",
            observed_hour="092049",
            source="kis_vts_rest:price.output3",
        ),
    )

    assert len(observations) == 1
    item = observations[0]
    assert item.source == "kis_vts_websocket"
    assert item.provenance.tr_ids == ("H0IOCNT0",)
    assert item.analytics.delta == Decimal("0.46")
    assert item.analytics.gamma == Decimal("0.00")
    assert item.analytics.theta == Decimal("-3.18")
    assert item.analytics.implied_volatility == Decimal("36.18")
    assert item.raw_reference.raw_id == "2026-10-01:1"
    assert item.underlying_price == Decimal("1075.44")


def test_market_adapter_and_greeks_adapter_support_kis_repeated_record_layout():
    first = ["0"] * 58
    second = ["0"] * 58
    for values, symbol in ((first, "B01610A34"), (second, "C01610A34")):
        values[0] = symbol
        values[1] = "092202"
        values[2] = "11.70"
        values[10] = "1"
        values[28] = "0.46"
        values[29] = "0.00"
        values[31] = "-3.18"
        values[33] = "36.18"
        values[41] = "11.60"
        values[42] = "11.50"

    frame = _frame(first + second, count=2)
    market = KISIndexOptionMarketWebSocketAdapter().adapt_many(frame)
    assert [item.shrn_iscd for item in market] == ["B01610A34", "C01610A34"]
