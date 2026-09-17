from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Protocol


@dataclass(frozen=True)
class PositionAggregate:
    """Authoritative aggregate state required by pre-trade Risk."""

    side: str
    qty: int
    avg_price: float | None = None
    contract_multiplier: Decimal | None = None
    identity_source: str | None = None


class PositionAggregateSource(Protocol):
    """Supplies authoritative per-instrument aggregate positions."""

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        ...


# Environment / Position implementation
# -> PositionAggregateSource.snapshot()
# -> Mapping[instrument_key, PositionAggregate]
# -> Risk Position Adapter
# -> RiskPositionInput







# Environment / Position implementation
# -> PositionAggregateSource.snapshot()
# -> Mapping[instrument_key, PositionAggregate]
# -> Risk Position Adapter
# -> RiskPositionInput
