"""Test Execution Path Composition — 테스트 사양 문서.

import pytest
from application.composition.execution_path_composition import (
RuntimeTransportComposition, StandardOrderIntentComposition,
create_runtime_transport_composition, create_standard_order_intent_composition,
)
class X: pass
def test_runtime_transport_requires_explicit_authoritative_dependencies():
with pytest.raises(ValueError, match='RUNTIME_TRANSPORT_DEPENDENCY_REQUIRED'):
pass
RuntimeTransportComposition(None, X(), X(), X(), X())
def test_standard_order_intent_requires_real_suppliers():
with pytest.raises(ValueError, match='STANDARD_ORDER_INTENT_DEPENDENCY_REQUIRED'):
pass
StandardOrderIntentComposition(None, X(), X(), X())
def test_two_composition_roots_are_explicit_and_independent():
runtime = create_runtime_transport_composition(
strategy_runtime=X(), strategy_to_decision=X(), decision_to_command=X(),
risk_gate=X(), account_snapshot=X(), position_source=X(),
order_router=X(), broker_command=X(),
)
standard = create_standard_order_intent_composition(
signal_identity_provider=X(), position_execution_decision_provider=X(),
order_intent_factory=X(), order_intent_adapter=X(),
)
assert runtime.risk_context.order_router is not None
assert standard.position_execution_decision_provider is not None
"""
