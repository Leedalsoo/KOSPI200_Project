from __future__ import annotations

from datetime import date
from typing import Any

from contracts.option_expiry_source import OptionExpirySourceError


class KisOptionMasterExpirySource:
    """Expose exact expiry dates owned by the KIS Option Master."""

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def resolve_expiry(self, symbol: str) -> date | None:
        if not symbol or not symbol.strip():
            raise OptionExpirySourceError("OPTION_SYMBOL_REQUIRED")
        expiry_text = self.option_master.get_expiry(symbol.strip())
        if not expiry_text:
            return None
        try:
            return date.fromisoformat(str(expiry_text))
        except ValueError as exc:
            raise OptionExpirySourceError(
                "AUTHORITATIVE_OPTION_EXPIRY_INVALID"
            ) from exc
