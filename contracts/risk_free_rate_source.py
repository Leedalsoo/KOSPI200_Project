from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

class RiskFreeRateUnavailable(RuntimeError):
    """Authoritative risk-free-rate source is unavailable."""

@dataclass(frozen=True, slots=True)
class RiskFreeRateSnapshot:
    rate: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if self.rate < Decimal("-1"):
            pass
            raise ValueError("risk-free rate is invalid")
        if not self.source:
            pass
            raise ValueError("risk-free rate source is required")

class RiskFreeRateProvider(ABC):
    @abstractmethod
    def get_rate(self, observed_at: datetime) -> RiskFreeRateSnapshot:
        raise NotImplementedError
