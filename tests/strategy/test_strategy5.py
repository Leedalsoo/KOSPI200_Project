from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track5_gap_divergence import Track5ExecutionInput, Track5GapDivergence, Track5State
from core.strategy.registry import StrategyRegistry
from application.strategy_hub.hub import StrategyHub


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


def _futures_exit_result(status="FILLED", filled_quantity=5, remaining_quantity=0,
                         execution_id="T5-FUTURES-FILL", execution_price="101.5",
                         leg_id="MINI_FUTURES_EXIT", pending_legs=0, routed_legs=1):
    report = SimpleNamespace(
        status=status,
        filled_quantity=filled_quantity,
        remaining_quantity=remaining_quantity,
        execution_id=execution_id,
        execution_timestamp=datetime(2026, 10, 6, 9, 1),
        execution_price=Decimal(str(execution_price)) if execution_price is not None else None,
        leg_id=leg_id,
    )
    return SimpleNamespace(
        reports=(report,), pending_legs=pending_legs, routed_legs=routed_legs
    )


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
    assert s.state.futures_close_requested and not s.state.futures_closed
    s.on_execution_result("TRACK5_GAP_HEDGE_FUTURES_EXIT", _futures_exit_result())
    assert s.state.futures_closed and not s.state.futures_close_requested
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


def _mini_futures_identity():
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.futures_contract_spec import FuturesProductType

    return FuturesInstrumentIdentity(
        instrument_id="MFUT", symbol="MFUT",
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source="TEST",
    )


def test_strategy5_stop_requests_futures_exit_before_option_exit():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))

    futures_exit = s.evaluate_mean_reversion(Decimal("103"))
    assert len(futures_exit) == 1
    assert futures_exit[0].direction == "CLOSE_FUTURES"
    assert "OPTION_STOP_REQUIRES_HEDGE_CLOSE" in futures_exit[0].reason
    assert s.state.is_active and s.state.futures_close_requested
    assert not s.state.futures_closed
    assert s.evaluate_mean_reversion(Decimal("103")) == ()
    s.on_execution_result("TRACK5_GAP_HEDGE_FUTURES_EXIT", _futures_exit_result())
    assert s.state.futures_closed

    option_exit = s.evaluate_mean_reversion(Decimal("103"))
    assert len(option_exit) == 1
    assert option_exit[0].direction == "CLOSE_OPTION"
    assert option_exit[0].execution_proposal.tag_id == "GAP_DIVERGENCE_OPTION_STOP_EXIT"
    assert not s.state.is_active


def test_strategy5_timeout_is_counted_in_evaluations_and_closes_hedge_first():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))

    for _ in range(s.MAX_OPEN_EVALUATIONS - 1):
        assert s.evaluate_mean_reversion(Decimal("102.2")) == ()
    futures_exit = s.evaluate_mean_reversion(Decimal("102.2"))
    assert len(futures_exit) == 1
    assert futures_exit[0].direction == "CLOSE_FUTURES"
    assert "TIMEOUT_REQUIRES_HEDGE_CLOSE" in futures_exit[0].reason
    assert s.state.futures_close_requested and not s.state.futures_closed
    assert s.evaluate_mean_reversion(Decimal("102.2")) == ()
    s.on_execution_result("TRACK5_GAP_HEDGE_FUTURES_EXIT", _futures_exit_result())
    assert s.state.futures_closed

    option_exit = s.evaluate_mean_reversion(Decimal("102.2"))
    assert len(option_exit) == 1
    assert option_exit[0].direction == "CLOSE_OPTION"
    assert f"TIMEOUT_{s.MAX_OPEN_EVALUATIONS}_EVALUATIONS" in option_exit[0].reason
    assert not s.state.is_active


def test_strategy5_same_price_path_keeps_futures_first_then_closes_option():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))

    futures_exit = s.evaluate_mean_reversion(Decimal("99"))
    assert len(futures_exit) == 1 and futures_exit[0].direction == "CLOSE_FUTURES"
    assert s.state.is_active and s.state.futures_close_requested
    assert s.evaluate_mean_reversion(Decimal("99")) == ()
    s.on_execution_result("TRACK5_GAP_HEDGE_FUTURES_EXIT", _futures_exit_result())
    option_exit = s.evaluate_mean_reversion(Decimal("99"))
    assert len(option_exit) == 1 and option_exit[0].direction == "CLOSE_OPTION"
    assert not s.state.is_active


def test_strategy5_missing_or_invalid_execution_input_fails_closed():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    analytics = _snapshot(at, 102, 100, 102)
    assert s.evaluate(StrategyContext(strategy_id=s.strategy_id, analytics=analytics, input=None)) == ()
    assert s.evaluate(StrategyContext(
        strategy_id=s.strategy_id, analytics=analytics,
        input=StrategyInput(payload={"selected_strike": "105"}),
    )) == ()
    assert not s.state.is_active


def test_strategy5_extreme_z_score_is_rejected():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    signals = s.evaluate(_context(s, at, 104, 100, 104))
    assert signals == ()
    assert not s.state.is_active


def test_strategy5_build_execution_plan_supports_futures_and_option_exits():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))
    futures_signal = s.evaluate_mean_reversion(Decimal("101.5"))[0]
    futures_plan = s.build_execution_plan(
        "T5-FUTURES-EXIT", proposal=futures_signal.execution_proposal,
        futures_identity=_mini_futures_identity(),
    )
    assert futures_plan.purpose == "TRACK5_GAP_HEDGE_FUTURES_EXIT"
    assert len(futures_plan.legs) == 1
    assert futures_plan.legs[0].leg_id == "MINI_FUTURES_EXIT"
    assert futures_plan.legs[0].side == "BUY"
    assert futures_plan.legs[0].quantity == 5
    s.on_execution_result("TRACK5_GAP_HEDGE_FUTURES_EXIT", _futures_exit_result())

    option_signal = s.evaluate_mean_reversion(Decimal("100"))[0]
    option_plan = s.build_execution_plan(
        "T5-OPTION-EXIT", proposal=option_signal.execution_proposal,
        futures_identity=_mini_futures_identity(),
    )
    assert option_plan.purpose == "TRACK5_GAP_HEDGE_OPTION_EXIT"
    assert len(option_plan.legs) == 1
    assert option_plan.legs[0].leg_id == "OPTION_EXIT"
    assert option_plan.legs[0].side == "SELL"
    assert option_plan.legs[0].quantity == 1



def test_strategy5_order_ack_and_partial_fill_do_not_authorize_option_exit():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))
    exit_signal = s.evaluate_mean_reversion(Decimal("101.5"))
    assert len(exit_signal) == 1
    assert exit_signal[0].direction == "CLOSE_FUTURES"
    assert s.state.futures_close_requested
    assert not s.state.futures_closed

    s.on_execution_result(
        "TRACK5_GAP_HEDGE_FUTURES_EXIT",
        _futures_exit_result(status="NEW", filled_quantity=0, remaining_quantity=5,
                             execution_id=None, execution_price=None),
    )
    assert s.evaluate_mean_reversion(Decimal("101.5")) == ()
    assert not s.state.futures_closed

    s.on_execution_result(
        "TRACK5_GAP_HEDGE_FUTURES_EXIT",
        _futures_exit_result(status="PARTIALLY_FILLED", filled_quantity=2,
                             remaining_quantity=3, execution_id="T5-PARTIAL"),
    )
    assert s.evaluate_mean_reversion(Decimal("101.5")) == ()
    assert not s.state.futures_closed

    s.on_execution_result(
        "TRACK5_GAP_HEDGE_FUTURES_EXIT",
        _futures_exit_result(status="FILLED", filled_quantity=5,
                             remaining_quantity=0, execution_id="T5-FULL"),
    )
    assert s.state.futures_closed
    option_exit = s.evaluate_mean_reversion(Decimal("100"))
    assert len(option_exit) == 1
    assert option_exit[0].direction == "CLOSE_OPTION"


def test_strategy5_rejected_futures_close_never_authorizes_option_exit():
    s = Track5GapDivergence()
    at = datetime(2026, 10, 6, 9, 0)
    assert s.evaluate(_context(s, at, 102, 100, 102))
    assert s.evaluate_mean_reversion(Decimal("101.5"))[0].direction == "CLOSE_FUTURES"

    s.on_execution_result(
        "TRACK5_GAP_HEDGE_FUTURES_EXIT",
        _futures_exit_result(status="REJECTED", filled_quantity=0,
                             remaining_quantity=5, execution_id=None,
                             execution_price=None),
    )
    assert not s.state.futures_closed
    assert not s.state.futures_close_requested
    assert s.evaluate_mean_reversion(Decimal("101.5"))[0].direction == "CLOSE_FUTURES"



def test_strategy5_execution_fill_is_dispatched_through_strategy_hub():
    strategy = Track5GapDivergence()
    strategy.state = Track5State(
        is_active=True, direction="SHORT", futures_side="SELL",
        futures_close_requested=True, futures_closed=False,
    )
    registry = StrategyRegistry()
    registry.register(strategy)
    hub = StrategyHub(registry, [(strategy.strategy_id, strategy.version)])
    report = SimpleNamespace(
        leg_id="MINI_FUTURES_EXIT", status="FILLED",
        filled_quantity=5, remaining_quantity=0,
        execution_id="T5-HUB-FILL",
        execution_timestamp=datetime(2026, 10, 6, 9, 1),
        execution_price=Decimal("101.5"),
    )
    result = SimpleNamespace(reports=(report,), pending_legs=0, routed_legs=1)

    hub.on_execution_result(
        strategy.strategy_id, "TRACK5_GAP_HEDGE_FUTURES_EXIT", result
    )

    assert strategy.state.futures_closed
    assert not strategy.state.futures_close_requested
