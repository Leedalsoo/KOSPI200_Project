"""Read model for authoritative per-leg Risk decisions and provenance."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from contracts.risk import RiskEvaluationResult


@dataclass(frozen=True, slots=True)
class RiskApprovalRecord:
    """One immutable Risk decision joined to strategy/group/leg/order provenance."""

    strategy_id: str
    group_id: str
    leg_id: str
    client_order_id: str
    result: RiskEvaluationResult


class RiskApprovalReadModel:
    """Independent in-memory read model for the latest Risk result per leg."""

    def __init__(self) -> None:
        self._records: dict[str, RiskApprovalRecord] = {}

    def record(self, record: RiskApprovalRecord) -> None:
        if not record.client_order_id:
            raise ValueError("RISK_READ_MODEL_CLIENT_ORDER_ID_REQUIRED")
        if not record.group_id or not record.leg_id or not record.strategy_id:
            raise ValueError("RISK_READ_MODEL_PROVENANCE_REQUIRED")
        self._records[record.client_order_id] = record

    def get(self, client_order_id: str) -> RiskApprovalRecord | None:
        return self._records.get(str(client_order_id))

    def for_group(self, group_id: str) -> tuple[RiskApprovalRecord, ...]:
        return tuple(record for record in self._records.values() if record.group_id == group_id)

    def all(self) -> tuple[RiskApprovalRecord, ...]:
        return tuple(self._records.values())

    def replace_all(self, records: Iterable[RiskApprovalRecord]) -> None:
        self._records.clear()
        for record in records:
            self.record(record)