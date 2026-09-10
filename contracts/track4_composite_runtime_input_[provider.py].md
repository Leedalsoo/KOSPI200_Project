```python
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4InputTimestampMismatch,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4CompositeRuntimeInputProvider(Track4RuntimeInputProvider):
    """Compose independent authoritative partial Track4 providers without synthesizing data."""

    def __init__(self, market_provider: Track4RuntimeInputProvider, account_provider: Track4RuntimeInputProvider) -> None:
        self._market_provider = market_provider
        self._account_provider = account_provider

    def readiness(self) -> Track4RuntimeInputReadiness:
        market = self._market_provider.readiness()
        account = self._account_provider.readiness()
        return Track4RuntimeInputReadiness(
            market=market.market or account.market,
            history=market.history or account.history,
            account_pnl=market.account_pnl or account.account_pnl,
            greeks=market.greeks or account.greeks,
            attribution=market.attribution or account.attribution,
        )

    def observed_at(self):
        market_at = self._market_provider.observed_at()
        account_at = self._account_provider.observed_at()
        if market_at != account_at:
            raise Track4InputTimestampMismatch(
                f"TRACK4_SOURCE_TIMESTAMP_MISMATCH: market={market_at!s} account={account_at!s}"
            )
        return market_at

    def current_price(self) -> Decimal: return self._market_provider.current_price()
    def active_vol(self) -> Decimal: return self._market_provider.active_vol()
    def base_vol(self) -> Decimal: return self._market_provider.base_vol()
    def current_pnl(self) -> Decimal: return self._account_provider.current_pnl()
    def current_equity(self) -> Decimal: return self._account_provider.current_equity()
    def price_history(self) -> Sequence[Decimal]: return self._market_provider.price_history()
    def current_delta(self) -> Decimal: return self._market_provider.current_delta()
    def current_gamma(self) -> Decimal: return self._market_provider.current_gamma()
    def premium_spent(self) -> Decimal: return self._market_provider.premium_spent()
    def accumulated_gamma_profit(self) -> Decimal: return self._market_provider.accumulated_gamma_profit()
    def theta_decay_cost(self) -> Decimal: return self._market_provider.theta_decay_cost()
```

## 경계

- Market과 Account/PnL 두 partial Provider의 authoritative source만 조합한다.

- Composite에서 값의 계산·추정·합성을 하지 않는다.

- price_history는 Market provider의 공개 관측 history projection을 그대로 전달한다.

- 각 source가 공급하지 않는 값은 원 Provider의 Track4InputSourceUnavailable를 그대로 전파한다.

- 전체 source completeness 확보 전에는 Runtime process_tick production 연결을 수행하지 않는다.