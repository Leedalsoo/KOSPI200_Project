"""Deterministic integration fixtures for the nine Standard Core strategies."""

from datetime import datetime
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track2_asymmetric_trap import Track2MarketInputs
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5MarketInput
from core.strategy.track6_daily_tail_insurance import Track6MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9MarketInput

AS_OF = datetime(2026, 1, 2, 10, 0)
DATE = "2026-01-02"
PRICE = Decimal("350")


def canonical_market_state() -> MarketState:
    return MarketState(
        as_of=AS_OF,
        ticks={
            "KOSPI200": CanonicalMarketTick(
                instrument_id="KOSPI200",
                observed_at=AS_OF,
                price=PRICE,
                volume=None,
            )
        },
        quality={},
    )


def common_input() -> CommonStrategyInput:
    return CommonStrategyInput(as_of=AS_OF, current_price=PRICE)


def payloads():
    return {
        "TRACK1_TAIL_DEFENSE": Track1Input(
            strategy_id="TRACK1_TAIL_DEFENSE",
            momentum_confirmed=False,
            days_to_expiry=10.0,
            current_time=AS_OF,
            active_vol=1.0,
            base_vol=1.0,
        ),
        "track2_asymmetric_trap": Track2MarketInputs(
            strategy_id="track2_asymmetric_trap",
            bbw_window=(2.0, 1.0),
            volume_window=(1.0, 10.0),
            basis=Decimal("0.5"),
            put_iv=Decimal("1.2"),
            call_iv=Decimal("1.0"),
            poc_price=Decimal("348"),
            bid_qtys=(Decimal("10"),) * 5,
            ask_qtys=(Decimal("1"),) * 5,
            active_vol=1.0,
            base_vol=1.0,
        ),
        "track3_stat_arb": Track3MarketInput(
            strategy_id="track3_stat_arb",
            spread_history=(1.0,) * 10,
            active_vol=1.0,
            base_vol=1.0,
            time_str="10:00:00",
            date_str=DATE,
            current_pnl=0.0,
            total_fees=0.0,
        ),
        "track4_gamma_scalping": Track4MarketInput(
            observed_at=AS_OF,
            current_price=PRICE,
            active_vol=Decimal("1"),
            base_vol=Decimal("1"),
            time_str="10:00:00",
            current_delta=Decimal("0"),
            current_gamma=Decimal("0"),
            current_pnl=Decimal("0"),
            premium_spent=Decimal("200000"),
            accumulated_gamma_profit=Decimal("0"),
            theta_decay_cost=Decimal("0"),
            current_equity=Decimal("1000000"),
        ),
        "track5_gap_divergence": Track5MarketInput(
            strategy_id="track5_gap_divergence",
            open_price=PRICE,
            previous_close=PRICE,
            active_vol=Decimal("1"),
            regime="NORMAL",
            current_price=PRICE,
        ),
        "track6_daily_tail_insurance": Track6MarketInput(
            strategy_id="track6_daily_tail_insurance",
            current_price=PRICE,
            active_vol=Decimal("1"),
            base_vol=Decimal("1"),
            budget=Decimal("1000000"),
            date_str=DATE,
            time_str="10:00:00",
        ),
        "track7_volatility_skew_weekly_insurance": Track7MarketInput(
            strategy_id="track7_volatility_skew_weekly_insurance",
            current_price=PRICE,
            budget=Decimal("1000000"),
            date_str=DATE,
            is_new_week_start=False,
            active_vol=Decimal("1"),
            call_iv=Decimal("1"),
            put_iv=Decimal("1"),
            time_str="10:00:00",
            is_expiry_day=False,
            is_week_end=False,
        ),
        "track8_macro_regime_monthly_strangle": Track8MarketInput(
            strategy_id="track8_macro_regime_monthly_strangle",
            dte=Decimal("20"),
            budget=Decimal("1000000"),
            current_price=PRICE,
            current_regime="NORMAL",
            date_str=DATE,
            current_pnl=Decimal("0"),
            total_fees=Decimal("0"),
            time_str="10:00:00",
            active_vol=Decimal("1"),
            margin_ratio=Decimal("0"),
            risk_guard_active=False,
        ),
        "track9_event_overnight_insurance": Track9MarketInput(
            strategy_id="track9_event_overnight_insurance",
            current_price=PRICE,
            active_sell_qty=10,
            current_insurance_qty=5,
            date_str=DATE,
            time_str="10:00:00",
        ),
    }


def contexts() -> dict[str, StrategyContext]:
    state = canonical_market_state()
    return {
        strategy_id: StrategyContext(
            market_state=state,
            strategy_id=strategy_id,
            input=StrategyInput(common=common_input(), payload=payload),
        )
        for strategy_id, payload in payloads().items()
    }
