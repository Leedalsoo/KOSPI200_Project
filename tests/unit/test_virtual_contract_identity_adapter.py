import pytest

from application.composition.virtual_contract_identity_adapter import (
    VirtualContractIdentityResolverAdapter,
)
from contracts.virtual_contract_resolver import (
    VirtualContractMapping,
    VirtualContractResolutionError,
    VirtualContractResolver,
)
from environments.high_speed.contract_identity import ReplayEvent, ScenarioEvent


class FakeRegistry:
    def __init__(self, values):
        self.values = values

    def get_contract_identity(self, shrn_iscd):
        return self.values.get(shrn_iscd)


def make_adapter(values=None):
    values = values or {}
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry(values),
    )
    return VirtualContractIdentityResolverAdapter(resolver)


def test_scenario_event_resolves_authoritative_identity():
    identity = object()
    adapter = make_adapter({"KR7001": identity})
    event = ScenarioEvent(1, "tick", {"price": 100}, "SCN-1")
    assert adapter.resolve_event(event) is identity


def test_replay_event_resolves_authoritative_identity():
    from datetime import datetime

    identity = object()
    adapter = make_adapter({"KR7001": identity})
    event = ReplayEvent(1, datetime(2026, 1, 1), {"price": 100}, "SCN-1")
    assert adapter.resolve_event(event) is identity


@pytest.mark.parametrize("event", [
    ScenarioEvent(1, "tick", {}, None),
    ScenarioEvent(1, "tick", {}, "   "),
])
def test_missing_or_blank_key_fails_closed(event):
    adapter = make_adapter({"KR7001": object()})
    with pytest.raises(VirtualContractResolutionError, match="KEY_REQUIRED"):
        adapter.resolve_event(event)


def test_unknown_mapping_fails_closed_through_adapter():
    adapter = make_adapter({"KR7001": object()})
    event = ScenarioEvent(1, "tick", {}, "UNKNOWN")
    with pytest.raises(VirtualContractResolutionError, match="MAPPING_NOT_FOUND"):
        adapter.resolve_event(event)


def test_registry_miss_fails_closed_through_adapter():
    adapter = make_adapter({})
    event = ScenarioEvent(1, "tick", {}, "SCN-1")
    with pytest.raises(VirtualContractResolutionError, match="IDENTITY_NOT_FOUND"):
        adapter.resolve_event(event)
