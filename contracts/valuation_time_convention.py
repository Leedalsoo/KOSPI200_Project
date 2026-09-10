from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

class ValuationTimeUnavailable(RuntimeError):
    """A complete valuation time convention is not available."""

@dataclass(frozen=True, slots=True)
class TimeToExpirySnapshot:
    expiry: date
    valuation_at: datetime
    years: Decimal
    source: str

    def __post_init__(self) -> None:
        if self.years <= 0:
            pass
            raise ValueError("time to expiry must be positive")
        if not self.source:
            pass
            raise ValueError("time-to-expiry source is required")

class ValuationTimeConvention(ABC):
    @abstractmethod
    def resolve(self, expiry: date, valuation_at: datetime) -> TimeToExpirySnapshot:
        raise NotImplementedError
