from __future__ import annotations
from dataclasses import dataclass
from contracts.position_provenance import PositionRole
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
@dataclass(frozen=True)
class Track9OptionPositionAttribution:
    run_id: str; instrument_id: str; strategy_id: str; group_id: str; leg_id: str
    client_order_id: str; execution_id: str; side: str; remaining_quantity: int
    instrument_identity: object; position_role: PositionRole
@dataclass(frozen=True)
class Track9InsurancePosition:
    run_id: str; instrument_id: str; strategy_id: str; group_id: str; leg_id: str
    client_order_id: str; execution_id: str; side: str; remaining_quantity: int
    instrument_identity: object; position_role: PositionRole
class Track9OptionPositionAttributionReadModel:
    """Projection of authoritative open option lots; no position inference."""
    def __init__(self, store: VirtualPositionLotStore) -> None: self._store=store
    def snapshot(self) -> tuple[Track9OptionPositionAttribution,...]:
        return tuple(Track9OptionPositionAttribution(x.run_id,x.instrument_id,x.strategy_id,x.group_id,x.leg_id,x.client_order_id,x.execution_id,x.side,x.remaining_quantity,x.instrument_identity,x.position_role) for x in self._store.open_lots())
class Track9InsurancePositionReadModel:
    """Projection of the same authoritative lots restricted to insurance roles."""
    def __init__(self, store: VirtualPositionLotStore) -> None: self._store=store
    def snapshot(self) -> tuple[Track9InsurancePosition,...]:
        return tuple(Track9InsurancePosition(x.run_id,x.instrument_id,x.strategy_id,x.group_id,x.leg_id,x.client_order_id,x.execution_id,x.side,x.remaining_quantity,x.instrument_identity,x.position_role) for x in self._store.open_lots() if x.position_role != PositionRole.NONE)
