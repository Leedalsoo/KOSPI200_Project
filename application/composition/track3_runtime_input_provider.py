from __future__ import annotations

from typing import Any

from contracts.track3_runtime_input_source import Track3RuntimeInputSource
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput, UnavailableStrategyPayload
from core.strategy.track3_statistical_arbitrage import Track3MarketInput


class Track3RuntimeInputProvider:
    """Materialize Track3 only from an injected authoritative source."""

    strategy_id = "Strategy_3_StatArb"

    def __init__(self, source: Track3RuntimeInputSource | None = None) -> None:
        self.source = source

    def build(
        self,
        market_state: MarketState,
        *,
        account: Any | None = None,
    ) -> StrategyContext:
        observed_at = market_state.as_of
        symbol = self._symbol(market_state)
        if self.source is None or not symbol:
            return self._unavailable("TRACK3_AUTHORITATIVE_SOURCE_REQUIRED")

        payload = self.source.get_input(symbol, observed_at)
        if payload is None:
            return self._unavailable("TRACK3_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE")
        if payload.observed_at != observed_at:
            return self._unavailable("TRACK3_INPUT_TIMESTAMP_MISMATCH")
        if not payload.source.strip():
            return self._unavailable("TRACK3_INPUT_SOURCE_REQUIRED")
        if len(payload.spread_history) < 10:
            return self._unavailable("TRACK3_SPREAD_HISTORY_UNAVAILABLE")
        if payload.active_vol <= 0 or payload.base_vol <= 0:
            return self._unavailable("TRACK3_VOLATILITY_SOURCE_INVALID")
        if payload.total_fees < 0 or payload.premium_spent < 0:
            return self._unavailable("TRACK3_COST_SOURCE_INVALID")
        if not payload.options_legs:
            return self._unavailable("TRACK3_OPTION_LEGS_UNAVAILABLE")

        tick = market_state.ticks[symbol]
        current_price = float(tick.price)
        common = None
        if account is not None:
            snapshot = account.snapshot() if callable(getattr(account, "snapshot", None)) else account
            balances = getattr(snapshot, "balances", {})
            pnl = balances.get("realized_pnl")
        else:
            pnl = None

        data = Track3MarketInput(
            spread_history=payload.spread_history,
            active_vol=payload.active_vol,
            base_vol=payload.base_vol,
            price_change_rate=payload.price_change_rate,
            bid_ask_spread=payload.bid_ask_spread,
            gap_pct=payload.gap_pct,
            is_gap=payload.is_gap,
            time_str=observed_at.strftime("%H:%M:%S"),
            market_stable=payload.market_stable,
            spread_normalizing=payload.spread_normalizing,
            allow_size_up=payload.allow_size_up,
            current_pnl=float(pnl) if pnl is not None else 0.0,
            total_fees=payload.total_fees,
            premium_spent=payload.premium_spent,
            current_price=current_price,
            options_legs=payload.options_legs,
            date_str=observed_at.date().isoformat(),
        )
        return StrategyContext(
            market_state=market_state,
            strategy_id=self.strategy_id,
            input=StrategyInput(payload=data, data_status={
                "track3": "AVAILABLE",
                "source": payload.source,
            }),
        )

    @staticmethod
    def _symbol(market_state: MarketState) -> str:
        return next(iter(market_state.ticks), "")

    @classmethod
    def _unavailable(cls, reason: str) -> StrategyContext:
        sources = (
            "market_stability",
            "spread_normalization",
            "position_sizing",
            "fee_ledger",
            "premium_attribution",
            "option_legs",
        )
        return StrategyContext(
            market_state=None,
            strategy_id=cls.strategy_id,
            input=StrategyInput(
                payload=UnavailableStrategyPayload(cls.strategy_id, sources, reason),
                data_status={source: "UNAVAILABLE" for source in sources},
            ),
        )
