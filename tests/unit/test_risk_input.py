from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import AccountSnapshot, DataQuality, PositionSnapshot
from core.risk.risk_input import (
RiskPositionInput,
account_snapshot_to_risk_input,
position_snapshot_to_risk_input,
)


def quality():
    return DataQuality(True, True, True, None)


def test_account_snapshot_maps_existing_virtual_account_fields():
    snapshot = AccountSnapshot(
        as_of=datetime.now(timezone.utc),
        balances={
            "cash": Decimal("50000000"),
            "margin_used": Decimal("1000000"),
            "realized_pnl": Decimal("-100000"),
            "available_cash": Decimal("49000000"),
        },
        freshness=quality(),
    )
    result = account_snapshot_to_risk_input(snapshot)
    assert result.total_balance == Decimal("50000000")
    assert result.realized_pnl == Decimal("-100000")
    assert result.used_margin == Decimal("1000000")
    assert result.free_margin == Decimal("49000000")


def test_account_snapshot_missing_required_field_fails_closed():
    snapshot = AccountSnapshot(
        as_of=datetime.now(timezone.utc),
        balances={"cash": Decimal("1")},
        freshness=quality(),
    )
    with pytest.raises(ValueError, match="RISK_ACCOUNT_FIELDS_REQUIRED"):
        account_snapshot_to_risk_input(snapshot)


def test_position_snapshot_does_not_invent_side():
    snapshot = PositionSnapshot(
        as_of=datetime.now(timezone.utc),
        positions={"OPTION_X": Decimal("2")},
        freshness=quality(),
    )
    with pytest.raises(ValueError, match="RISK_POSITION_SIDE_REQUIRED"):
        position_snapshot_to_risk_input(snapshot)
