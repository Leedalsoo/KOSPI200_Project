"""Test Live Runtime Tick Transport Production Boundary — test specification.

import pytest
from application.composition import live_runtime_production_factory as production_factory
from application.composition import live_runtime_risk_state_factory as risk_factory
class Providers:
def __init__(self, account_provider, position_provider):
self.account_snapshot_provider = account_provider
self.position_source_provider = position_provider
class Transport:
def __init__(self, runtime, s2d, d2c, gate, router, broker_command, account, position):
self.strategy_runtime = runtime
self.strategy_to_decision = s2d
self.decision_to_command = d2c
self.risk_gate = gate
self.risk_context = type("Context", (), {"order_router": router})()
self.account_snapshot = account
self.position_source = position
class Entry:
def __init__(self, runtime, s2d, d2c, gate, account_provider, position_provider):
self.runtime = runtime
self.strategy_to_decision = s2d
self.decision_to_command = d2c
self.risk_gate = gate
self.account_snapshot_provider = account_provider
self.position_source_provider = position_provider
def test_tick_transport_shares_strategy_decision_risk_and_provider_graph(monkeypatch):
runtime = object(); s2d = object(); d2c = object(); gate = object()
router = object(); broker_command = object()
account_provider = lambda: "account-current"
position_provider = lambda: "position-current"
providers = Providers(account_provider, position_provider)
captured = {}
def fake_transport_composition(**kwargs):
captured["transport_kwargs"] = kwargs
return Transport(
kwargs["strategy_runtime"], kwargs["strategy_to_decision"],
kwargs["decision_to_command"], kwargs["risk_gate"],
kwargs["order_router"], kwargs["broker_command"],
kwargs["account_snapshot"], kwargs["position_source"],
)
monkeypatch.setattr(risk_factory, "create_runtime_transport_composition", fake_transport_composition)
monkeypatch.setattr(risk_factory, "LiveRuntimeTickEntry", Entry)
monkeypatch.setattr(risk_factory, "route_from_runtime_authoritative_sources", lambda *a, **k: None)
transport, entry = risk_factory.create_live_runtime_tick_transport(
strategy_runtime=runtime, strategy_to_decision=s2d,
decision_to_command=d2c, risk_gate=gate, order_router=router,
broker_command=broker_command, risk_state_providers=providers,
)
assert transport.strategy_runtime is runtime
assert transport.strategy_to_decision is s2d
assert transport.decision_to_command is d2c
assert transport.risk_gate is gate
assert transport.account_snapshot == "account-current"
assert transport.position_source == "position-current"
assert entry.runtime is runtime
assert entry.strategy_to_decision is s2d
assert entry.decision_to_command is d2c
assert entry.risk_gate is gate
assert entry.account_snapshot_provider is account_provider
assert entry.position_source_provider is position_provider
assert captured["transport_kwargs"]["account_snapshot"] == "account-current"
assert captured["transport_kwargs"]["position_source"] == "position-current"
def test_tick_transport_requires_provider_bundle():
with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED"):
pass
risk_factory.create_live_runtime_tick_transport(
strategy_runtime=object(), strategy_to_decision=object(),
decision_to_command=object(), risk_gate=object(),
order_router=object(), broker_command=object(),
risk_state_providers=None,
)
def test_production_factory_accepts_the_same_injected_tick_graph(monkeypatch):
runtime = object(); s2d = object(); d2c = object(); gate = object()
account_provider = lambda: "account"; position_provider = lambda: "position"
providers = Providers(account_provider, position_provider)
tick_entry = Entry(runtime, s2d, d2c, gate, account_provider, position_provider)
deps = {name: object() for name in (
"market", "broker", "account", "position", "reconciler", "transport",
"execution_adapter", "correlation_provider", "order_state_machine",
"execution_event_deduplicator", "safety_policy")}
aggregate = object()
deps["position_aggregate"] = aggregate
deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
deps["tick_entry"] = tick_entry; deps["risk_state_providers"] = providers
deps["runtime_transport"] = Transport(runtime, s2d, d2c, gate, object(), object(), "account", "position")
captured = {}
class Bootstrap: recovery_service = object()
monkeypatch.setattr(production_factory, "create_live_runtime_bootstrap", lambda **kwargs: (captured.update(kwargs) or Bootstrap()))
monkeypatch.setattr(production_factory, "build_live_bundle_from_components", lambda **kwargs: object())
monkeypatch.setattr(production_factory, "create_live_runtime_controller", lambda *, live_builder: object())
monkeypatch.setattr(production_factory, "LiveRuntimeLifecycleCoordinator", lambda *, controller, bootstrap: object())
production_factory.create_live_runtime_lifecycle_coordinator(**deps)
assert captured["tick_entry"] is tick_entry
assert captured["runtime_transport"] is deps["runtime_transport"]
def test_production_factory_does_not_replace_injected_tick_entry_or_transport(monkeypatch):
deps = {name: object() for name in (
"market", "broker", "account", "position", "reconciler", "transport",
"execution_adapter", "correlation_provider", "order_state_machine",
"execution_event_deduplicator", "safety_policy")}
aggregate = object()
deps["position_aggregate"] = aggregate
deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
account_provider = lambda: "account"; position_provider = lambda: "position"
deps["risk_state_providers"] = Providers(account_provider, position_provider)
entry = Entry(object(), object(), object(), object(), account_provider, position_provider)
deps["tick_entry"] = entry
deps["runtime_transport"] = Transport(
entry.runtime, entry.strategy_to_decision, entry.decision_to_command,
entry.risk_gate, object(), object(), "account", "position")
captured = {}
class Bootstrap: recovery_service = object()
monkeypatch.setattr(production_factory, "create_live_runtime_bootstrap", lambda **kwargs: (captured.update(kwargs) or Bootstrap()))
monkeypatch.setattr(production_factory, "build_live_bundle_from_components", lambda **kwargs: object())
monkeypatch.setattr(production_factory, "create_live_runtime_controller", lambda *, live_builder: object())
monkeypatch.setattr(production_factory, "LiveRuntimeLifecycleCoordinator", lambda *, controller, bootstrap: object())
production_factory.create_live_runtime_lifecycle_coordinator(**deps)
assert captured["tick_entry"] is entry
assert captured["runtime_transport"] is deps["runtime_transport"]
"""
