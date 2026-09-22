from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from contracts.futures_identity_source_port import FuturesInstrumentIdentity

@dataclass(frozen=True)
class CanonicalMarketTick:
    instrument_id: str
    observed_at: datetime
    price: Decimal
    volume: Decimal | None = None
    source_sequence: int | None = None
    seq_id: int | None = None
    underlying_price: Decimal | None = None
    underlying_symbol: str = ""
    underlying_observed_hour: str = ""
    underlying_source: str = ""


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
    contract_multiplier: Decimal | None = None
    identity_source: str | None = None


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
    position_role: str = "NONE"


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
            raise ValueError("group_id must be non-empty")
        if not self.legs:
            raise ValueError("MultiLegExecutionPlan requires at least one leg")
        leg_ids = [leg.leg_id for leg in self.legs]
        if len(set(leg_ids)) != len(leg_ids):
            raise ValueError("leg_id values must be unique within a plan")
        if any(leg.quantity <= 0 for leg in self.legs):
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
    instrument_identity: OptionInstrumentIdentity | FuturesInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    order_type: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None
    position_role: str = "NONE"


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
    instrument_identity: OptionInstrumentIdentity | FuturesInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    strategy_id: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None
    position_role: str = "NONE"


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
    fee: Decimal | None = None
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
    source: str | None = None
    observed_at: datetime | None = None
    freshness_seconds: float | None = None


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



@dataclass(frozen=True)
class OrderBookLevel:
    level: int
    price: Decimal | None = None
    quantity: Decimal | None = None


@dataclass(frozen=True)
class MarketQuote:
    last: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True)
class MarketOrderBook:
    bids: Sequence[OrderBookLevel] = ()
    asks: Sequence[OrderBookLevel] = ()
    total_bid_quantity: Decimal | None = None
    total_ask_quantity: Decimal | None = None


@dataclass(frozen=True)
class MarketAnalytics:
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None


@dataclass(frozen=True)
class MarketDataProvenance:
    endpoints: Sequence[str] = ()
    tr_ids: Sequence[str] = ()
    source_timestamps: Sequence[str] = ()
    metadata: Sequence[tuple[str, str]] = ()


@dataclass(frozen=True)
class RawMarketDataReference:
    raw_id: str
    content_hash: str | None = None


@dataclass(frozen=True)
class MarketObservation:
    observation_id: str
    observed_at: datetime | None
    collected_at: datetime
    source: str
    provider: str
    schema_version: str
    run_id: str
    contract: OptionInstrumentIdentity
    quote: MarketQuote
    order_book: MarketOrderBook
    analytics: MarketAnalytics
    provenance: MarketDataProvenance
    raw_reference: RawMarketDataReference | None = None
    underlying_price: Decimal | None = None
    underlying_symbol: str = ""
    underlying_observed_hour: str = ""
    underlying_source: str = ""

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("MARKET_OBSERVATION_CONTRACT_ID_REQUIRED")
        if not self.contract.instrument_id or not self.contract.symbol:
            raise ValueError("MARKET_OBSERVATION_CONTRACT_ID_REQUIRED")
        if not self.source or not self.provider or not self.schema_version or not self.run_id:
            raise ValueError("MARKET_OBSERVATION_METADATA_REQUIRED")


__all__ += (
    "MarketAnalytics",
    "MarketDataProvenance",
    "MarketObservation",
    "MarketOrderBook",
    "MarketQuote",
    "OrderBookLevel",
    "RawMarketDataReference",
)
