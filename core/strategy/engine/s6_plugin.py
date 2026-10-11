"""StrategyPlugin adapter for the opt-in S6 engine candidate; not production-registered."""
from __future__ import annotations

from typing import Sequence

from contracts.analytics import AnalyticsStatus
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.track6_daily_tail_insurance import Track6State
from core.strategy.engine.s6_engine import (
    INSURANCE_QTY, STRATEGY_ID, STRATEGY_VERSION, build_execution_plan,
    evaluate_s6, evaluate_take_profit_s6, execution_result_transition,
)
from core.strategy.engine.s6_rules import S6_RULES, S6Rules

class S6CandidatePlugin:
    strategy_id = STRATEGY_ID
    version = STRATEGY_VERSION

    def __init__(self, *, rules: S6Rules = S6_RULES, insurance_qty: int = INSURANCE_QTY) -> None:
        self.rules = rules
        self.insurance_qty = insurance_qty
        self.state = Track6State()
        self._exit_pending = False

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.last", "volatility.active", "volatility.base", "volatility.ratio",
                "portfolio.premium_spent",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track6State()
        self._exit_pending = False

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        decision = evaluate_s6(self.state, self._exit_pending, context, rules=self.rules, insurance_qty=self.insurance_qty)
        self.state = decision.state
        self._exit_pending = decision.exit_pending
        return decision.signals

    def evaluate_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        decision = evaluate_take_profit_s6(self.state, self._exit_pending, context, rules=self.rules, insurance_qty=self.insurance_qty)
        self.state = decision.state
        self._exit_pending = decision.exit_pending
        return decision.signals

    def on_execution_result(self, purpose: str, result: object) -> None:
        self.state, self._exit_pending = execution_result_transition(self.state, self._exit_pending, purpose, result)

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        return build_execution_plan(self.state, group_id, insurance_qty=self.insurance_qty)