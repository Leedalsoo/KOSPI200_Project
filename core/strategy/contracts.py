from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence

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
    """Marker contract for strategy-specific, typed input payloads.

    Strategy identity is authoritative in StrategyContext. Individual typed
    payloads may additionally expose strategy_id, but the field is not required
    because some strategy contracts intentionally carry no identity field.
    """


@dataclass(frozen=True)
class StrategyInput:
    common: CommonStrategyInput
    payload: StrategyPayload


@dataclass(frozen=True)
class StrategyContext:
    market_state: MarketState
    strategy_id: str
    input: StrategyInput | None = None


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    direction: str  # LONG / SHORT / FLAT
    confidence: float
    reason: str
    instrument_identity: OptionInstrumentIdentity | None = None

    # Strategy may express an option selection without replacing authoritative
    # market/master symbol or expiry.
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
