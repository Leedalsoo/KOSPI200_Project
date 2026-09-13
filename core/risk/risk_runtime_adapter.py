"""Non-invasive Standard Risk input boundary for Runtime integration."""
from dataclasses import dataclass
from typing import Any, Protocol

from contracts.types import AccountSnapshot
from core.risk.risk_input import RiskAccountInput, RiskPositionInput, account_snapshot_to_risk_input
from core.risk.risk_position import position_manager_to_risk_input


class RiskCompatibleOrderCommand(Protocol):
    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: Any
    tag_id: str
    def get_instrument_key(self) -> str: ...


@dataclass(frozen=True)
class RiskRuntimeInputs:
    command: RiskCompatibleOrderCommand
    account: RiskAccountInput
    positions: RiskPositionInput


def validate_risk_order_command(command: Any) -> RiskCompatibleOrderCommand:
    required = ("client_order_id", "track_id", "qty", "price", "side", "tag_id")
    missing = [name for name in required if not hasattr(command, name)]
    if missing or not callable(getattr(command, "get_instrument_key", None)):
        raise TypeError("RISK_ORDER_COMMAND_FIELDS_REQUIRED: " + ",".join(missing or ["get_instrument_key"]))
    return command


def build_risk_runtime_inputs(command: Any, account_snapshot: AccountSnapshot, position_manager: Any) -> RiskRuntimeInputs:
    return RiskRuntimeInputs(
        command=validate_risk_order_command(command),
        account=account_snapshot_to_risk_input(account_snapshot),
        positions=position_manager_to_risk_input(position_manager),
    )
