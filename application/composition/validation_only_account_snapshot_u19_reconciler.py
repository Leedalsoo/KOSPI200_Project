from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from application.composition.validation_only_account_snapshot_assembler import (
    AccountSnapshotBundle,
    AccountSnapshotValidation,
)
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryDecision,
)
from application.composition.track2_u19_ledger_snapshot_builder import U19LedgerSnapshotBuildError


@dataclass(frozen=True)
class AccountSnapshotU19Reconciliation:
    status: str
    issues: tuple[str, ...]
    ledger_snapshot: U19ExecutionLedgerSnapshot | None
    projected_ledger_snapshot: U19ExecutionLedgerSnapshot | None
    broker_snapshot: U19BrokerPositionSnapshot | None
    recovery_decision: U19RecoveryDecision | None

    @property
    def is_valid(self) -> bool:
        return self.status == "VALIDATION_ONLY_U19_RECONCILED"


def _signed(side: str, quantity: int) -> int:
    normalized = str(side or "").upper()
    if normalized in {"BUY", "LONG"}:
        return quantity
    if normalized in {"SELL", "SHORT"}:
        return -quantity
    if normalized == "FLAT" and quantity == 0:
        return 0
    raise ValueError("ACCOUNT_SNAPSHOT_POSITION_SIDE_INVALID")


def _position_map(positions: tuple[U19Position, ...]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for item in positions:
        if item.instrument_id in result:
            raise ValueError("U19_POSITION_DUPLICATE_INSTRUMENT")
        result[item.instrument_id] = item.signed_quantity
    return result


def _positions(values: dict[str, int]) -> tuple[U19Position, ...]:
    return tuple(
        U19Position(instrument_id, Decimal(quantity))
        for instrument_id, quantity in sorted(values.items())
        if quantity != 0
    )


class ValidationOnlyAccountSnapshotU19Reconciler:
    """Join normalized account snapshots to the persisted U19 execution ledger.

    The account snapshot is a validation-only broker-position proxy. The U19
    builder remains responsible for OMS command, group/leg, replacement,
    execution fingerprint and pending-reconciliation lineage.
    """

    def __init__(self, *, ledger_snapshot_builder, recovery_coordinator) -> None:
        self.ledger_snapshot_builder = ledger_snapshot_builder
        self.recovery_coordinator = recovery_coordinator

    def reconcile(
        self,
        *,
        bundle: AccountSnapshotBundle,
        validation: AccountSnapshotValidation,
        group_id: str,
        snapshot_id: str,
        as_of: datetime,
    ) -> AccountSnapshotU19Reconciliation:
        if not validation.is_valid or validation.as_of is None or not validation.evidence_sha256:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED",
                tuple(validation.issues) or ("ACCOUNT_SNAPSHOT_VALIDATION_REQUIRED",),
                None, None, None, None,
            )
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", ("U19_AS_OF_TIMEZONE_UNSPECIFIED",),
                None, None, None, None,
            )

        try:
            ledger = self.ledger_snapshot_builder.build(
                group_id=group_id,
                snapshot_id=f"{snapshot_id}:u19-ledger",
                as_of=as_of,
            )
        except U19LedgerSnapshotBuildError as exc:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", (str(exc),), None, None, None, None,
            )
        issues: list[str] = []
        if ledger.as_of.astimezone(timezone.utc) != validation.as_of.astimezone(timezone.utc):
            issues.append("ACCOUNT_U19_SNAPSHOT_AS_OF_MISMATCH")

        account_execution_ids = tuple(
            str(row.get("execution_id") or "").strip()
            for row in bundle.executions.rows
        )
        ledger_execution_ids = tuple(event.execution_id for event in ledger.execution_events)
        if len(account_execution_ids) != len(set(account_execution_ids)):
            issues.append("ACCOUNT_EXECUTION_ID_NOT_UNIQUE")
        if set(account_execution_ids) != set(ledger_execution_ids):
            issues.append("ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH")

        settlement_store = self.ledger_snapshot_builder.settlement_store
        journal_rows = settlement_store.load_execution_journal_records()
        journal_by_id = {str(row.get("execution_id") or ""): row for row in journal_rows}
        states_by_client = {
            str(state.get("client_order_id") or ""): state
            for state in settlement_store.load_order_state_payloads()
        }
        for account_row in bundle.executions.rows:
            execution_id = str(account_row.get("execution_id") or "").strip()
            journal_row = journal_by_id.get(execution_id)
            if journal_row is None:
                issues.append(f"ACCOUNT_U19_EXECUTION_MISSING_FROM_JOURNAL:{execution_id}")
                continue
            report = journal_row.get("report") or {}
            client_id = str(account_row.get("client_order_id") or "").strip()
            state = states_by_client.get(client_id) or {}
            command = state.get("broker_order_command") or {}
            if (
                str(journal_row.get("client_order_id") or "") != client_id
                or str(journal_row.get("broker_order_id") or "") != str(account_row.get("broker_order_id") or "")
                or str(command.get("instrument_id") or "") != str(account_row.get("instrument_id") or "")
                or str(command.get("side") or "").upper() != str(account_row.get("side") or "").upper()
            ):
                issues.append(f"ACCOUNT_U19_EXECUTION_LINEAGE_MISMATCH:{execution_id}")
            if report.get("filled_quantity") != account_row.get("filled_quantity"):
                issues.append(f"ACCOUNT_U19_EXECUTION_QUANTITY_MISMATCH:{execution_id}")
            try:
                if Decimal(str(report.get("execution_price"))) != Decimal(str(account_row.get("execution_price"))):
                    issues.append(f"ACCOUNT_U19_EXECUTION_PRICE_MISMATCH:{execution_id}")
            except (InvalidOperation, TypeError, ValueError):
                issues.append(f"ACCOUNT_U19_EXECUTION_PRICE_UNVERIFIABLE:{execution_id}")
            try:
                journal_time = datetime.fromisoformat(str(report.get("execution_timestamp") or ""))
                account_time = account_row.get("execution_timestamp")
                if (
                    journal_time.tzinfo is None or journal_time.utcoffset() is None
                    or not isinstance(account_time, datetime)
                    or account_time.tzinfo is None or account_time.utcoffset() is None
                    or journal_time.astimezone(timezone.utc) != account_time.astimezone(timezone.utc)
                ):
                    issues.append(f"ACCOUNT_U19_EXECUTION_TIME_MISMATCH:{execution_id}")
            except (TypeError, ValueError):
                issues.append(f"ACCOUNT_U19_EXECUTION_TIME_UNVERIFIABLE:{execution_id}")

        opening: dict[str, int] = {}
        for row in bundle.opening_positions.rows:
            instrument = str(row.get("instrument_id") or "").strip()
            try:
                opening[instrument] = _signed(str(row.get("side") or ""), int(row.get("quantity")))
            except (TypeError, ValueError):
                issues.append(f"OPENING_POSITION_CANNOT_BE_PROJECTED:{instrument}")

        ledger_delta: dict[str, int] = {}
        try:
            for item in ledger.positions:
                if item.signed_quantity != item.signed_quantity.to_integral_value():
                    raise ValueError("U19_LEDGER_POSITION_NOT_INTEGRAL")
                ledger_delta[item.instrument_id] = int(item.signed_quantity)
        except (AttributeError, ValueError):
            issues.append("U19_LEDGER_POSITION_CANNOT_BE_PROJECTED")

        projected_quantities = dict(opening)
        for instrument, quantity in ledger_delta.items():
            projected_quantities[instrument] = projected_quantities.get(instrument, 0) + quantity

        final_quantities: dict[str, int] = {}
        for row in validation.normalized_positions:
            instrument = str(row.get("instrument_id") or "").strip()
            try:
                final_quantities[instrument] = _signed(
                    str(row.get("side") or "FLAT"), int(row.get("qty"))
                )
            except (TypeError, ValueError):
                issues.append(f"FINAL_POSITION_CANNOT_BE_PROJECTED:{instrument}")

        if projected_quantities != final_quantities:
            issues.append("ACCOUNT_POSITION_U19_LEDGER_PROJECTION_MISMATCH")

        projected_positions = _positions(projected_quantities)
        final_positions = _positions(final_quantities)
        projected_payload = {
            "group_id": group_id,
            "snapshot_id": f"{snapshot_id}:u19-ledger-account-projection",
            "as_of": ledger.as_of.astimezone(timezone.utc).isoformat(),
            "source": "VALIDATION_ONLY:U19_LEDGER_PLUS_OPENING_BASELINE",
            "base_ledger_sha256": ledger.payload_sha256,
            "account_snapshot_evidence_sha256": validation.evidence_sha256,
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in projected_positions
            ],
            "execution_events": [
                {"execution_id": item.execution_id, "fingerprint": item.fingerprint}
                for item in ledger.execution_events
            ],
            "pending_order_ids": list(ledger.pending_order_ids),
        }
        projected_hash = hashlib.sha256(
            json.dumps(projected_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        projected_ledger = replace(
            ledger,
            snapshot_id=projected_payload["snapshot_id"],
            as_of=ledger.as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=projected_positions,
            payload_sha256=projected_hash,
        )

        broker_payload = {
            "group_id": group_id,
            "snapshot_id": f"{snapshot_id}:account-position-proxy",
            "as_of": validation.as_of.astimezone(timezone.utc).isoformat(),
            "source": "VALIDATION_ONLY:BROKER_EXCHANGE",
            "account_snapshot_evidence_sha256": validation.evidence_sha256,
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in final_positions
            ],
        }
        broker_hash = hashlib.sha256(
            json.dumps(broker_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        broker_snapshot = U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id=broker_payload["snapshot_id"],
            as_of=validation.as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=broker_hash,
        )

        if "ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH" in issues or "ACCOUNT_EXECUTION_ID_NOT_UNIQUE" in issues:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", tuple(issues), ledger,
                projected_ledger, broker_snapshot, None,
            )

        decision = self.recovery_coordinator.recover(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=projected_ledger,
        )
        if decision.status.value not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
            issues.append(f"U19_RECOVERY_{decision.status.value}")
        if issues:
            status = "RECONCILIATION_REQUIRED"
        else:
            status = "VALIDATION_ONLY_U19_RECONCILED"
        return AccountSnapshotU19Reconciliation(
            status, tuple(issues), ledger, projected_ledger, broker_snapshot, decision,
        )
