from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.types import OrderIntent
from core.risk.multi_leg_risk import MultiLegRiskError, admit_multi_leg_intents
from core.risk.risk_engine import RiskGate
from core.risk.risk_input import RiskAccountInput, RiskPositionInput


@dataclass
class Command:
    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: str
    tag_id: str

    def get_instrument_key(self) -> str:
        return self.client_order_id


class Margin:
    def calculate_order_margin(self, command):
        return float(command.qty) * 10


def account():
    return RiskAccountInput(
        total_balance=Decimal("100000"),
        free_margin=Decimal("100000"),
        used_margin=Decimal("0"),
        realized_pnl=Decimal("0"),
    )


def intent(client_id: str, leg_id: str, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_id,
        instrument_id=f"I-{leg_id}",
        side="BUY",
        quantity=qty,
        intent_type="ENTRY",
        strategy_id="track2_asymmetric_trap",
        asset_type="OPTION",
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        track_id="track2_asymmetric_trap",
        tag_id="LEG",
        group_id="G-2",
        leg_id=leg_id,
    )


def gate():
    from core.risk.risk_config import RiskConfig
    return RiskGate(__import__("core.risk.risk_engine", fromlist=["RiskEngine"]).RiskEngine(
        config=RiskConfig(max_order_qty=50), margin_engine=Margin()
    ))


def factory(i):
    return Command(i.client_order_id, i.track_id or "", i.quantity, float(i.requested_price or 0), i.side, i.tag_id or "")


def test_all_legs_receive_independent_tokens():
    g = gate()
    result = admit_multi_leg_intents(
        [intent("O1", "put"), intent("O2", "call"), intent("O3", "long_put"), intent("O4", "long_call")],
        risk_gate=g, account=account(), command_factory=factory,
    )
    assert result.group_id == "G-2"
    assert set(result.tokens) == {"O1", "O2", "O3", "O4"}
    assert result.approved_quantities == {"O1": 1, "O2": 1, "O3": 1, "O4": 1}


def test_deny_stops_later_legs():
    g = gate()
    calls = []
    def deny_factory(i):
        calls.append(i.client_order_id)
        return Command(i.client_order_id, "t", 999 if i.client_order_id == "O2" else 1, 1.0, "BUY", "LEG")
    with pytest.raises(MultiLegRiskError, match="EXCEEDED_MAX_ORDER_QTY"):
        admit_multi_leg_intents([intent("O1", "a"), intent("O2", "b"), intent("O3", "c")], risk_gate=g, account=account(), command_factory=deny_factory)
    assert calls == ["O1", "O2"]


def test_client_order_id_provenance_mismatch_fails_closed():
    g = gate()
    with pytest.raises(MultiLegRiskError, match="CLIENT_ORDER_ID_PROVENANCE_MISMATCH"):
        admit_multi_leg_intents([intent("O1", "a")], risk_gate=g, account=account(), command_factory=lambda i: Command("OTHER", "t", 1, 1.0, "BUY", "LEG"))


def test_reduced_quantity_provenance_mismatch_fails_closed():
    class FakeGate:
        last_evaluation_result = SimpleNamespace(
            approved_qty=2,
            decision="REDUCE",
            reduced_command=SimpleNamespace(qty=1),
            token=object(),
        )
        def admit_order(self, *args, **kwargs):
            return True, self.last_evaluation_result.token, None
    with pytest.raises(MultiLegRiskError, match="REDUCED_QUANTITY_PROVENANCE_MISMATCH"):
        admit_multi_leg_intents([intent("O1", "a")], risk_gate=FakeGate(), account=account(), command_factory=factory)
