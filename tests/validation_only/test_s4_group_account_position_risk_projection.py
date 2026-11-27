from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.validation_only_position_lot_risk_projection import (
    project_position_lot_risk_exposure,
)


def _lot(*, run: str, strategy: str, group: str, side: str, qty: int):
    return SimpleNamespace(
        run_id=run,
        execution_id=f"exec-{run}-{strategy}-{group}-{side}-{qty}",
        strategy_id=strategy,
        group_id=group,
        instrument_id="SYNTHETIC:MINI:SHARED",
        side=side,
        remaining_quantity=qty,
        contract_multiplier=Decimal("50000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def test_group_and_account_exposure_keep_shared_instrument_ownership_separate():
    lots = (
        _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=2),
        _lot(run="run-a", strategy="S4", group="group-b", side="SELL", qty=1),
        _lot(run="run-b", strategy="S3", group="group-a", side="BUY", qty=3),
    )

    projection = project_position_lot_risk_exposure(lots)

    assert projection.group_positions[("run-a", "S4", "group-a", "SYNTHETIC:MINI:SHARED")].net_signed_qty == -2
    assert projection.group_positions[("run-a", "S4", "group-b", "SYNTHETIC:MINI:SHARED")].net_signed_qty == -1
    assert projection.group_positions[("run-b", "S3", "group-a", "SYNTHETIC:MINI:SHARED")].net_signed_qty == 3
    account = projection.account_positions["SYNTHETIC:MINI:SHARED"]
    assert account.net_signed_qty == 0
    assert account.gross_long_qty == 3
    assert account.gross_short_qty == 3


def test_same_group_name_does_not_merge_different_run_or_strategy_ownership():
    projection = project_position_lot_risk_exposure((
        _lot(run="run-a", strategy="S4", group="same", side="SELL", qty=2),
        _lot(run="run-b", strategy="S4", group="same", side="SELL", qty=4),
    ))

    assert len(projection.group_positions) == 2
    assert projection.account_positions["SYNTHETIC:MINI:SHARED"].gross_short_qty == 6


@pytest.mark.parametrize("field,value", [("run_id", ""), ("strategy_id", ""), ("group_id", ""), ("instrument_id", "")])
def test_missing_ownership_or_instrument_identity_is_rejected(field, value):
    lot = _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=1)
    setattr(lot, field, value)
    with pytest.raises(ValueError, match="POSITION_LOT_RISK_PROJECTION_IDENTITY_REQUIRED"):
        project_position_lot_risk_exposure((lot,))


def test_inconsistent_contract_provenance_for_same_instrument_is_rejected():
    first = _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=1)
    second = _lot(run="run-b", strategy="S3", group="group-b", side="BUY", qty=1)
    second.contract_multiplier = Decimal("10000")

    with pytest.raises(ValueError, match="POSITION_LOT_RISK_PROJECTION_CONTRACT_PROVENANCE_MISMATCH"):
        project_position_lot_risk_exposure((first, second))




def test_fixture_group_cap_is_evaluated_per_group_not_shared_across_groups():
    projection = project_position_lot_risk_exposure((
        _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=2),
        _lot(run="run-a", strategy="S4", group="group-b", side="SELL", qty=1),
    ))
    fixture_only_group_cap = 2

    group_a = projection.group_positions[("run-a", "S4", "group-a", "SYNTHETIC:MINI:SHARED")]
    group_b = projection.group_positions[("run-a", "S4", "group-b", "SYNTHETIC:MINI:SHARED")]
    assert abs(group_a.net_signed_qty) == fixture_only_group_cap
    assert abs(group_b.net_signed_qty) < fixture_only_group_cap
    assert projection.account_positions["SYNTHETIC:MINI:SHARED"].gross_short_qty == 3


def test_duplicate_execution_identity_is_rejected_instead_of_double_counted():
    first = _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=1)
    duplicate = _lot(run="run-a", strategy="S4", group="group-a", side="SELL", qty=1)
    duplicate.execution_id = first.execution_id

    with pytest.raises(ValueError, match="POSITION_LOT_RISK_PROJECTION_DUPLICATE_EXECUTION_ID"):
        project_position_lot_risk_exposure((first, duplicate))
