from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance
from verification.strategy_parity.harness import ParityStep, compare_plugins, run_trace
from verification.strategy_parity.scenarios import BASE_VALUES, active_strategy, case_contexts, make_context


def _clone_legacy(template):
    plugin = Track6DailyTailInsurance()
    plugin.state = replace(template.state)
    plugin._exit_pending = template._exit_pending
    return plugin


def test_old_implementation_against_itself_has_zero_diff():
    for label, template, context, expected in case_contexts():
        left = _clone_legacy(template)
        right = _clone_legacy(template)
        method = "evaluate_take_profit" if label == "take_profit_suppressed_at_15_12" else "evaluate"
        result = compare_plugins(left, right, (ParityStep(context, label=label, method=method),))
        assert result.equal, (label, result.differences)
        observed = tuple(signal["direction"] for signal in result.left_trace[0]["signals"])
        assert observed == expected, (label, observed, expected)


def test_same_input_twice_from_same_initial_state_is_deterministic():
    for label, template, context, _expected in case_contexts():
        traces = []
        for _ in range(2):
            plugin = _clone_legacy(template)
            method = "evaluate_take_profit" if label == "take_profit_suppressed_at_15_12" else "evaluate"
            traces.append(run_trace(plugin, (ParityStep(context, label=label, method=method),)))
        assert traces[0] == traces[1], label


def test_harness_detects_all_five_temporary_mutation_types():
    class Mutated(Track6DailyTailInsurance):
        mutation = ""

        def evaluate(self, context):
            if self.mutation == "cutoff_plus_one_second" and context.analytics.as_of.strftime("%H:%M:%S") == "15:14:59":
                context = replace(context, analytics=replace(context.analytics, as_of=context.analytics.as_of + timedelta(seconds=1)))
            before = self.state
            signals = tuple(super().evaluate(context))
            if self.mutation == "state_field_not_updated" and any(s.direction == "UPDATE_TRAILING" for s in signals):
                self.state = before
            if self.mutation == "proposal_tag_changed":
                signals = tuple(replace(s, execution_proposal=replace(s.execution_proposal, tag_id="MUTATED_TAG")) if s.execution_proposal else s for s in signals)
            if self.mutation == "update_trailing_condition_changed":
                signals = tuple(s for s in signals if s.direction != "UPDATE_TRAILING")
            return signals

    variants = (
        ("ratio_088_to_089", active_strategy(high="15", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.32")})),
        ("cutoff_plus_one_second", active_strategy(), make_context("15:14:59")),
        ("state_field_not_updated", active_strategy(), make_context(values={**BASE_VALUES, "price.last": Decimal("102"), "volatility.active": Decimal("1.2")})),
        ("proposal_tag_changed", Track6DailyTailInsurance(), make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.3")})),
        ("update_trailing_condition_changed", active_strategy(), make_context(values={**BASE_VALUES, "price.last": Decimal("102"), "volatility.active": Decimal("1.2")})),
    )
    for mutation, reference, context in variants:
        if mutation == "ratio_088_to_089":
            import sys
            import types
            from pathlib import Path
            from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput, Track6State

            source_path = Path("core/strategy/track6_daily_tail_insurance.py")
            source = source_path.read_text(encoding="utf-8").replace('Decimal("0.88")', 'Decimal("0.89")')
            module = types.ModuleType("_temporary_track6_ratio_089_variant")
            sys.modules[module.__name__] = module
            exec(compile(source, str(source_path), "exec"), module.__dict__)
            module.Track6ExecutionInput = Track6ExecutionInput
            module.Track6State = Track6State
            mutant = module.Track6DailyTailInsurance()
        else:
            mutant = Mutated()
            mutant.mutation = mutation
        mutant.state = replace(reference.state)
        mutant._exit_pending = reference._exit_pending
        result = compare_plugins(_clone_legacy(reference), mutant, (ParityStep(context, label=mutation),))
        assert not result.equal, mutation
        assert result.differences, mutation