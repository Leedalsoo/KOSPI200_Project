from datetime import UTC, datetime
from decimal import Decimal

from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.types import OptionInstrumentIdentity
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore


def _lot(execution_id: str, group_id: str, side: str) -> PositionLotProvenance:
    identity = OptionInstrumentIdentity(
        instrument_id="SYNTH-OPT-SHARED", symbol="SYNTH-OPT-SHARED", expiry="20261210",
        option_type="CALL", strike=Decimal("500"), contract_multiplier=Decimal("10"),
        identity_source="SYNTHETIC_VALIDATION_ONLY",
    )
    return PositionLotProvenance(
        run_id="SYNTH-RUN", instrument_id=identity.instrument_id, strategy_id="SYNTH-STRATEGY",
        group_id=group_id, leg_id="CALL", client_order_id=f"CO-{execution_id}",
        execution_id=execution_id, side=side, opened_quantity=1, remaining_quantity=1,
        execution_timestamp=datetime(2026, 11, 20, tzinfo=UTC), instrument_identity=identity,
        contract_multiplier=Decimal("10"), identity_source="SYNTHETIC_VALIDATION_ONLY",
        position_role=PositionRole.NONE,
    )


def test_fifo_does_not_close_another_candidate_group_lot():
    store = VirtualPositionLotStore()
    store.apply_execution(_lot("A-BUY", "GROUP-A", "BUY"))
    store.apply_execution(_lot("B-SELL", "GROUP-B", "SELL"))

    assert [(lot.execution_id, lot.group_id, lot.remaining_quantity) for lot in store.open_lots()] == [
        ("A-BUY", "GROUP-A", 1), ("B-SELL", "GROUP-B", 1),
    ]
    assert store.close_events() == ()
