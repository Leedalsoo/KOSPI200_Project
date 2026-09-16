from __future__ import annotations

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from contracts.option_orderbook_source import OptionOrderBookSnapshot


class KISOptionOrderBookSource:
    """Latest authoritative H0IOASP0 order book keyed by KIS option symbol."""

    def __init__(self) -> None:
        self._books: dict[str, OptionOrderBookSnapshot] = {}

    def update(self, observation: KisIndexOptionMarketObservation) -> None:
        book = observation.order_book
        if book is None or observation.source != "KIS:H0IOASP0":
            return
        if book.symbol != observation.shrn_iscd or not book.is_complete():
            raise ValueError("AUTHORITATIVE_OPTION_ORDERBOOK_IDENTITY_OR_DEPTH_INVALID")
        self._books[book.symbol] = book

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        clean_symbol = str(symbol).strip()
        if not clean_symbol:
            return None
        book = self._books.get(clean_symbol)
        if book is None or book.symbol != clean_symbol or not book.is_complete():
            return None
        return book
