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
