"""Deterministic integration fixtures for the nine Standard Core strategies."""

from datetime import datetime
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5MarketInput
from core.strategy.track6_daily_tail_insurance import Track6MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9MarketInput
from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track2 import build_track2_evaluators

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


def track2_analytics() -> MarketSnapshot:
    observations = {
        "bbw_window": (0.30, 0.20, 0.10),
        "volume_window": (100.0, 100.0, 500.0),
        "basis": Decimal("0.5"),
        "put_iv": Decimal("1.2"),
        "call_iv": Decimal("1.0"),
        "poc_price": Decimal("348"),
        "bid_qtys": (Decimal("10"),) * 5,
        "ask_qtys": (Decimal("1"),) * 5,
        "active_vol": Decimal("1"),
        "base_vol": Decimal("1"),
    }
    market = MarketSnapshot("FIXTURE", AS_OF, AnalyticsProvenance("integration-fixture"), None, observations)
    keys = (
        ("volatility.bbw", ("bbw_window",)), ("volume.z_score", ("volume_window",)),
        ("microstructure.obi", ("bid_qtys", "ask_qtys")), ("futures.basis", ("basis",)),
        ("options.put_iv", ("put_iv",)), ("options.call_iv", ("call_iv",)),
        ("volume_profile.poc", ("poc_price",)), ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
    )
    requests = tuple(AnalyticsRequest(k, "tick", 20, d, 1.0, "authoritative", "1") for k, d in keys)
    return AnalyticsEngine(build_track2_evaluators()).evaluate(market, requests)


def contexts() -> dict[str, StrategyContext]:
    state = canonical_market_state()
    result = {
        strategy_id: StrategyContext(
            market_state=state,
            strategy_id=strategy_id,
            input=StrategyInput(common=common_input(), payload=payload),
        )
        for strategy_id, payload in payloads().items()
    }
    result["track2_asymmetric_trap"] = StrategyContext(
        market_state=state,
        strategy_id="track2_asymmetric_trap",
        input=StrategyInput(common=common_input()),
        analytics=track2_analytics(),
    )
    return result









# No.060 이후 추가 대조한 Track4~Track9의 실제 typed contract를 반영했다.






# 이 fixture는 production input adapter가 아니며, 실제 전략 로직을 변경하지 않는다.

# Integration contract test for No.491.
# The harness mirrors the current OptionProject lifecycle contracts:
# RuntimeController owns Environment bundle lifecycle; LiveRuntimeBootstrap
# exposes explicit recovery/execution lifecycle and does not auto-start them.

def test_explicit_lifecycle_order_and_shared_settlement_state():
    events = []
    shared_state = {"oms": "OMS-1", "position": "POSITION-1"}
    controller = RuntimeController(Hub(Bundle(events)))
    execution = Execution(events, shared_state)
    recovery = Recovery(events)
    bootstrap = LiveRuntimeBootstrap(
        execution=execution,
        order_router=object(),
        recovery_service=recovery,
    )

# controller.start("live-config", "live-policy")
    assert controller._state == "RUNNING"
    assert bootstrap.startup_reconcile("Q1") == "SETTLED"
# asyncio.run(bootstrap.start_execution("HTS"))
# assert asyncio.run(bootstrap.receive_execution_once()) is shared_state
# asyncio.run(bootstrap.close_execution())
# controller.stop()

    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "recovery.startup_reconcile", "execution.start",
        "execution.receive", "execution.close",
        "bundle.stop", "bundle.shutdown",
    ]
    assert controller._state == "STOPPED"
# assert controller._hub.active is None


def test_no_implicit_bootstrap_or_execution_lifecycle_inside_controller():
    events = []
    controller = RuntimeController(Hub(Bundle(events)))
# controller.start("live-config", "live-policy")
    assert events == ["bundle.initialize", "bundle.connect", "bundle.start"]
# controller.stop()
    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "bundle.stop", "bundle.shutdown",
    ]
