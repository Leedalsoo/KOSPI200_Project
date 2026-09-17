"""Explicit ownership boundary for Runtime transport and Standard OrderIntent execution seams."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext

@dataclass(frozen=True)
class RuntimeTransportComposition:
    strategy_runtime: Any
    strategy_to_decision: Any
    decision_to_command: Any
    risk_gate: Any
    risk_context: RiskRouterContext

    def __post_init__(self) -> None:
        required = {
            'strategy_runtime': self.strategy_runtime,
            'strategy_to_decision': self.strategy_to_decision,
            'decision_to_command': self.decision_to_command,
            'risk_gate': self.risk_gate,
            'risk_context': self.risk_context,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("RUNTIME_TRANSPORT_DEPENDENCY_REQUIRED:" + ",".join(missing))

@dataclass(frozen=True)
class StandardOrderIntentComposition:
    signal_identity_provider: Any
    position_execution_decision_provider: Any
    order_intent_factory: Any
    order_intent_adapter: Any

    def __post_init__(self) -> None:
        required = {
            'signal_identity_provider': self.signal_identity_provider,
            'position_execution_decision_provider': self.position_execution_decision_provider,
            'order_intent_factory': self.order_intent_factory,
            'order_intent_adapter': self.order_intent_adapter,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("STANDARD_ORDER_INTENT_DEPENDENCY_REQUIRED:" + ",".join(missing))

def create_runtime_transport_composition(*, strategy_runtime: Any, strategy_to_decision: Any, decision_to_command: Any, risk_gate: Any, account_snapshot: Any, position_source: Any, order_router: Any, broker_command: Any) -> RuntimeTransportComposition:
    context = RiskRouterContext(account_snapshot, position_source, order_router, broker_command)
    return RuntimeTransportComposition(strategy_runtime, strategy_to_decision, decision_to_command, risk_gate, context)

def create_standard_order_intent_composition(*, signal_identity_provider: Any, position_execution_decision_provider: Any, order_intent_factory: Any, order_intent_adapter: Any) -> StandardOrderIntentComposition:
    return StandardOrderIntentComposition(signal_identity_provider, position_execution_decision_provider, order_intent_factory, order_intent_adapter)
