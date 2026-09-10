from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from contracts.account import AccountProvider
from contracts.track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4VSSFAccountProjectionProvider(Track4RuntimeInputProvider):
    """Partial read-only Track4 provider backed by authoritative AccountSnapshot."""

    def __init__(self, account: AccountProvider):
        self._account = account

    def readiness(self) -> Track4RuntimeInputReadiness:
        return Track4RuntimeInputReadiness(False, False, True, False, False)

    def _snapshot(self):
        snapshot = self._account.snapshot()
        required = ("cash", "realized_pnl", "unrealized_pnl")
        missing = [name for name in required if name not in snapshot.balances]
        if missing:
            raise Track4InputSourceUnavailable(
                f"TRACK4_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}"
            )
        return snapshot

    def observed_at(self):
        return self._snapshot().as_of

    def current_equity(self) -> Decimal:
        return Decimal(self._snapshot().balances["cash"])

    def current_pnl(self) -> Decimal:
        balances = self._snapshot().balances
        return Decimal(balances["realized_pnl"]) + Decimal(balances["unrealized_pnl"])

    def current_price(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")

    def active_vol(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")

    def base_vol(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")

    def price_high(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")

    def price_low(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")

    def price_close(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")

    def current_delta(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_GREEKS_SOURCE_UNAVAILABLE")

    def current_gamma(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_GREEKS_SOURCE_UNAVAILABLE")

    def premium_spent(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")

    def accumulated_gamma_profit(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")

    def theta_decay_cost(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")
