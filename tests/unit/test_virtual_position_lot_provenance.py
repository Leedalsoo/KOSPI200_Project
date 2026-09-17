from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.position_provenance import PositionRole
from contracts.types import BrokerOrderCommand, ExecutionReport, OptionInstrumentIdentity
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

T0 = datetime(2026, 9, 17, 9, 0, 0)
IDENTITY = OptionInstrumentIdentity(
    instrument_id="OPT-C-100", symbol="OPT-C-100", expiry="202610",
    option_type="CALL", strike=Decimal("100"),
    contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
)


def fill(execution_id, side, qty, ts, *, strategy="S1", group="G1", leg="L1", client=None):
    command = BrokerOrderCommand(
        client_order_id=client or f"{group}-{leg}-{execution_id}",
        instrument_id=IDENTITY.instrument_id, side=side, quantity=qty,
        order_type="LIMIT", instrument_identity=IDENTITY, asset_type="OPTION",
        requested_price=Decimal("1"), strategy_id=strategy, group_id=group,
        leg_id=leg,
    )
    report = ExecutionReport(
        client_order_id=command.client_order_id, broker_order_id=f"B-{execution_id}",
        execution_id=execution_id, status="FILLED", filled_quantity=qty,
        remaining_quantity=0, execution_price=Decimal("1"), execution_timestamp=ts,
    )
    return command, report


def test_single_execution_preserves_full_provenance():
    store = VirtualPositionLotStore()
    c, r = fill("E1", "BUY", 5, T0)
    result = store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    lot = result.opened_lots[0]
    assert lot.remaining_quantity == 5
    assert (lot.strategy_id, lot.group_id, lot.leg_id, lot.execution_id) == ("S1", "G1", "L1", "E1")


def test_same_instrument_different_strategy_groups_remain_separate():
    store = VirtualPositionLotStore()
    for args in [("E1", "BUY", 2, T0, "S1", "G1", "L1"), ("E2", "BUY", 3, T0.replace(minute=1), "S2", "G2", "L2")]:
        c, r = fill(*args[:4], strategy=args[4], group=args[5], leg=args[6])
        store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    assert [(x.strategy_id, x.group_id, x.leg_id, x.remaining_quantity) for x in store.open_lots()] == [
        ("S1", "G1", "L1", 2), ("S2", "G2", "L2", 3)
    ]


def test_partial_close_reduces_original_lot_only():
    store = VirtualPositionLotStore()
    c1, r1 = fill("E1", "BUY", 5, T0)
    store.apply(c1, r1, run_id="RUN1", position_role=PositionRole.NONE)
    c2, r2 = fill("E2", "SELL", 2, T0.replace(minute=1))
    result = store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.NONE)
    assert store.open_lots()[0].execution_id == "E1"
    assert store.open_lots()[0].remaining_quantity == 3
    assert result.close_events[0].source_lot_execution_id == "E1"


def test_fifo_partial_close_consumes_oldest_lot_first():
    store = VirtualPositionLotStore()
    for eid, minute, qty in [("E1", 0, 2), ("E2", 1, 4)]:
        c, r = fill(eid, "BUY", qty, T0.replace(minute=minute))
        store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    c, r = fill("E3", "SELL", 3, T0.replace(minute=2))
    store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    lots = store.open_lots()
    assert [(x.execution_id, x.remaining_quantity) for x in lots] == [("E2", 3)]


def test_full_close_removes_open_lot_but_preserves_history():
    store = VirtualPositionLotStore()
    c1, r1 = fill("E1", "BUY", 2, T0)
    store.apply(c1, r1, run_id="RUN1", position_role=PositionRole.NONE)
    c2, r2 = fill("E2", "SELL", 2, T0.replace(minute=1))
    store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.NONE)
    assert store.open_lots() == ()
    assert any(getattr(x, "source_lot_execution_id", None) == "E1" for x in store.history())


def test_reversal_consumes_old_lot_then_opens_excess_with_new_provenance():
    store = VirtualPositionLotStore()
    c1, r1 = fill("E1", "BUY", 2, T0)
    store.apply(c1, r1, run_id="RUN1", position_role=PositionRole.NONE)
    c2, r2 = fill("E2", "SELL", 5, T0.replace(minute=1), strategy="S2", group="G2", leg="L2")
    store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.EVENT_INSURANCE)
    lot = store.open_lots()[0]
    assert (lot.execution_id, lot.strategy_id, lot.group_id, lot.leg_id, lot.remaining_quantity) == ("E2", "S2", "G2", "L2", 3)


def test_duplicate_execution_is_idempotent_and_conflict_is_rejected():
    store = VirtualPositionLotStore()
    c, r = fill("E1", "BUY", 2, T0)
    first = store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    second = store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)
    assert not first.idempotent and second.idempotent and len(store.open_lots()) == 1
    c2, r2 = fill("E1", "BUY", 3, T0)
    with pytest.raises(ValueError, match="DUPLICATE_CONFLICT"):
        store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.NONE)


def test_missing_provenance_fails_closed():
    store = VirtualPositionLotStore()
    c, r = fill("E1", "BUY", 1, T0)
    c = replace(c, strategy_id=None)
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        store.apply(c, r, run_id="RUN1", position_role=PositionRole.NONE)


def test_insurance_roles_are_explicit_and_separate_from_none():
    store = VirtualPositionLotStore()
    c1, r1 = fill("E1", "BUY", 1, T0)
    c2, r2 = fill("E2", "BUY", 1, T0.replace(minute=1))
    store.apply(c1, r1, run_id="RUN1", position_role=PositionRole.NONE)
    store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.EVENT_INSURANCE)
    assert [x.position_role for x in store.open_lots()] == [PositionRole.NONE, PositionRole.EVENT_INSURANCE]


def test_insurance_partial_close_preserves_role_and_original_provenance():
    store = VirtualPositionLotStore()
    c1, r1 = fill("E1", "BUY", 5, T0)
    store.apply(c1, r1, run_id="RUN1", position_role=PositionRole.OVERNIGHT_INSURANCE)
    c2, r2 = fill("E2", "SELL", 2, T0.replace(minute=1))
    store.apply(c2, r2, run_id="RUN1", position_role=PositionRole.NONE)
    lot = store.open_lots()[0]
    assert (lot.execution_id, lot.position_role, lot.remaining_quantity) == ("E1", PositionRole.OVERNIGHT_INSURANCE, 3)
