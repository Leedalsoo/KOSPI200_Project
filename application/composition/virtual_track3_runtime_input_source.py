from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.track3_runtime_input_source import Track3RuntimeInput


class VirtualTrack3RuntimeInputSource:
    """Build Track3 inputs from one live Virtual Exchange/VSSF runtime scope."""

    source_name = "VirtualExchange.VMS+VirtualBroker.VSSF"

    def __init__(self, market: Any, account: Any, vssf_runtime: Any, option_master: Any) -> None:
        self.market = market
        self.account = account
        self.vssf_runtime = vssf_runtime
        self.option_master = option_master

    def get_input(self, symbol: str, observed_at: datetime) -> Track3RuntimeInput | None:
        tick = getattr(self.market, "last_tick", None)
        recent = tuple(getattr(self.market, "recent_ticks", ()))
        if tick is None or not recent or not symbol:
            return None
        if getattr(tick, "symbol", None) != symbol:
            return None
        if datetime.fromisoformat(tick.timestamp) != observed_at:
            return None

        prices = tuple(float(getattr(item, "underlying_price")) for item in recent)
        if len(prices) < 11:
            return None
        returns = tuple(prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1] != 0)
        if len(returns) < 10:
            return None

        spread_history = returns
        active_vol = sum(abs(value) for value in returns) / len(returns)
        base_window = returns[:-1]
        base_vol = sum(abs(value) for value in base_window) / len(base_window)
        previous = prices[-2]
        price_change_rate = prices[-1] / previous - 1.0 if previous else 0.0
        bid = float(getattr(tick, "bid_price", 0.0))
        ask = float(getattr(tick, "ask_price", 0.0))
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        bid_ask_spread = ask - bid
        prior_spreads = tuple(
            float(getattr(item, "ask_price", 0.0)) - float(getattr(item, "bid_price", 0.0))
            for item in recent[:-1]
            if float(getattr(item, "bid_price", 0.0)) > 0 and float(getattr(item, "ask_price", 0.0)) >= float(getattr(item, "bid_price", 0.0))
        )
        spread_normalizing = bool(prior_spreads and bid_ask_spread <= prior_spreads[-1])
        market_stable = max(abs(value) for value in returns[-5:]) < 0.02
        is_gap = bool(getattr(tick, "timestamp", "")[11:19] < "09:05:00" and abs(price_change_rate) >= 0.008)

        options_legs = self._option_legs(tick)
        if not options_legs:
            return None
        multipliers = {float(leg["contract_multiplier"]) for leg in options_legs}
        if len(multipliers) != 1:
            return None
        contract_multiplier = multipliers.pop()

        total_fees, premium_spent = self._execution_totals()
        return Track3RuntimeInput(
            observed_at=observed_at,
            spread_history=spread_history,
            active_vol=active_vol,
            base_vol=base_vol,
            price_change_rate=price_change_rate,
            bid_ask_spread=bid_ask_spread,
            gap_pct=price_change_rate,
            is_gap=is_gap,
            market_stable=market_stable,
            spread_normalizing=spread_normalizing,
            allow_size_up=market_stable and spread_normalizing,
            total_fees=total_fees,
            premium_spent=premium_spent,
            options_legs=options_legs,
            contract_multiplier=contract_multiplier,
            source=self.source_name,
        )

    def _option_legs(self, tick: Any) -> tuple[dict[str, object], ...]:
        quotes = getattr(self.market, "option_quotes", {})
        expiry = str(getattr(tick, "expiry", ""))
        legs: list[dict[str, object]] = []
        for key, quote in sorted(quotes.items(), key=lambda item: str(item[0])):
            if not isinstance(key, tuple) or len(key) != 3 or not isinstance(quote, dict):
                continue
            option_type, strike, quote_expiry = str(key[0]).upper(), float(key[1]), str(key[2])
            if quote_expiry != expiry:
                continue
            last = quote.get("last")
            multiplier = quote.get("contract_multiplier")
            if last is None or multiplier is None or float(last) <= 0 or float(multiplier) <= 0:
                continue
            identity = self.option_master.find_contract_identity(
                expiry, option_type, Decimal(str(strike))
            )
            if identity is None or not identity.shrn_iscd or identity.contract_multiplier is None:
                continue
            if float(identity.contract_multiplier) != float(multiplier):
                continue
            legs.append({
                "instrument_id": identity.shrn_iscd,
                "strike": strike,
                "price": float(last),
                "current_market_price": float(last),
                "qty": 1,
                "side": "BUY",
                "type": option_type,
                "expiry": expiry,
                "contract_multiplier": float(identity.contract_multiplier),
                "source": self.source_name,
            })
        return tuple(legs)

    def _execution_totals(self) -> tuple[float, float]:
        engine = getattr(self.vssf_runtime, "execution_engine", None)
        reports = tuple(getattr(engine, "reports", ())) if engine is not None else ()
        total_fees = 0.0
        premium_spent = 0.0
        for report in reports:
            fee = float(getattr(report, "fee", 0.0))
            total_fees += fee
            asset_type = str(getattr(getattr(report, "asset_type", None), "value", getattr(report, "asset_type", ""))).upper()
            side = str(getattr(getattr(report, "side", None), "value", getattr(report, "side", ""))).upper()
            if asset_type == "OPTION" and side == "BUY":
                premium_spent += float(getattr(report, "executed_price", 0.0)) * int(getattr(report, "executed_qty", 0))
        return total_fees, premium_spent
