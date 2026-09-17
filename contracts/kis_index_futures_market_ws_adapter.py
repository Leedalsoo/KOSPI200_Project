from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class KISIndexFuturesWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS index-futures realtime frame cannot be adapted safely."""


@dataclass(frozen=True)
class KisIndexFuturesMarketObservation:
    shrn_iscd: str
    observed_hour: str
    price: Decimal | None
    volume: Decimal | None
    ask_price: Decimal | None
    bid_price: Decimal | None
    source: str


_H0IFCNT0 = "H0IFCNT0"
_H0IFASP0 = "H0IFASP0"

# H0IFCNT0: symbol, time, current price, accumulated volume, ask1, bid1
_TRADE_SYMBOL = 0
_TRADE_TIME = 1
_TRADE_PRICE = 5
_TRADE_VOLUME = 10
_TRADE_ASK1 = 35
_TRADE_BID1 = 36

# H0IFASP0: symbol, time, ask1, bid1
_QUOTE_SYMBOL = 0
_QUOTE_TIME = 1
_QUOTE_ASK1 = 2
_QUOTE_BID1 = 7


def _decode_fields(frame: str, expected_tr_id: str) -> list[str]:
    parts = frame.split("|")
    if len(parts) < 4 or parts[0] not in {"0", "1"}:
        raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
    if parts[1] != expected_tr_id:
        raise KISIndexFuturesWebSocketAdapterInvalid("unexpected KIS TR ID")
    try:
        field_count = int(parts[2])
    except ValueError as exc:
        raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS field count") from exc
    values = parts[3].split("^")
    if field_count != len(values):
        raise KISIndexFuturesWebSocketAdapterInvalid("KIS field count mismatch")
    return values


class KISIndexFuturesMarketWebSocketAdapter:
    """Adapt official KIS index-futures trade/quote frames into typed observations."""

    TRADE_TR_ID = _H0IFCNT0
    QUOTE_TR_ID = _H0IFASP0

    def adapt(self, frame: str, *, source: str | None = None) -> KisIndexFuturesMarketObservation:
        parts = frame.split("|")
        if len(parts) < 2:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS realtime frame")
        if parts[1] == self.TRADE_TR_ID:
            return self._adapt_trade(frame, source=source or "KIS:H0IFCNT0")
        if parts[1] == self.QUOTE_TR_ID:
            return self._adapt_quote(frame, source=source or "KIS:H0IFASP0")
        raise KISIndexFuturesWebSocketAdapterInvalid("unsupported KIS index-futures TR ID")

    def _adapt_trade(self, frame: str, *, source: str) -> KisIndexFuturesMarketObservation:
        values = _decode_fields(frame, self.TRADE_TR_ID)
        required_max = max(_TRADE_SYMBOL, _TRADE_TIME, _TRADE_PRICE, _TRADE_VOLUME, _TRADE_ASK1, _TRADE_BID1)
        if len(values) <= required_max:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS H0IFCNT0 payload is incomplete")
        symbol = values[_TRADE_SYMBOL].strip()
        if not symbol:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS futures short code is missing")
        try:
            return KisIndexFuturesMarketObservation(
                shrn_iscd=symbol,
                observed_hour=values[_TRADE_TIME].strip(),
                price=Decimal(values[_TRADE_PRICE]),
                volume=Decimal(values[_TRADE_VOLUME]),
                ask_price=Decimal(values[_TRADE_ASK1]),
                bid_price=Decimal(values[_TRADE_BID1]),
                source=source,
            )
        except Exception as exc:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid H0IFCNT0 numeric field") from exc

    def _adapt_quote(self, frame: str, *, source: str) -> KisIndexFuturesMarketObservation:
        values = _decode_fields(frame, self.QUOTE_TR_ID)
        required_max = max(_QUOTE_SYMBOL, _QUOTE_TIME, _QUOTE_ASK1, _QUOTE_BID1)
        if len(values) <= required_max:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS H0IFASP0 payload is incomplete")
        symbol = values[_QUOTE_SYMBOL].strip()
        if not symbol:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS futures short code is missing")
        try:
            return KisIndexFuturesMarketObservation(
                shrn_iscd=symbol,
                observed_hour=values[_QUOTE_TIME].strip(),
                price=None,
                volume=None,
                ask_price=Decimal(values[_QUOTE_ASK1]),
                bid_price=Decimal(values[_QUOTE_BID1]),
                source=source,
            )
        except Exception as exc:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid H0IFASP0 numeric field") from exc
