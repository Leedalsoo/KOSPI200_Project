from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from core.market.session_policy import MarketSessionPolicy
from core.strategy.engine.phase_clock import at_or_after, in_window
from core.strategy.engine.s6_rules import S6_RULES
from core.strategy.engine.s6_plugin import S6CandidatePlugin
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6State
from verification.strategy_parity.harness import ExecutionCallback, ParityStep, compare_plugins
from verification.strategy_parity.scenarios import BASE_VALUES, active_strategy, case_contexts, make_context


def test_s6_rules_match_existing_strategy_and_session_policy():
    old = Track6DailyTailInsurance()
    assert S6_RULES.vol_trigger_multiplier == old.vol_trigger_multiplier == Decimal("1.3")
    assert S6_RULES.trailing_volatility_boundary == Decimal("1.3")
    assert S6_RULES.trailing_activation_below_boundary == Decimal("1.5")
    assert S6_RULES.trailing_activation_at_or_above_boundary == Decimal("2.0")
    assert S6_RULES.trailing_retain_ratio_high == Decimal("0.90")
    assert S6_RULES.trailing_retain_ratio_middle == Decimal("0.88")
    assert S6_RULES.trailing_retain_ratio_low == Decimal("0.85")
    assert S6_RULES.trailing_ratio_high_boundary == Decimal("2")
    assert S6_RULES.trailing_ratio_middle_boundary == Decimal("1.3")
    assert S6_RULES.watermark_update_ratio == Decimal("1.01")
    assert S6_RULES.take_profit_suppression_time == "15:12:00"
    assert S6_RULES.limit_cutoff == MarketSessionPolicy.text(MarketSessionPolicy.LIMIT_CUTOFF) == "15:00:00"
    assert S6_RULES.market_cutoff == MarketSessionPolicy.text(MarketSessionPolicy.MARKET_CUTOFF) == "15:15:00"
    assert S6_RULES.pending_cancel_end == MarketSessionPolicy.text(MarketSessionPolicy.PENDING_CANCEL_END) == "15:20:00"


def test_phase_clock_uses_string_comparison_and_half_open_window():
    assert at_or_after("15:12:00", "15:12:00")
    assert not at_or_after("15:11:59", "15:12:00")
    assert in_window("15:00:00", "15:00:00", "15:15:00")
    assert not in_window("15:15:00", "15:00:00", "15:15:00")


def test_candidate_exposes_same_identity_features_and_reset_state_shape():
    old = Track6DailyTailInsurance()
    candidate = S6CandidatePlugin()
    assert (candidate.strategy_id, candidate.version) == (old.strategy_id, old.version)
    assert candidate.feature_requirements() == old.feature_requirements()
    candidate.state = Track6State(is_active=True, long_put_strike=Decimal("100"), long_call_strike=Decimal("125"))
    candidate._exit_pending = True
    candidate.reset()
    assert candidate.state == Track6State()
    assert candidate._exit_pending is False


def test_pure_engine_does_not_mutate_input_state():
    from datetime import datetime
    from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
    from core.strategy.contracts import StrategyContext, StrategyInput
    from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput
    from core.strategy.engine.s6_engine import evaluate_s6

    at = datetime.fromisoformat("2026-10-01T10:00:00")
    values = {"price.last": Decimal("102"), "volatility.active": Decimal("1.2"), "volatility.base": Decimal("1"), "volatility.ratio": Decimal("1.2"), "portfolio.premium_spent": Decimal("10")}
    metrics = {key: AnalyticsMetric(key, value, AnalyticsStatus.AVAILABLE, "UNSPECIFIED", at, "candidate-test", ("UNIT_TEST",)) for key, value in values.items()}
    analytics = AnalyticsSnapshot("candidate-run", None, at, "tick", 1, "candidate-test", metrics)
    payload = Track6ExecutionInput("track6_daily_tail_insurance", "2026-10-01", listed_put_strike=Decimal("87.5"), listed_call_strike=Decimal("112.5"), contract_multiplier=Decimal("250000"))
    context = StrategyContext(strategy_id="track6_daily_tail_insurance", input=StrategyInput(payload=payload), analytics=analytics)
    initial = Track6State(is_active=True, long_put_strike=Decimal("100"), long_call_strike=Decimal("100"))
    result = evaluate_s6(initial, False, context)
    assert initial == Track6State(is_active=True, long_put_strike=Decimal("100"), long_call_strike=Decimal("100"))
    assert result.signals and result.signals[0].direction == "UPDATE_TRAILING"
    assert result.signals[0].kind.value == "NON_EXECUTION"


def test_manifest_identity_and_declared_s6_parameters_match_candidate():
    import json
    from pathlib import Path
    manifest = json.loads(Path("config/strategies/strategy-manifest.v1.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["strategies"] if item["strategy_id"] == "track6_daily_tail_insurance")
    candidate = S6CandidatePlugin()
    assert entry["code_version"] == candidate.version == "1.0"
    assert entry["parameters"]["vol_trigger_multiplier"] == str(S6_RULES.vol_trigger_multiplier) == "1.3"
    assert entry["parameters"]["insurance_qty"] == candidate.insurance_qty == 1


def test_legacy_and_candidate_are_equal_across_required_s6_branch_contexts():
    for label, legacy, context, expected in case_contexts():
        candidate = S6CandidatePlugin()
        candidate.state = replace(legacy.state)
        candidate._exit_pending = legacy._exit_pending
        method = "evaluate_take_profit" if label == "take_profit_suppressed_at_15_12" else "evaluate"
        result = compare_plugins(legacy, candidate, (ParityStep(context, label=label, method=method),))
        assert result.equal, (label, result.differences)
        observed = tuple(signal["direction"] for signal in result.left_trace[0]["signals"])
        assert observed == expected, (label, observed, expected)


def test_legacy_and_candidate_match_execution_callbacks_and_reset():
    for purpose in ("DAILY_TAIL_INSURANCE_TRAILING_CLOSE", "DAILY_TAIL_INSURANCE_LIMIT_CLOSE", "DAILY_TAIL_INSURANCE_FALLBACK_CLOSE"):
        legacy = active_strategy(high="20", trailing=True, pending=True)
        candidate = S6CandidatePlugin()
        candidate.state = replace(legacy.state)
        candidate._exit_pending = True
        result = compare_plugins(legacy, candidate, (ParityStep(
            make_context(), callbacks=(ExecutionCallback(purpose, SimpleNamespace(group_complete=True, position_flat=True)),),
            reset_after=True, label=purpose,
        ),))
        assert result.equal, (purpose, result.differences)
        assert result.left_trace[-1]["plugin"]["state"]["is_active"] is False

    for purpose, result_obj in (
        ("UNRELATED_PURPOSE", SimpleNamespace(group_complete=True, position_flat=True)),
        ("DAILY_TAIL_INSURANCE_TRAILING_CLOSE", SimpleNamespace(group_complete=False, position_flat=True)),
        ("DAILY_TAIL_INSURANCE_LIMIT_CLOSE", SimpleNamespace(group_complete=True, position_flat=False)),
    ):
        legacy = active_strategy(high="20", trailing=True, pending=True)
        candidate = S6CandidatePlugin()
        candidate.state = replace(legacy.state)
        candidate._exit_pending = True
        result = compare_plugins(legacy, candidate, (ParityStep(make_context(), callbacks=(ExecutionCallback(purpose, result_obj),), label=purpose),))
        assert result.equal, (purpose, result.differences)
        assert result.left_trace[-1]["plugin"]["state"]["is_active"] is True


def test_multistep_entry_trailing_close_callback_and_reset_parity():
    legacy = Track6DailyTailInsurance()
    candidate = S6CandidatePlugin()
    steps = (
        ParityStep(make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.3")}), label="entry"),
        ParityStep(make_context(values={**BASE_VALUES, "price.last": Decimal("130"), "volatility.active": Decimal("1.2")}), label="trailing-update"),
        ParityStep(
            make_context(values={**BASE_VALUES, "price.last": Decimal("128.25"), "volatility.active": Decimal("1.2")}),
            callbacks=(ExecutionCallback("DAILY_TAIL_INSURANCE_TRAILING_CLOSE", SimpleNamespace(group_complete=True, position_flat=True)),),
            label="trailing-close-and-fill-callback", reset_after=True,
        ),
    )
    result = compare_plugins(legacy, candidate, steps)
    assert result.equal, result.differences
    assert result.left_trace[0]["signals"][0]["direction"] == "BUY_INSURANCE"
    assert result.left_trace[1]["signals"][0]["direction"] == "UPDATE_TRAILING"
    assert result.left_trace[2]["signals"][0]["direction"] == "CLOSE"
    assert result.left_trace[-1]["plugin"]["state"]["is_active"] is False