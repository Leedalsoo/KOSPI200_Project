"""Materialize nine Standard Strategy inputs from authoritative Virtual Runtime data."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Any
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput, UnavailableStrategyPayload
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track2_asymmetric_trap import Track2MarketInputs
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5MarketInput
from core.strategy.track6_daily_tail_insurance import Track6MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9MarketInput

class StandardRuntimeInputProvider:
    """Materialize typed inputs only from current VMS observations/state."""
    def __init__(self, market: Any) -> None:
        self.data = VirtualRuntimeDataProvider(market)

    @staticmethod
    def _unavailable(strategy_id: str, sources: tuple[str, ...], reason: str) -> StrategyContext:
        return StrategyContext(strategy_id=strategy_id, input=StrategyInput(
            payload=UnavailableStrategyPayload(strategy_id, sources, reason),
            data_status={source: "UNAVAILABLE" for source in sources}))

    @staticmethod
    def _position_values(account: Any | None) -> tuple[int, int, str | None]:
        if account is None:
            return 0, 0, None
        positions = getattr(account, "positions", None) or {}
        qty = 0
        side = None
        for state in positions.values() if hasattr(positions, "values") else ():
            if isinstance(state, dict):
                qty += int(state.get("qty", 0) or 0)
                side = state.get("side") or side
        return qty, qty, side

    def build(self, tick: Any, market_state: MarketState, account: Any | None = None) -> dict[str, StrategyContext]:
        d = self.data.snapshot(tick)
        as_of, price = d.as_of, d.price
        budget = Decimal("0"); pnl = Decimal("0")
        if account is not None:
            snapshot = account.snapshot() if callable(getattr(account, "snapshot", None)) else account
            balances = getattr(snapshot, "balances", {})
            budget = Decimal(str(balances.get("available_cash", 0)))
            pnl = Decimal(str(balances.get("realized_pnl", 0)))
        common = CommonStrategyInput(as_of=as_of, current_price=price, active_vol=d.active_vol, base_vol=d.base_vol,
            budget=budget, current_pnl=pnl, time_str=as_of.strftime("%H:%M:%S"), date_str=as_of.date().isoformat())
        contexts: dict[str, StrategyContext] = {}
        contexts["TRACK1_TAIL_DEFENSE"] = StrategyContext(market_state, "TRACK1_TAIL_DEFENSE", StrategyInput(common,
            Track1Input(active_vol=float(d.active_vol or 0), base_vol=float(d.base_vol or 0), current_time=as_of,
                        days_to_expiry=0.0, momentum_confirmed=False, coverage_ratio=0.0, short_option_net_delta=0.0)))
        basis = Decimal(str(self.data.market.futures_price)) - price
        ticks = self.data.market.recent_ticks
        if d.put_iv is None or d.option_iv is None:
            contexts["track2_asymmetric_trap"] = self._unavailable("track2_asymmetric_trap", ("option_iv_chain",), "OPTION_CHAIN_UNAVAILABLE")
        else:
            contexts["track2_asymmetric_trap"] = StrategyContext(market_state, "track2_asymmetric_trap", StrategyInput(common,
                Track2MarketInputs(tuple(float(abs(x / price - 1)) for x in d.prices), tuple(float(t.volume) for t in ticks), basis,
                    d.put_iv, d.option_iv, d.open_price, tuple(Decimal(str(t.volume)) for t in ticks[-5:]), tuple(Decimal(str(t.volume)) for t in ticks[-5:]),
                    float(d.active_vol or 0), float(d.base_vol or 0))))
        spread = tuple(float(x) for x in d.prices)
        contexts["Strategy_3_StatArb"] = StrategyContext(market_state, "Strategy_3_StatArb", StrategyInput(common,
            Track3MarketInput(spread_history=spread, active_vol=float(d.active_vol or 0), base_vol=float(d.base_vol or 0),
                price_change_rate=float((price / d.previous_close - 1) if d.previous_close else 0), bid_ask_spread=float(Decimal(str(tick.ask_price))-Decimal(str(tick.bid_price))),
                gap_pct=float((d.open_price/d.previous_close-1) if d.previous_close else 0), is_gap=False, time_str=as_of.strftime("%H:%M:%S"), market_stable=True,
                spread_normalizing=True, allow_size_up=False, current_pnl=float(pnl), total_fees=0.0, premium_spent=0.0, current_price=float(price), options_legs=(), regime=d.macro_regime or "NORMAL", date_str=as_of.date().isoformat())))
        if d.option_delta is None or d.option_gamma is None:
            contexts["track4_gamma_scalping"] = self._unavailable("track4_gamma_scalping", ("option_iv_greeks",), "OPTION_GREEKS_UNAVAILABLE")
        else:
            contexts["track4_gamma_scalping"] = StrategyContext(market_state, "track4_gamma_scalping", StrategyInput(common,
                Track4MarketInput(as_of, price, d.active_vol or Decimal("0"), d.base_vol or Decimal("0"), as_of.strftime("%H:%M:%S"), d.option_delta, d.option_gamma, pnl, budget, d.prices)))
        contexts["track5_gap_divergence"] = StrategyContext(market_state, "track5_gap_divergence", StrategyInput(common,
            Track5MarketInput("track5_gap_divergence", d.open_price, d.previous_close, d.active_vol or Decimal("0"), d.macro_regime or "NORMAL", price)))
        contexts["track6_daily_tail_insurance"] = StrategyContext(market_state, "track6_daily_tail_insurance", StrategyInput(common,
            Track6MarketInput("track6_daily_tail_insurance", price, d.active_vol or Decimal("0"), d.base_vol or Decimal("0"), budget, as_of.date().isoformat(), as_of.strftime("%H:%M:%S"))))
        if d.put_iv is None or d.option_iv is None:
            contexts["track7_volatility_skew_weekly_insurance"] = self._unavailable("track7_volatility_skew_weekly_insurance", ("option_iv_chain",), "OPTION_CHAIN_UNAVAILABLE")
        else:
            monday, friday = as_of.weekday()==0, as_of.weekday()==4
            def ma(n):
                window=d.prices[-n:]; return sum(window, Decimal("0"))/Decimal(len(window))
            contexts["track7_volatility_skew_weekly_insurance"] = StrategyContext(market_state, "track7_volatility_skew_weekly_insurance", StrategyInput(common,
                Track7MarketInput("track7_volatility_skew_weekly_insurance", price, budget, as_of.date().isoformat(), monday, d.active_vol or Decimal("0"), d.option_iv, d.put_iv, False,
                    ma(1),ma(3),ma(5),ma(10),d.low_price,d.high_price,as_of.strftime("%H:%M:%S"),False,friday)))
        expiry=datetime.strptime(tick.expiry,"%Y%m").replace(day=1); dte=Decimal(str(max(0,(expiry.date()-as_of.date()).days)))
        contexts["track8_macro_regime_monthly_strangle"] = StrategyContext(market_state,"track8_macro_regime_monthly_strangle",StrategyInput(common,
            Track8MarketInput("track8_macro_regime_monthly_strangle",dte,budget,price,d.macro_regime or "NORMAL",as_of.date().isoformat(),pnl,Decimal("0"),as_of.strftime("%H:%M:%S"),d.active_vol or Decimal("0"),Decimal("0"),False)))
        qty, insurance_qty, _side = self._position_values(account)
        contexts["track9_event_overnight_insurance"] = StrategyContext(market_state,"track9_event_overnight_insurance",StrategyInput(common,
            Track9MarketInput("track9_event_overnight_insurance",price,qty,insurance_qty,as_of.date().isoformat(),as_of.strftime("%H:%M:%S"),bool(d.event_upcoming),Decimal("0"),Decimal("0"),pnl,Decimal("0"),Decimal("250000"),None,True,qty,insurance_qty,Decimal("0"),False,Decimal("0"),Decimal("0"))))
        return contexts
