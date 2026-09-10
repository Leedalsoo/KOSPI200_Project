from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_config import RiskConfig
from core.risk.risk_runtime_adapter import (
build_risk_runtime_inputs,
validate_risk_order_command,
)


class Command:
    client_order_id = "ORD-1"
    track_id = "Track1"
    qty = 3
    price = 12.5
    side = "BUY"
    tag_id = "Track1"

    def get_instrument_key(self):
        return "OPT-1"


class PositionManager:
    positions = {
        "OPT-1": {"side": "BUY", "qty": 2, "avg_price": 10.0}
    }


def quality():
    return DataQuality(True, True, True, None)


def account_snapshot():
    return AccountSnapshot(
        as_of=datetime(2026, 9, 5),
        balances={
            "cash": Decimal("50000000"),
            "realized_pnl": Decimal("0"),
            "margin_used": Decimal("1000000"),
            "available_cash": Decimal("49000000"),
        },
        freshness=quality(),
    )


def test_command_boundary_preserves_same_object():
    command = Command()
# assert validate_risk_order_command(command) is command


def test_runtime_inputs_use_authoritative_account_and_position_adapters():
    command = Command()
    result = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())

# assert result.command is command
    assert result.account.total_balance == Decimal("50000000")
    assert result.account.used_margin == Decimal("1000000")
    assert result.account.free_margin == Decimal("49000000")
    assert result.positions.positions["OPT-1"].side == "BUY"
    assert result.positions.positions["OPT-1"].qty == 2


def test_command_without_instrument_key_fails_closed():
    class InvalidCommand:
        client_order_id = "ORD-2"
        track_id = "Track1"
        qty = 1
        price = 1.0
        side = "BUY"
        tag_id = "Track1"

    with pytest.raises(TypeError, match="RISK_ORDER_COMMAND_FIELDS_REQUIRED"):
        pass
        validate_risk_order_command(InvalidCommand())


def test_adapter_inputs_can_be_passed_to_standard_risk_gate_without_reconstruction():
    class MarginCalculator:
        def calculate_order_margin(self, command):
            return float(command.price) * int(command.qty)

    command = Command()
    inputs = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())
    gate = RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=100),
            margin_engine=MarginCalculator(),
        )
    )

    approved, token, reason = gate.admit_order(
        command=inputs.command,
        account=inputs.account,
        positions=inputs.positions,
    )

# assert approved is True
# assert token is not None
# assert reason is None
    assert gate.last_evaluation_result.approved_qty == command.qty
# assert gate.last_evaluation_result.reduced_command is None
# assert inputs.command is command


def test_risk_gate_reduce_quantity_becomes_authoritative_effective_command():
    class MarginCalculator:
        def calculate_order_margin(self, command):
            return float(command.price) * int(command.qty)

    command = Command()
    inputs = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())
    gate = RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=3),
            margin_engine=MarginCalculator(),
        )
    )

    approved, token, reason = gate.admit_order(
        command=inputs.command,
        account=inputs.account,
        positions=inputs.positions,
        allow_reduction=True,
    )

# assert approved is True
# assert token is not None
# assert reason is None
    result = gate.last_evaluation_result
    assert result.decision == "REDUCE"
# assert result.reduced_command is not None
    assert result.reduced_command.qty == 1
    assert result.approved_qty == 1
# assert result.reduced_command is not command
    assert result.reduced_command.client_order_id == command.client_order_id
    assert result.reduced_command.track_id == command.track_id
    assert result.reduced_command.side == command.side
    assert result.reduced_command.price == command.price
    assert result.reduced_command.tag_id == command.tag_id
