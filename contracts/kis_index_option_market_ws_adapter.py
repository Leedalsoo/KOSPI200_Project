from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot


class KISIndexOptionMarketWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS index-option market frame cannot be adapted safely."""


@dataclass(frozen=True)
class KisIndexOptionMarketObservation:
    shrn_iscd: str
    observed_hour: str
    last_price: Decimal | None
    ask_price: Decimal | None
    bid_price: Decimal | None
    volume: Decimal | None
    source: str
    order_book: OptionOrderBookSnapshot | None = None


_H0IOCNT0 = "H0IOCNT0"
_H0IOASP0 = "H0IOASP0"

# KIS index-option realtime trade payload positions.
_TRADE_SYMBOL = 0
_TRADE_TIME = 1
_TRADE_PRICE = 2
_TRADE_VOLUME = 10
_TRADE_ASK1 = 41
_TRADE_BID1 = 42

# KIS index-option realtime quote payload positions.
_QUOTE_SYMBOL = 0
_QUOTE_TIME = 1
_QUOTE_ASK1 = 2
_QUOTE_BID1 = 7
_QUOTE_ASK_LEVELS = tuple(range(2, 7))
_QUOTE_BID_LEVELS = tuple(range(7, 12))
_QUOTE_ASK_QTY = tuple(range(22, 27))
_QUOTE_BID_QTY = tuple(range(27, 32))


def _decode_fields(frame: str, expected_tr_id: str) -> list[str]:
    parts = frame.split("|")
    if len(parts) < 4 or parts[0] not in {"0", "1"}:
        raise KISIndexOptionMarketWebSocketAdapterInvalid(
            "invalid KIS realtime frame envelope"
        )
    if parts[1] != expected_tr_id:
        raise KISIndexOptionMarketWebSocketAdapterInvalid("unexpected KIS TR ID")
    try:
        field_count = int(parts[2])
    except ValueError as exc:
        raise KISIndexOptionMarketWebSocketAdapterInvalid(
            "invalid KIS field count"
        ) from exc
    values = parts[3].split("^")
    if field_count != len(values):
        raise KISIndexOptionMarketWebSocketAdapterInvalid(
            "KIS field count mismatch"
        )
    return values


def _decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise KISIndexOptionMarketWebSocketAdapterInvalid(
            f"invalid {field_name} numeric field"
        ) from exc


class KISIndexOptionMarketWebSocketAdapter:
    """Adapt KIS H0IOCNT0/H0IOASP0 frames into one option market observation."""

    TRADE_TR_ID = _H0IOCNT0
    QUOTE_TR_ID = _H0IOASP0

    def adapt(
        self, frame: str, *, source: str | None = None
    ) -> KisIndexOptionMarketObservation:
        parts = frame.split("|")
        if len(parts) < 2:
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "invalid KIS realtime frame"
            )
        if parts[1] == self.TRADE_TR_ID:
            return self._adapt_trade(frame, source=source or "KIS:H0IOCNT0")
        if parts[1] == self.QUOTE_TR_ID:
            return self._adapt_quote(frame, source=source or "KIS:H0IOASP0")
        raise KISIndexOptionMarketWebSocketAdapterInvalid(
            "unsupported KIS index-option TR ID"
        )

    def _adapt_trade(
        self, frame: str, *, source: str
    ) -> KisIndexOptionMarketObservation:
        values = _decode_fields(frame, self.TRADE_TR_ID)
        required_max = max(
            _TRADE_SYMBOL, _TRADE_TIME, _TRADE_PRICE,
            _TRADE_VOLUME, _TRADE_ASK1, _TRADE_BID1,
        )
        if len(values) <= required_max:
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "KIS H0IOCNT0 payload is incomplete"
            )
        symbol = values[_TRADE_SYMBOL].strip()
        if not symbol:
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "KIS option short code is missing"
            )
        return KisIndexOptionMarketObservation(
            shrn_iscd=symbol,
            observed_hour=values[_TRADE_TIME].strip(),
            last_price=_decimal(values[_TRADE_PRICE], "option last price"),
            ask_price=_decimal(values[_TRADE_ASK1], "option ask price"),
            bid_price=_decimal(values[_TRADE_BID1], "option bid price"),
            volume=_decimal(values[_TRADE_VOLUME], "option volume"),
            source=source,
        )

    def _adapt_quote(
        self, frame: str, *, source: str
    ) -> KisIndexOptionMarketObservation:
        values = _decode_fields(frame, self.QUOTE_TR_ID)
        required_max = max(_QUOTE_SYMBOL, _QUOTE_TIME, _QUOTE_ASK1, _QUOTE_BID1)
        if len(values) <= required_max:
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "KIS H0IOASP0 payload is incomplete"
            )
        symbol = values[_QUOTE_SYMBOL].strip()
        if not symbol:
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "KIS option short code is missing"
            )
        ask_levels = tuple(
            OptionOrderBookLevel(
                _decimal(values[p], f"option ask price {i + 1}"),
                _decimal(values[q], f"option ask quantity {i + 1}"),
            )
            for i, (p, q) in enumerate(zip(_QUOTE_ASK_LEVELS, _QUOTE_ASK_QTY))
        )
        bid_levels = tuple(
            OptionOrderBookLevel(
                _decimal(values[p], f"option bid price {i + 1}"),
                _decimal(values[q], f"option bid quantity {i + 1}"),
            )
            for i, (p, q) in enumerate(zip(_QUOTE_BID_LEVELS, _QUOTE_BID_QTY))
        )
        order_book = OptionOrderBookSnapshot(
            symbol=symbol,
            observed_hour=values[_QUOTE_TIME].strip(),
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            source=source,
        )
        if not order_book.is_complete():
            raise KISIndexOptionMarketWebSocketAdapterInvalid(
                "KIS H0IOASP0 order-book quantities are incomplete"
            )
        return KisIndexOptionMarketObservation(
            shrn_iscd=symbol,
            observed_hour=values[_QUOTE_TIME].strip(),
            last_price=None,
            ask_price=ask_levels[0].price,
            bid_price=bid_levels[0].price,
            volume=None,
            source=source,
            order_book=order_book,
        )
