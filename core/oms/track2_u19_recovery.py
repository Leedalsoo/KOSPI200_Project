from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import re


class U19RecoveryStatus(str, Enum):
    RESTORE_ALLOWED = "RESTORE_ALLOWED"
    FLAT_CONFIRMED = "FLAT_CONFIRMED"
    BROKER_POSITION_UNAVAILABLE = "BROKER_POSITION_UNAVAILABLE"
    BROKER_SNAPSHOT_UNVERIFIED = "BROKER_SNAPSHOT_UNVERIFIED"
    LEDGER_UNAVAILABLE = "LEDGER_UNAVAILABLE"
    LEDGER_SNAPSHOT_UNVERIFIED = "LEDGER_SNAPSHOT_UNVERIFIED"
    SNAPSHOT_AS_OF_MISMATCH = "SNAPSHOT_AS_OF_MISMATCH"
    PENDING_ORDER_RECONCILIATION_REQUIRED = "PENDING_ORDER_RECONCILIATION_REQUIRED"
    EXECUTION_ID_CONFLICT = "EXECUTION_ID_CONFLICT"
    POSITION_SNAPSHOT_INVALID = "POSITION_SNAPSHOT_INVALID"
    POSITION_LEDGER_MISMATCH = "POSITION_LEDGER_MISMATCH"


@dataclass(frozen=True)
class U19Position:
    instrument_id: str
    signed_quantity: Decimal


@dataclass(frozen=True)
class U19ExecutionEvent:
    execution_id: str
    fingerprint: str


@dataclass(frozen=True)
class U19BrokerPositionSnapshot:
    group_id: str
    snapshot_id: str
    as_of: datetime
    source: str
    positions: tuple[U19Position, ...]
    complete: bool
    capability_verified: bool
    payload_sha256: str


@dataclass(frozen=True)
class U19ExecutionLedgerSnapshot:
    group_id: str
    snapshot_id: str
    as_of: datetime
    source: str
    positions: tuple[U19Position, ...]
    complete: bool
    payload_sha256: str
    execution_events: tuple[U19ExecutionEvent, ...] = ()
    pending_order_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class U19RecoveryDecision:
    checkpoint_id: str
    group_id: str
    status: U19RecoveryStatus
    reason: str
    as_of: datetime | None
    position_basis: str
    positions: tuple[U19Position, ...]
    broker_snapshot_sha256: str | None
    ledger_snapshot_sha256: str | None
    broker_snapshot_id: str | None
    ledger_snapshot_id: str | None
    broker_positions: tuple[U19Position, ...]
    ledger_positions: tuple[U19Position, ...]
    execution_events: tuple[U19ExecutionEvent, ...]
    pending_order_ids: tuple[str, ...]
    restore_allowed: bool
    strategy_resume_allowed: bool
    new_entry_enabled: bool = False
    order_submission_enabled: bool = False
    runtime_restore_performed: bool = False
    schema_version: int = 1

    def to_checkpoint(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "checkpoint_id": self.checkpoint_id,
            "group_id": self.group_id,
            "status": self.status.value,
            "reason": self.reason,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "position_basis": self.position_basis,
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in sorted(self.positions, key=lambda item: item.instrument_id)
            ],
            "broker_snapshot_sha256": self.broker_snapshot_sha256,
            "ledger_snapshot_sha256": self.ledger_snapshot_sha256,
            "broker_snapshot_id": self.broker_snapshot_id,
            "ledger_snapshot_id": self.ledger_snapshot_id,
            "broker_positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in sorted(self.broker_positions, key=lambda item: item.instrument_id)
            ],
            "ledger_positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in sorted(self.ledger_positions, key=lambda item: item.instrument_id)
            ],
            "execution_events": [
                {"execution_id": item.execution_id, "fingerprint": item.fingerprint}
                for item in self.execution_events
            ],
            "pending_order_ids": list(self.pending_order_ids),
            "restore_allowed": self.restore_allowed,
            "strategy_resume_allowed": self.strategy_resume_allowed,
            "new_entry_enabled": self.new_entry_enabled,
            "order_submission_enabled": self.order_submission_enabled,
            "runtime_restore_performed": self.runtime_restore_performed,
        }


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def _valid_hash(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _position_map(positions: tuple[U19Position, ...]) -> dict[str, Decimal] | None:
    result: dict[str, Decimal] = {}
    for item in positions:
        if not isinstance(item, U19Position):
            return None
        if (
            not item.instrument_id
            or not item.instrument_id.strip()
            or not isinstance(item.signed_quantity, Decimal)
            or not item.signed_quantity.is_finite()
            or item.signed_quantity != item.signed_quantity.to_integral_value()
            or item.signed_quantity == 0
            or item.instrument_id in result
        ):
            return None
        result[item.instrument_id] = item.signed_quantity
    return result


def _event_ids_valid(events: tuple[U19ExecutionEvent, ...]) -> bool:
    seen: dict[str, str] = {}
    for event in events:
        if not isinstance(event, U19ExecutionEvent):
            return False
        if not event.execution_id or not event.execution_id.strip() or not event.fingerprint:
            return False
        prior = seen.get(event.execution_id)
        if prior is not None and prior != event.fingerprint:
            return False
        seen[event.execution_id] = event.fingerprint
    return True


def _checkpoint_id(
    group_id: str,
    status: U19RecoveryStatus,
    broker: U19BrokerPositionSnapshot | None,
    ledger: U19ExecutionLedgerSnapshot | None,
    as_of: datetime | None,
) -> str:
    parts = (
        group_id,
        status.value,
        broker.snapshot_id if broker else "",
        ledger.snapshot_id if ledger else "",
        broker.payload_sha256 if broker else "",
        ledger.payload_sha256 if ledger else "",
        as_of.astimezone(timezone.utc).isoformat() if _aware(as_of) else "",
    )
    return "u19-" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def evaluate_u19_recovery(
    *,
    group_id: str,
    broker_snapshot: U19BrokerPositionSnapshot | None,
    ledger_snapshot: U19ExecutionLedgerSnapshot | None,
) -> U19RecoveryDecision:
    """Validation-only reconciliation. Broker positions are primary; mismatch never auto-adjusts."""
    status: U19RecoveryStatus
    reason: str
    as_of = broker_snapshot.as_of if broker_snapshot else (
        ledger_snapshot.as_of if ledger_snapshot else None
    )
    positions: tuple[U19Position, ...] = ()
    broker_hash = broker_snapshot.payload_sha256 if broker_snapshot else None
    ledger_hash = ledger_snapshot.payload_sha256 if ledger_snapshot else None

    if not group_id or not group_id.strip():
        status, reason = U19RecoveryStatus.POSITION_SNAPSHOT_INVALID, "GROUP_ID_REQUIRED"
    elif broker_snapshot is None:
        status, reason = U19RecoveryStatus.BROKER_POSITION_UNAVAILABLE, "AUTHORITATIVE_BROKER_POSITION_SNAPSHOT_REQUIRED"
    elif (
        broker_snapshot.group_id != group_id
        or broker_snapshot.source != "VALIDATION_ONLY:BROKER_EXCHANGE"
        or not broker_snapshot.snapshot_id or not broker_snapshot.snapshot_id.strip()
        or not broker_snapshot.complete
        or not broker_snapshot.capability_verified
        or not _aware(broker_snapshot.as_of)
        or not _valid_hash(broker_snapshot.payload_sha256)
    ):
        status, reason = U19RecoveryStatus.BROKER_SNAPSHOT_UNVERIFIED, "BROKER_SNAPSHOT_SOURCE_COMPLETENESS_OR_PROVENANCE_UNVERIFIED"
    elif ledger_snapshot is None:
        status, reason = U19RecoveryStatus.LEDGER_UNAVAILABLE, "PERSISTED_EXECUTION_LEDGER_REQUIRED_AS_SECONDARY_EVIDENCE"
    elif (
        ledger_snapshot.group_id != group_id
        or ledger_snapshot.source != "VALIDATION_ONLY:EXECUTION_LEDGER"
        or not ledger_snapshot.snapshot_id or not ledger_snapshot.snapshot_id.strip()
        or not ledger_snapshot.complete
        or not _aware(ledger_snapshot.as_of)
        or not _valid_hash(ledger_snapshot.payload_sha256)
    ):
        status, reason = U19RecoveryStatus.LEDGER_SNAPSHOT_UNVERIFIED, "EXECUTION_LEDGER_SNAPSHOT_SOURCE_COMPLETENESS_OR_PROVENANCE_UNVERIFIED"
    elif broker_snapshot.as_of.astimezone(timezone.utc) != ledger_snapshot.as_of.astimezone(timezone.utc):
        status, reason = U19RecoveryStatus.SNAPSHOT_AS_OF_MISMATCH, "BROKER_AND_LEDGER_SNAPSHOTS_NOT_TIME_ALIGNED"
    elif ledger_snapshot.pending_order_ids:
        status, reason = U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED, "PENDING_OR_UNKNOWN_ORDER_MAY_HAVE_LATE_FILL"
    elif not _event_ids_valid(ledger_snapshot.execution_events):
        status, reason = U19RecoveryStatus.EXECUTION_ID_CONFLICT, "EXECUTION_ID_DUPLICATE_WITH_CONFLICTING_FINGERPRINT_OR_MISSING_ID"
    else:
        broker_positions = _position_map(broker_snapshot.positions)
        ledger_positions = _position_map(ledger_snapshot.positions)
        if broker_positions is None or ledger_positions is None:
            status, reason = U19RecoveryStatus.POSITION_SNAPSHOT_INVALID, "POSITION_IDENTITY_OR_SIGNED_QUANTITY_INVALID"
        elif broker_positions != ledger_positions:
            status, reason = U19RecoveryStatus.POSITION_LEDGER_MISMATCH, "AUTHORITATIVE_BROKER_POSITION_DIFFERS_FROM_EXECUTION_LEDGER"
            positions = tuple(broker_snapshot.positions)
        else:
            positions = tuple(broker_snapshot.positions)
            if not broker_positions:
                status, reason = U19RecoveryStatus.FLAT_CONFIRMED, "BROKER_AND_LEDGER_BOTH_CONFIRM_FLAT"
            else:
                status, reason = U19RecoveryStatus.RESTORE_ALLOWED, "BROKER_POSITION_CONFIRMED_BY_PERSISTED_EXECUTION_LEDGER"

    allowed = status in {U19RecoveryStatus.RESTORE_ALLOWED, U19RecoveryStatus.FLAT_CONFIRMED}
    return U19RecoveryDecision(
        checkpoint_id=_checkpoint_id(group_id, status, broker_snapshot, ledger_snapshot, as_of),
        group_id=group_id,
        status=status,
        reason=reason,
        as_of=as_of,
        position_basis="BROKER_EXCHANGE" if broker_snapshot is not None else "UNAVAILABLE",
        positions=positions,
        broker_snapshot_sha256=broker_hash,
        ledger_snapshot_sha256=ledger_hash,
        broker_snapshot_id=broker_snapshot.snapshot_id if broker_snapshot else None,
        ledger_snapshot_id=ledger_snapshot.snapshot_id if ledger_snapshot else None,
        broker_positions=tuple(broker_snapshot.positions) if broker_snapshot else (),
        ledger_positions=tuple(ledger_snapshot.positions) if ledger_snapshot else (),
        execution_events=tuple(ledger_snapshot.execution_events) if ledger_snapshot else (),
        pending_order_ids=tuple(ledger_snapshot.pending_order_ids) if ledger_snapshot else (),
        restore_allowed=allowed,
        strategy_resume_allowed=allowed,
        new_entry_enabled=False,
        order_submission_enabled=False,
    )
