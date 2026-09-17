from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from contracts.types import AccountSnapshot, PositionSnapshot


@dataclass(frozen=True)
class RiskAccountInput:
    total_balance: Decimal
    realized_pnl: Decimal
    used_margin: Decimal
    free_margin: Decimal


@dataclass(frozen=True)
class RiskPosition:
    side: str
    qty: int


@dataclass(frozen=True)
class RiskPositionInput:
    positions: Mapping[str, RiskPosition]


def account_snapshot_to_risk_input(snapshot: AccountSnapshot) -> RiskAccountInput:
    required = ("cash", "realized_pnl", "margin_used", "available_cash")
    missing = [key for key in required if key not in snapshot.balances]
    if missing:
        raise ValueError(f"RISK_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}")
    return RiskAccountInput(
        total_balance=Decimal(snapshot.balances["cash"]),
        realized_pnl=Decimal(snapshot.balances["realized_pnl"]),
        used_margin=Decimal(snapshot.balances["margin_used"]),
        free_margin=Decimal(snapshot.balances["available_cash"]),
    )


def position_snapshot_to_risk_input(snapshot: PositionSnapshot) -> RiskPositionInput:
    raise ValueError("RISK_POSITION_SIDE_REQUIRED")
