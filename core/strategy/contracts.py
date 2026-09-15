from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence, Mapping

from contracts.types import OptionInstrumentIdentity
from core.domain.market_models import MarketState


@dataclass(frozen=True)
class CommonStrategyInput:
    """Only values whose meaning and unit are shared by multiple strategies."""
    as_of: datetime
    current_price: Decimal | None = None
    active_vol: Decimal | None = None
    base_vol: Decimal | None = None
    budget: Decimal | None = None
    current_pnl: Decimal | None = None
    total_fees: Decimal | None = None
    time_str: str | None = None
    date_str: str | None = None


class StrategyPayload(Protocol):
    """Marker contract for strategy-specific typed input payloads."""


@dataclass(frozen=True)
class UnavailableStrategyPayload:
    """Explicit fail-closed payload when authoritative Runtime data is absent."""
    strategy_id: str
    required_sources: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class StrategyInput:
    common: CommonStrategyInput | None = None
    payload: StrategyPayload | None = None
    data_status: Mapping[str, str] | None = None


@dataclass(frozen=True)
class StrategyContext:
    market_state: MarketState | None = None
    strategy_id: str = ""
    input: StrategyInput | None = None


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    direction: str
    confidence: float
    reason: str
    instrument_identity: OptionInstrumentIdentity | None = None
    option_type_override: str | None = None
    strike_override: Decimal | None = None
    execution_proposal: "StrategyExecutionProposal | None" = None


class Strategy(Protocol):
    strategy_id: str
    version: str
    def initialize(self, context: StrategyContext) -> None: ...
    def on_market_state(self, context: StrategyContext) -> None: ...
    def evaluate(self, context: StrategyContext) -> Sequence[Signal]: ...
    def reset(self) -> None: ...
