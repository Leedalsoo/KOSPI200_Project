"""FRESH-06 real bridge execution with a fake broker; offline only."""
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
from types import MethodType

import pytest

from application.composition import virtual_multi_leg_execution as bridge_module
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity


class FakeBroker:
    def __init__(self):
        self.submissions = []

    def submit(self, command, **kwargs):
        self.submissions.append(command)
        raise AssertionError("preflight test must not reach fake broker")


class _Owner:
    def __init__(self, vssf_runtime):
        self.vssf_runtime = vssf_runtime

    def execute(self):
        pass


def test_fresh06_bad_second_leg_raises_before_any_fake_broker_submit(monkeypatch):
    """Actual execute() path; missing quote is a real supported preflight failure."""
    broker = FakeBroker()
    order_book = SimpleNamespace(update_bid_ask=lambda *args, **kwargs: None)
    vssf = SimpleNamespace(account=SimpleNamespace(realized_pnl=Decimal("0")), order_book=order_book)
    owner = _Owner(vssf)
    account = SimpleNamespace(snapshot=lambda: object())
    market = SimpleNamespace(option_quotes={
        ("CALL", 100.0, "20261029"): {"bid": "1.0", "ask": "1.1", "contract_multiplier": "100"}
    })
    bundle = SimpleNamespace(account=account, position=object(), market=market,
        broker=broker, execution=SimpleNamespace(_authoritative_execute=owner.execute))
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.bundle = bundle
    bridge.option_master = SimpleNamespace(get_contract_identity=lambda _instrument_id: SimpleNamespace(contract_multiplier=Decimal("100")))
    bridge.groups = {}
    bridge.freshness_verdict_provider = None
    bridge.command_context = SimpleNamespace(build_command=lambda command: command)
    identities = {
        "call": OptionInstrumentIdentity("OPT-C", "OPT-C", "20261029", "CALL", Decimal("100"), Decimal("100"), "TEST_FIXTURE"),
        "put": OptionInstrumentIdentity("OPT-P", "OPT-P", "20261029", "PUT", Decimal("100"), Decimal("100"), "TEST_FIXTURE"),
    }
    bridge.identity_for_leg = MethodType(lambda self, plan, leg: identities[leg.leg_id], bridge)
    monkeypatch.setattr(bridge_module, "account_snapshot_to_risk_input", lambda _snapshot: object())
    monkeypatch.setattr(bridge_module, "position_manager_to_risk_input", lambda _position: object())
    plan = MultiLegExecutionPlan("fresh06-group", "S1", (
        ExecutionLeg("call", "BUY", 1, instrument_identity=identities["call"]),
        ExecutionLeg("put", "BUY", 1, instrument_identity=identities["put"]),
    ))

    with pytest.raises(ValueError, match="MULTI_LEG_GROUP_PREFLIGHT_QUOTE_REQUIRED"):
        bridge.execute(plan)
    assert broker.submissions == []
