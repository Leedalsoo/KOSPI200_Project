from __future__ import annotations

from datetime import date
from typing import Protocol


class OptionExpirySourceError(ValueError):
    """Raised when an authoritative option expiry cannot be resolved."""


class OptionExpirySource(Protocol):
    """Authoritative option-contract expiry boundary."""

    def resolve_expiry(self, symbol: str) -> date | None:
        """Return the source-owned expiry date for one broker symbol."""
        ...


def resolve_authoritative_option_expiry(
    source: OptionExpirySource, symbol: str
) -> date:
    """Resolve one expiry and fail closed when the source cannot prove it."""
    if not symbol or not symbol.strip():
        raise OptionExpirySourceError("OPTION_SYMBOL_REQUIRED")
    expiry = source.resolve_expiry(symbol.strip())
    if expiry is None:
        raise OptionExpirySourceError("AUTHORITATIVE_OPTION_EXPIRY_NOT_FOUND")
    if not isinstance(expiry, date):
        raise OptionExpirySourceError("AUTHORITATIVE_OPTION_EXPIRY_INVALID")
    return expiry
