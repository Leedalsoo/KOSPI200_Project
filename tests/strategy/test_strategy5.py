from datetime import datetime, timedelta
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track5_gap_divergence import Track5ExecutionInput, Track5GapDivergence


def test_strategy5_effective_threshold_is_stricter_in_high_vol():
    s = Track5GapDivergence()
    assert s.effective_z_threshold("HIGH_VOL") == s.effective_z_threshold("NOISE_CHOPPY") == Decimal("1.8")


def test_strategy5_missing_analytics_fails_closed():
    s = Track5GapDivergence()
    assert s.evaluate(StrategyContext(strategy_id=s.strategy_id, analytics=None, input=None)) == ()


def _snapshot(at, open_price, previous_close, current_price, active_vol=Decimal("1"), regime="NORMAL"):
    market = MarketSnapshot(
        run_id="T5-TEST", as_of=at,
        provenance=AnalyticsProvenance(source="SYNTHETIC:test"),
        instrument_identity=None,
        observations={
            "open_price": Decimal(str(open_price)),
            "previous_close": Decimal(str(previous_close)),
            "current_price": Decimal(str(current_price)),
            "active_vol": Decimal(str(active_vol)),
            "regime": regime,
        },
    )
    keys = (
        ("price.open", ("open_price",)),
        ("price.gap", ("open_price", "previous_close")),
        ("price.last", ("current_price",)),
        ("price.previous_close", ("previous_close",)),
        ("volatility.expected_move", ("previous_close", "active_vol")),
        ("stats.z_score", ("open_price", "previous_close", "active_vol")),
        ("regime.market", ("regime",)),
    )
    requests = tuple(AnalyticsRequest(k, "tick", 1, deps, 1.0, "synthetic", "1") for k, deps in keys)
    return AnalyticsEngine(build_track5_evaluators()).evaluate(market, requests)


def _execution_input(option_type="CALL", strike="105"):
    return Track5ExecutionInput(
        expiry="202610",
        atm_strike=Decimal("102.5"),
        selected_strike=Decimal(str(strike)),
        option_type=option_type,
        strike_rank=2,
        liquidity_score=Decimal("100"),
    )


def _context(s, at, open_price, previous_close, current_price, option_type="CALL"):
    return StrategyContext(
        strategy_id=s.strategy_id,
        analytics=_snapshot(at, open_price, previous_close, current_price),
        input=StrategyInput(payload=_execution_input(option_type=option_type)),
    )


def test_strategy5_opening_gap_generates_option_plus_hedge_entry_signal():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    signals = s.evaluate(_context(s, at, 102, 100, 102))
    assert len(signals) == 1
    assert signals[0].direction == "SHORT"
    assert signals[0].kind.value == "EXECUTION"
    assert signals[0].execution_proposal.asset_type == "OPTION"
    assert signals[0].execution_proposal.option_type == "CALL"
    assert signals[0].execution_proposal.strike == Decimal("105")
    assert "MINI_FUTURES_QTY:5" in signals[0].reason


def test_strategy5_no_opening_gap_detects_sharp_move_within_30_minutes():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 100, 100, 100)) == ()
    signals = s.evaluate(_context(s, at + timedelta(minutes=10), 100, 100, 103))
    assert len(signals) == 1
    assert signals[0].direction == "SHORT"
    assert signals[0].execution_proposal.option_type == "CALL"
    assert "GAP_SOURCE:OPENING_WINDOW_INTRADAY_GAP" in signals[0].reason


def test_strategy5_does_not_create_intraday_gap_after_30_minutes():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 100, 100, 100)) == ()
    assert s.evaluate(_context(s, at + timedelta(minutes=31), 100, 100, 103)) == ()


def test_strategy5_closes_mini_futures_first_then_option_on_reversion():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))
    futures_exit = s.evaluate_mean_reversion(Decimal("102.5"))
    assert futures_exit == ()
    futures_exit = s.evaluate_mean_reversion(Decimal("101.5"))
    assert len(futures_exit) == 1
    assert futures_exit[0].direction == "CLOSE_FUTURES"
    assert futures_exit[0].execution_proposal.asset_type == "FUTURES"
    assert futures_exit[0].execution_proposal.proposed_quantity == 5
    assert futures_exit[0].execution_proposal.side == "BUY"
    option_exit = s.evaluate_mean_reversion(Decimal("100"))
    assert len(option_exit) == 1
    assert option_exit[0].direction == "CLOSE_OPTION"
    assert option_exit[0].execution_proposal.asset_type == "OPTION"
    assert option_exit[0].execution_proposal.proposed_quantity == 1
    assert option_exit[0].execution_proposal.side == "SELL"


def test_strategy5_plan_contains_option_one_and_mini_futures_five():
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.futures_contract_spec import FuturesProductType

    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    signal = s.evaluate(_context(s, at, 102, 100, 102))[0]
    futures_identity = FuturesInstrumentIdentity(
        instrument_id="MFUT", symbol="MFUT",
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source="TEST",
    )
    plan = s.build_execution_plan(
        "T5-GROUP",
        proposal=signal.execution_proposal,
        futures_identity=futures_identity,
    )
    assert len(plan.legs) == 2
    assert [(leg.option_type, leg.quantity, leg.side) for leg in plan.legs] == [
        ("CALL", 1, "BUY"),
        (None, 5, "SELL"),
    ]
