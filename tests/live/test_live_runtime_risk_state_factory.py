import pytest
from application.composition.live_runtime_risk_state_factory import create_live_runtime_risk_state_providers

class Account:
    def snapshot(self): return "authoritative-account"
class Position:
    def snapshot(self): return {}

def test_authoritative_account_and_position_are_exposed_without_synthesis():
    p=create_live_runtime_risk_state_providers(account=Account(), position_source=Position())
    assert p.account_snapshot_provider()=="authoritative-account"
    assert p.position_source_provider().snapshot()=={}

def test_missing_account_fails_closed():
    with pytest.raises(ValueError, match="LIVE_ACCOUNT_PROVIDER_REQUIRED"):
        create_live_runtime_risk_state_providers(account=None, position_source=Position())
