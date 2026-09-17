from datetime import datetime
from decimal import Decimal
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.types import OptionInstrumentIdentity
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
T0 = datetime(2026, 1, 1, 9, 0)
ID = OptionInstrumentIdentity("OPT-C-100", "OPT-C-100", "202601", "CALL", Decimal("100"), Decimal("250000"), "OPTION_MASTER")
def lot(execution, side, qty, ts=T0, strategy="S1", group="G1", leg="L1", role=PositionRole.NONE):
    return PositionLotProvenance("RUN1", "OPT-C-100", strategy, group, leg, f"{group}-{leg}-{execution}", execution, side, qty, qty, ts, ID, Decimal("250000"), "OPTION_MASTER", role)
def test_single_lot_preserves_provenance():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 3))
    assert store.open_lots()[0].strategy_id == "S1"; assert store.open_lots()[0].remaining_quantity == 3
def test_cross_strategy_lots_are_not_merged():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 2)); store.apply_execution(lot("E2", "BUY", 4, strategy="S2", group="G2"))
    assert [(x.strategy_id, x.remaining_quantity) for x in store.open_lots()] == [("S1", 2), ("S2", 4)]
def test_partial_close_fifo():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 5)); store.apply_execution(lot("E2", "BUY", 4, ts=datetime(2026,1,1,9,1)))
    store.apply_execution(lot("E3", "SELL", 6, ts=datetime(2026,1,1,9,2)))
    assert [(x.execution_id, x.remaining_quantity) for x in store.open_lots()] == [("E2", 3)]
def test_full_close_keeps_history():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 2)); store.apply_execution(lot("E2", "SELL", 2, ts=datetime(2026,1,1,9,1)))
    assert store.open_lots() == (); assert store.close_events()[0].source_lot_execution_id == "E1"
def test_reversal_consumes_old_and_opens_excess_with_new_provenance():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 2)); store.apply_execution(lot("E2", "SELL", 5, strategy="S2", group="G2", leg="L2"))
    x = store.open_lots()[0]; assert x.execution_id == "E2"; assert x.strategy_id == "S2"; assert x.remaining_quantity == 3
def test_duplicate_execution_is_idempotent():
    store = VirtualPositionLotStore(); e = lot("E1", "BUY", 2); store.apply_execution(e); store.apply_execution(e)
    assert len(store.open_lots()) == 1
def test_duplicate_conflict_fails_closed():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 2))
    try: store.apply_execution(lot("E1", "BUY", 3))
    except ValueError as exc: assert str(exc) == "POSITION_PROVENANCE_DUPLICATE_CONFLICT"
    else: raise AssertionError("expected duplicate conflict")
def test_missing_provenance_fails_closed():
    try: PositionLotProvenance("RUN1", "OPT-C-100", "", "G1", "L1", "C1", "E1", "BUY", 1, 1, T0, ID, Decimal("250000"), "OPTION_MASTER", PositionRole.NONE).validate()
    except ValueError as exc: assert str(exc) == "POSITION_PROVENANCE_REQUIRED"
    else: raise AssertionError("expected fail closed")
def test_insurance_roles_are_explicit():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 1)); store.apply_execution(lot("E2", "BUY", 1, group="G2", leg="L2", role=PositionRole.EVENT_INSURANCE))
    assert [x.position_role for x in store.open_lots()] == [PositionRole.NONE, PositionRole.EVENT_INSURANCE]
def test_insurance_partial_close_preserves_role_and_provenance():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 5, role=PositionRole.OVERNIGHT_INSURANCE)); store.apply_execution(lot("E2", "SELL", 2, ts=datetime(2026,1,1,9,1)))
    x = store.open_lots()[0]; assert x.remaining_quantity == 3; assert x.position_role == PositionRole.OVERNIGHT_INSURANCE; assert x.execution_id == "E1"

def test_reversal_close_events_record_original_lot_provenance():
    store = VirtualPositionLotStore(); store.apply_execution(lot("E1", "BUY", 2)); store.apply_execution(lot("E2", "SELL", 5, strategy="S2", group="G2", leg="L2"))
    assert store.close_events()[0].source_lot_execution_id == "E1"
    assert store.open_lots()[0].execution_id == "E2"

def test_run_identity_is_part_of_provenance():
    store=VirtualPositionLotStore(); e=lot("E1","BUY",1); assert e.run_id == "RUN1"; store.apply_execution(e)
    assert store.open_lots()[0].run_id == "RUN1"
