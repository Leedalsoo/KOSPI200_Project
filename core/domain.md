폴더 페이지

[Child Page] market_models.py
```python
from contracts.types import CanonicalMarketTick, DataQuality, MarketState


__all__ = ("CanonicalMarketTick", "DataQuality", "MarketState")
```
## Ownership correction
Canonical market DTO ownership is contracts/types.py.
This module remains as the existing Core-domain import surface so current Standard Core code can continue importing CanonicalMarketTick, DataQuality, and MarketState without creating a second DTO definition.
Rules remain unchanged: missing market data is explicit and synthetic fallback prices must not masquerade as real input.

[Child Page] option_contract.py
```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

@dataclass(frozen=True)
class OptionContract:
    instrument_id: str
    underlying_id: str
    option_type: str
    strike: Decimal
    expiry: date

class TradingCalendar(Protocol):
    def trading_days_between(self, start: date, end: date) -> int: ...

def calculate_dte(contract: OptionContract, today: date, calendar: TradingCalendar) -> int:
    return calendar.trading_days_between(today, contract.expiry)
```
External master download and Calendar source implementation are outside Core. Unverified production calendar remains BLOCKED.