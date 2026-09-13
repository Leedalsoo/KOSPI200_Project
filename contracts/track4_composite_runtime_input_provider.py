from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .track4_runtime_input_provider import Track4RuntimeInputProvider, Track4RuntimeInputReadiness, Track4InputSourceUnavailable


class Track4CompositeRuntimeInputProvider(Track4RuntimeInputProvider):
    """Compose authoritative market and account projections without synthesizing data."""

    def __init__(self, market_provider: Track4RuntimeInputProvider, account_provider: Track4RuntimeInputProvider) -> None:
        self._market = market_provider
        self._account = account_provider

    def readiness(self) -> Track4RuntimeInputReadiness:
        m = self._market.readiness()
        a = self._account.readiness()
        return Track4RuntimeInputReadiness(
            market=m.market,
            history=m.history,
            account_pnl=a.account_pnl,
            greeks=m.greeks,
            attribution=m.attribution and a.attribution,
        )

    def observed_at(self):
        market_at = self._market.observed_at()
        account_at = self._account.observed_at()
        if market_at != account_at:
            raise Track4InputSourceUnavailable(f"TRACK4_SOURCE_TIMESTAMP_MISMATCH: market={market_at!s} account={account_at!s}")
        return market_at

    def current_price(self) -> Decimal: return self._market.current_price()
    def active_vol(self) -> Decimal: return self._market.active_vol()
    def base_vol(self) -> Decimal: return self._market.base_vol()
    def current_pnl(self) -> Decimal: return self._account.current_pnl()
    def current_equity(self) -> Decimal: return self._account.current_equity()
    def price_history(self) -> Sequence[Decimal]: return self._market.price_history()
    def current_delta(self) -> Decimal: return self._market.current_delta()
    def current_gamma(self) -> Decimal: return self._market.current_gamma()
    def premium_spent(self) -> Decimal: return self._market.premium_spent()
    def accumulated_gamma_profit(self) -> Decimal: return self._market.accumulated_gamma_profit()
    def theta_decay_cost(self) -> Decimal: return self._market.theta_decay_cost()
