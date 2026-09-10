from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

@dataclass(frozen=True)
class CanonicalMarketTick:
    instrument_id: str
    observed_at: datetime
    price: Decimal
    volume: Decimal | None = None
    source_sequence: int | None = None


@dataclass(frozen=True)
class DataQuality:
    is_fresh: bool
    is_complete: bool
    source_available: bool
    reason: str | None = None


@dataclass(frozen=True)
class MarketState:
    as_of: datetime
    ticks: Mapping[str, CanonicalMarketTick]
    quality: Mapping[str, DataQuality]


class EnvironmentType(str, Enum):
    HIGH_SPEED = "high_speed"
    VIRTUAL = "virtual"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class OptionInstrumentIdentity:
    """Environment-neutral authoritative identity for an option instrument."""

    instrument_id: str
    symbol: str
    expiry: str | None = None
    option_type: str | None = None
    strike: Decimal | None = None


@dataclass(frozen=True)
class ExecutionLeg:
    """One typed leg of a strategy-owned multi-leg execution plan.

    Instrument identity resolution remains outside Strategy; strike/option_type are
    explicit strategy outputs and submission policy is intentionally not owned here.
    """

    leg_id: str
    side: str
    quantity: int
    option_type: str | None = None
    strike: Decimal | None = None
    requested_price: Decimal | None = None


@dataclass(frozen=True)
class MultiLegExecutionPlan:
    """Lossless strategy plan for one logical multi-leg intent.

    This is additive to OrderIntent. It describes legs only; atomicity, ordering,
    partial-fill compensation and broker submission policy belong to OMS/Execution.
    """

    group_id: str
    strategy_id: str
    legs: Sequence[ExecutionLeg]
    purpose: str | None = None

    def __post_init__(self) -> None:
        if not self.group_id:
            pass
            raise ValueError("group_id must be non-empty")
        if not self.legs:
            pass
            raise ValueError("MultiLegExecutionPlan requires at least one leg")
        leg_ids = [leg.leg_id for leg in self.legs]
        if len(set(leg_ids)) != len(leg_ids):
            pass
            raise ValueError("leg_id values must be unique within a plan")
        if any(leg.quantity <= 0 for leg in self.legs):
            pass
            raise ValueError("leg quantity must be positive")


@dataclass(frozen=True)
class OrderIntent:
    """Environment-neutral instruction emitted by Core/OMS.

    instrument_identity preserves domain identity without introducing broker-specific fields.
    The additive execution/provenance fields preserve existing program semantics
    without moving broker-specific details into Core.
    """

    client_order_id: str
    instrument_id: str
    side: str
    quantity: int
    intent_type: str
    strategy_id: str | None = None
    risk_context: str | None = None
    instrument_identity: OptionInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    order_type: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class BrokerOrderCommand:
    """Environment-specific translation of an OrderIntent."""

    client_order_id: str
    instrument_id: str
    side: str
    quantity: int
    order_type: str
    broker_symbol: str | None = None
    session_id: str | None = None
    instrument_identity: OptionInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    strategy_id: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class BrokerOrderResponse:
    """Transport-level broker ACK/result; not an execution or fill report."""

    client_order_id: str
    accepted: bool
    broker_order_id: str | None = None
    broker_code: str | None = None
    message: str | None = None
    raw_response: Mapping[str, object] | None = None


@dataclass(frozen=True)
class OrderAckEvent:
    """Canonical order acknowledgement event; never an execution/fill."""

    client_order_id: str
    accepted: bool
    broker_order_id: str | None = None
    broker_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ExecutionReport:
    """Canonical execution result returned by an Environment adapter."""

    client_order_id: str
    broker_order_id: str | None
    execution_id: str | None
    status: str
    filled_quantity: int
    remaining_quantity: int
    execution_price: Decimal | None
    execution_timestamp: datetime | None
    source_freshness: DataQuality | None = None
    rejected_reason: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    """Environment-neutral account read model."""

    as_of: datetime
    balances: Mapping[str, Decimal]
    freshness: DataQuality


@dataclass(frozen=True)
class PositionSnapshot:
    """Environment-neutral position read model."""

    as_of: datetime
    positions: Mapping[str, Decimal]
    freshness: DataQuality


@dataclass(frozen=True)
class ProviderHealth:
    """Environment-neutral provider health result."""

    available: bool
    as_of: datetime | None = None
    reason: str | None = None


__all__: Sequence[str] = (
    "AccountSnapshot",
    "BrokerOrderCommand",
    "BrokerOrderResponse",
    "CanonicalMarketTick",
    "DataQuality",
    "EnvironmentType",
    "ExecutionReport",
    "ExecutionLeg",
    "MultiLegExecutionPlan",
    "OrderAckEvent",
    "MarketState",
    "OrderIntent",
    "OptionInstrumentIdentity",
    "PositionSnapshot",
    "ProviderHealth",
)


__all__ = (
    "AccountSnapshot",
    "BrokerOrderCommand",
    "BrokerOrderResponse",
    "CanonicalMarketTick",
    "DataQuality",
    "EnvironmentType",
    "ExecutionReport",
    "ExecutionLeg",
    "MultiLegExecutionPlan",
    "OrderAckEvent",
    "MarketState",
    "OrderIntent",
    "OptionInstrumentIdentity",
    "PositionSnapshot",
    "ProviderHealth",
)

