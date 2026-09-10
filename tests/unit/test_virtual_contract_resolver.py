from decimal import Decimal

import pytest

from contracts.virtual_contract_resolver import (
    VirtualContractMapping,
    VirtualContractResolutionError,
    VirtualContractResolver,
)


class FakeRegistry:
    def __init__(self, values):
        self.values = values

    def get_contract_identity(self, shrn_iscd):
        return self.values.get(shrn_iscd)


def test_exact_mapping_resolves_authoritative_identity():
    identity = object()
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry({"KR7001": identity}),
    )
    assert resolver.resolve("SCN-1") is identity


def test_missing_mapping_fails_closed():
    resolver = VirtualContractResolver({}, FakeRegistry({}))
    with pytest.raises(VirtualContractResolutionError, match="MAPPING_NOT_FOUND"):
        resolver.resolve("UNKNOWN")


def test_missing_registry_identity_fails_closed():
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry({}),
    )
    with pytest.raises(VirtualContractResolutionError, match="IDENTITY_NOT_FOUND"):
        resolver.resolve("SCN-1")


def test_blank_key_fails_closed():
    resolver = VirtualContractResolver({}, FakeRegistry({}))
    with pytest.raises(VirtualContractResolutionError, match="KEY_REQUIRED"):
        resolver.resolve("   ")


def test_invalid_mapping_is_rejected_at_construction():
    with pytest.raises(VirtualContractResolutionError, match="INVALID_SCENARIO"):
        VirtualContractResolver(
            {"SCN-1": VirtualContractMapping("OTHER", "KR7001")},
            FakeRegistry({}),
        )
