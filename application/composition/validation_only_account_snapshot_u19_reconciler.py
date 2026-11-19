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
    U19ExpectedGroupManifest,
    U19Position,
    U19RecoveryDecision,
    _expected_group_manifest_digest,
    _expected_group_manifest_positions,
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
    group_ledger_snapshots: tuple[U19ExecutionLedgerSnapshot, ...] = ()
    expected_group_manifest: U19ExpectedGroupManifest | None = None

    @property
    def is_valid(self) -> bool:
        return self.status == "VALIDATION_ONLY_U19_RECONCILED"


def _signed(side: str, quantity: int) -> int:
    normalized = str(side or "").upper()
    if normalized in {"BUY", "LONG"}:
        return quantity
    if normalized in {"SELL", "SHORT"}:
        return -quantity
    if normalized in {"FLAT", "NONE", ""} and quantity == 0:
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


def _compose_account_expected_group_manifest(
    *,
    group_manifests: tuple[U19ExpectedGroupManifest, ...],
    group_ids: tuple[str, ...],
    aggregate_group_id: str,
    opening_positions: tuple[U19Position, ...],
    opening_evidence_sha256: str,
) -> U19ExpectedGroupManifest | None:
    """Compose independent group expectations plus the opening baseline.

    Leg identity is the union of every child manifest, while expected positions
    are signed net quantities after cross-group offsets and opening baseline.
    A net-zero instrument remains in leg_instrument_ids even though its zero
    quantity is omitted from expected_positions.
    """
    if (
        not isinstance(group_manifests, tuple)
        or len(group_manifests) != len(group_ids)
        or not isinstance(opening_evidence_sha256, str)
        or len(opening_evidence_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in opening_evidence_sha256)
    ):
        return None
    by_group = {
        item.group_id: item
        for item in group_manifests
        if isinstance(item, U19ExpectedGroupManifest)
    }
    if len(by_group) != len(group_manifests) or set(by_group) != set(group_ids):
        return None

    leg_ids: set[str] = set()
    expected_quantities: dict[str, Decimal] = {}
    child_lineage: list[dict[str, str]] = []
    for group_id in group_ids:
        manifest = by_group[group_id]
        positions = _expected_group_manifest_positions(manifest, group_id=group_id)
        if positions is None:
            return None
        leg_ids.update(manifest.leg_instrument_ids)
        for instrument_id, quantity in positions.items():
            expected_quantities[instrument_id] = (
                expected_quantities.get(instrument_id, Decimal(0)) + quantity
            )
        child_lineage.append({
            "group_id": group_id,
            "manifest_id": manifest.manifest_id,
            "payload_sha256": manifest.payload_sha256.lower(),
        })

    opening_map = _position_map(opening_positions)
    if opening_map is None:
        return None
    leg_ids.update(opening_map)
    for instrument_id, quantity in opening_map.items():
        expected_quantities[instrument_id] = (
            expected_quantities.get(instrument_id, Decimal(0)) + quantity
        )
    if any(
        not quantity.is_finite() or quantity != quantity.to_integral_value()
        for quantity in expected_quantities.values()
    ):
        return None

    leg_instrument_ids = tuple(sorted(leg_ids))
    if not leg_instrument_ids or not set(expected_quantities).issubset(leg_ids):
        return None
    expected_positions = tuple(
        U19Position(instrument_id, quantity)
        for instrument_id, quantity in sorted(expected_quantities.items())
        if quantity != 0
    )
    provenance_payload = {
        "group_manifests": child_lineage,
        "opening_evidence_sha256": opening_evidence_sha256,
    }
    provenance_hash = hashlib.sha256(
        json.dumps(provenance_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = U19ExpectedGroupManifest(
        group_id=aggregate_group_id,
        manifest_id=f"account-aggregate:{provenance_hash}",
        source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        provenance=f"VALIDATION_ONLY:ACCOUNT_AGGREGATE_MANIFEST:{provenance_hash}",
        leg_instrument_ids=leg_instrument_ids,
        expected_positions=expected_positions,
        payload_sha256="0" * 64,
    )
    return replace(manifest, payload_sha256=_expected_group_manifest_digest(manifest))


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
        expected_group_manifest: U19ExpectedGroupManifest | None = None,
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

        projected_quantities = {key: value for key, value in projected_quantities.items() if value != 0}
        final_quantities = {key: value for key, value in final_quantities.items() if value != 0}
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
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
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
            expected_group_manifest=expected_group_manifest,
        )
        if decision.status.value not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
            issues.append(f"U19_RECOVERY_{decision.status.value}")
        if issues:
            status = "RECONCILIATION_REQUIRED"
        else:
            status = "VALIDATION_ONLY_U19_RECONCILED"
        return AccountSnapshotU19Reconciliation(
            status, tuple(issues), ledger, projected_ledger, broker_snapshot, decision,
            (), expected_group_manifest,
        )

    def reconcile_account(
        self,
        *,
        bundle: AccountSnapshotBundle,
        validation: AccountSnapshotValidation,
        group_ids: tuple[str, ...],
        snapshot_id: str,
        as_of: datetime,
        aggregate_group_id: str = "SYNTHETIC:ACCOUNT_AGGREGATE:VALIDATION",
        expected_group_manifests: tuple[U19ExpectedGroupManifest, ...] | None = None,
    ) -> AccountSnapshotU19Reconciliation:
        """Reconcile several OMS groups against one account-wide position snapshot.

        Group IDs are internal validation lineage, not assumed KIS response fields.
        The aggregate U19 checkpoint is synthetic and must never be used as a
        production account or broker identity.
        """
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
        normalized_groups = tuple(sorted(str(value).strip() for value in group_ids))
        if (
            not normalized_groups
            or any(not value for value in normalized_groups)
            or len(set(normalized_groups)) != len(normalized_groups)
        ):
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", ("ACCOUNT_GROUP_IDS_MISSING_OR_DUPLICATE",),
                None, None, None, None,
            )
        aggregate_group = str(aggregate_group_id or "").strip()
        if not aggregate_group.startswith("SYNTHETIC:ACCOUNT_AGGREGATE:"):
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", ("ACCOUNT_AGGREGATE_GROUP_MUST_BE_SYNTHETIC",),
                None, None, None, None,
            )

        group_set = set(normalized_groups)
        issues: list[str] = []
        order_group_by_client: dict[str, str] = {}
        for row in bundle.orders.rows:
            client_id = str(row.get("client_order_id") or "").strip()
            row_group = str(row.get("group_id") or "").strip()
            if not client_id or not row_group:
                issues.append("ACCOUNT_ORDER_GROUP_LINEAGE_MISSING")
                continue
            if row_group not in group_set:
                issues.append(f"ACCOUNT_ORDER_GROUP_NOT_REQUESTED:{row_group}")
                continue
            order_group_by_client[client_id] = row_group
        observed_order_groups = set(order_group_by_client.values())
        if observed_order_groups != group_set:
            issues.append("ACCOUNT_ORDER_GROUP_SET_MISMATCH")

        executions_by_group: dict[str, list[dict[str, Any]]] = {
            group: [] for group in normalized_groups
        }
        for row in bundle.executions.rows:
            client_id = str(row.get("client_order_id") or "").strip()
            row_group = str(row.get("group_id") or "").strip()
            if not row_group or row_group not in group_set:
                issues.append(f"ACCOUNT_EXECUTION_GROUP_INVALID:{row.get('execution_id')}")
                continue
            if order_group_by_client.get(client_id) != row_group:
                issues.append(f"ACCOUNT_EXECUTION_GROUP_ORDER_MISMATCH:{row.get('execution_id')}")
                continue
            executions_by_group[row_group].append(dict(row))
        if issues:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", tuple(dict.fromkeys(issues)),
                None, None, None, None,
            )

        group_ledgers: list[U19ExecutionLedgerSnapshot] = []
        for group in normalized_groups:
            try:
                group_ledgers.append(self.ledger_snapshot_builder.build(
                    group_id=group,
                    snapshot_id=f"{snapshot_id}:group:{group}",
                    as_of=as_of,
                ))
            except U19LedgerSnapshotBuildError as exc:
                issues.append(f"U19_GROUP_LEDGER_BUILD_FAILED:{group}:{exc}")
        if issues:
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", tuple(issues),
                None, None, None, None,
            )
        if any(
            item.as_of.astimezone(timezone.utc) != validation.as_of.astimezone(timezone.utc)
            for item in group_ledgers
        ):
            issues.append("ACCOUNT_U19_SNAPSHOT_AS_OF_MISMATCH")

        account_execution_ids = tuple(
            str(row.get("execution_id") or "").strip()
            for row in bundle.executions.rows
        )
        if any(not value for value in account_execution_ids) or len(account_execution_ids) != len(set(account_execution_ids)):
            issues.append("ACCOUNT_EXECUTION_ID_NOT_UNIQUE_OR_MISSING")
        ledger_events_by_id = {
            event.execution_id: event
            for ledger in group_ledgers
            for event in ledger.execution_events
        }
        if len(ledger_events_by_id) != sum(len(item.execution_events) for item in group_ledgers):
            issues.append("U19_GROUP_EXECUTION_ID_COLLISION")
        ledger_by_group = {item.group_id: item for item in group_ledgers}
        for group in normalized_groups:
            account_group_ids = {
                str(row.get("execution_id") or "").strip()
                for row in executions_by_group[group]
            }
            ledger_group_ids = {
                event.execution_id for event in ledger_by_group[group].execution_events
            }
            if account_group_ids != ledger_group_ids:
                issues.append(f"ACCOUNT_U19_GROUP_EXECUTION_ID_SET_MISMATCH:{group}")
        if set(account_execution_ids) != set(ledger_events_by_id):
            issues.append("ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH")

        settlement_store = self.ledger_snapshot_builder.settlement_store
        journal_rows = settlement_store.load_execution_journal_records()
        journal_by_id = {str(row.get("execution_id") or ""): row for row in journal_rows}
        states_by_client = {
            str(state.get("client_order_id") or ""): state
            for state in settlement_store.load_order_state_payloads()
        }
        journal_fill_totals: dict[str, int] = {}
        for journal_row in journal_rows:
            client_id = str(journal_row.get("client_order_id") or "").strip()
            report = journal_row.get("report") or {}
            if client_id in order_group_by_client:
                quantity = report.get("filled_quantity", 0)
                if isinstance(quantity, int) and not isinstance(quantity, bool):
                    journal_fill_totals[client_id] = journal_fill_totals.get(client_id, 0) + quantity
        for order_row in bundle.orders.rows:
            client_id = str(order_row.get("client_order_id") or "").strip()
            state = states_by_client.get(client_id) or {}
            command = state.get("broker_order_command") or {}
            if (
                str(state.get("broker_order_id") or "") != str(order_row.get("broker_order_id") or "")
                or str(command.get("group_id") or "").strip() != str(order_row.get("group_id") or "").strip()
                or str(command.get("instrument_id") or "") != str(order_row.get("instrument_id") or "")
                or str(command.get("side") or "").upper() != str(order_row.get("side") or "").upper()
                or command.get("quantity") != order_row.get("order_quantity")
            ):
                issues.append(f"ACCOUNT_U19_ORDER_LINEAGE_MISMATCH:{client_id}")
            if journal_fill_totals.get(client_id, 0) != order_row.get("cumulative_filled_quantity"):
                issues.append(f"ACCOUNT_U19_ORDER_CUMULATIVE_FILL_MISMATCH:{client_id}")
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
            row_group = str(account_row.get("group_id") or "").strip()
            command_group = str(command.get("group_id") or "").strip()
            if (
                str(journal_row.get("client_order_id") or "") != client_id
                or str(journal_row.get("broker_order_id") or "") != str(account_row.get("broker_order_id") or "")
                or str(command.get("instrument_id") or "") != str(account_row.get("instrument_id") or "")
                or str(command.get("side") or "").upper() != str(account_row.get("side") or "").upper()
                or command_group != row_group
                or (report.get("group_id") and str(report.get("group_id")) != row_group)
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

        delta_quantities: dict[str, int] = {}
        pending_ids: list[str] = []
        for ledger in group_ledgers:
            pending_ids.extend(ledger.pending_order_ids)
            for item in ledger.positions:
                if item.signed_quantity != item.signed_quantity.to_integral_value():
                    issues.append(f"U19_GROUP_POSITION_NOT_INTEGRAL:{ledger.group_id}:{item.instrument_id}")
                    continue
                delta_quantities[item.instrument_id] = (
                    delta_quantities.get(item.instrument_id, 0) + int(item.signed_quantity)
                )

        opening: dict[str, int] = {}
        for row in bundle.opening_positions.rows:
            instrument = str(row.get("instrument_id") or "").strip()
            try:
                quantity = int(row.get("quantity"))
                if not instrument or quantity < 0:
                    raise ValueError
                if instrument in opening:
                    raise ValueError
                opening[instrument] = _signed(str(row.get("side") or ""), quantity)
            except (TypeError, ValueError):
                issues.append(f"OPENING_POSITION_CANNOT_BE_PROJECTED:{instrument}")

        final_quantities: dict[str, int] = {}
        for row in validation.normalized_positions:
            instrument = str(row.get("instrument_id") or "").strip()
            try:
                final_quantities[instrument] = _signed(
                    str(row.get("side") or "FLAT"), int(row.get("qty"))
                )
            except (TypeError, ValueError):
                issues.append(f"FINAL_POSITION_CANNOT_BE_PROJECTED:{instrument}")

        projected_quantities = dict(opening)
        for instrument, quantity in delta_quantities.items():
            projected_quantities[instrument] = projected_quantities.get(instrument, 0) + quantity
        projected_quantities = {key: value for key, value in projected_quantities.items() if value != 0}
        final_quantities = {key: value for key, value in final_quantities.items() if value != 0}
        if projected_quantities != final_quantities:
            issues.append("ACCOUNT_POSITION_U19_GROUP_AGGREGATE_MISMATCH")

        delta_positions = _positions(delta_quantities)
        projected_positions = _positions(projected_quantities)
        final_positions = _positions(final_quantities)
        aggregate_manifest = None
        if expected_group_manifests is not None:
            aggregate_manifest = _compose_account_expected_group_manifest(
                group_manifests=expected_group_manifests,
                group_ids=normalized_groups,
                aggregate_group_id=aggregate_group,
                opening_positions=_positions(opening),
                opening_evidence_sha256=bundle.opening_positions.payload_sha256,
            )
            if aggregate_manifest is None:
                issues.append("ACCOUNT_EXPECTED_GROUP_MANIFEST_INVALID_OR_GROUP_SET_MISMATCH")
            elif aggregate_manifest.expected_positions != projected_positions:
                issues.append("ACCOUNT_EXPECTED_GROUP_MANIFEST_POSITION_PROJECTION_MISMATCH")
        execution_events = tuple(
            ledger_events_by_id[key] for key in sorted(ledger_events_by_id)
        )
        pending = tuple(dict.fromkeys(pending_ids))
        aggregate_ledger_payload = {
            "group_id": aggregate_group,
            "snapshot_id": f"{snapshot_id}:u19-account-aggregate-ledger",
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
            "pending_order_ids": list(pending),
            "source": "VALIDATION_ONLY:U19_GROUP_LEDGER_AGGREGATE",
            "group_snapshots": [
                {"group_id": item.group_id, "snapshot_id": item.snapshot_id, "sha256": item.payload_sha256}
                for item in group_ledgers
            ],
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in delta_positions
            ],
            "execution_events": [
                {"execution_id": item.execution_id, "fingerprint": item.fingerprint}
                for item in execution_events
            ],
            "pending_order_ids": list(pending),
        }
        aggregate_ledger_hash = hashlib.sha256(
            json.dumps(aggregate_ledger_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        aggregate_ledger = U19ExecutionLedgerSnapshot(
            group_id=aggregate_group,
            snapshot_id=aggregate_ledger_payload["snapshot_id"],
            as_of=as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=delta_positions,
            complete=all(item.complete for item in group_ledgers),
            payload_sha256=aggregate_ledger_hash,
            execution_events=execution_events,
            pending_order_ids=pending,
        )

        projected_payload = {
            "group_id": aggregate_group,
            "snapshot_id": f"{snapshot_id}:u19-account-projected-ledger",
            "source": "VALIDATION_ONLY:U19_GROUP_LEDGER_PLUS_OPENING_BASELINE",
            "base_ledger_sha256": aggregate_ledger_hash,
            "account_snapshot_evidence_sha256": validation.evidence_sha256,
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in projected_positions
            ],
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
            "pending_order_ids": list(pending),
        }
        projected_hash = hashlib.sha256(
            json.dumps(projected_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        projected_ledger = replace(
            aggregate_ledger,
            snapshot_id=f"{snapshot_id}:u19-account-projected-ledger",
            positions=projected_positions,
            payload_sha256=projected_hash,
        )

        broker_payload = {
            "group_id": aggregate_group,
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
            group_id=aggregate_group,
            snapshot_id=broker_payload["snapshot_id"],
            as_of=validation.as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_positions,
            complete=True,
            capability_verified=True,
            payload_sha256=broker_hash,
        )

        recovery_unsafe_prefixes = (
            "ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH",
            "ACCOUNT_U19_GROUP_EXECUTION_ID_SET_MISMATCH:",
            "ACCOUNT_EXECUTION_ID_NOT_UNIQUE_OR_MISSING",
            "U19_GROUP_EXECUTION_ID_COLLISION",
            "ACCOUNT_U19_ORDER_LINEAGE_MISMATCH:",
            "ACCOUNT_U19_ORDER_CUMULATIVE_FILL_MISMATCH:",
            "ACCOUNT_U19_EXECUTION_MISSING_FROM_JOURNAL:",
            "ACCOUNT_U19_EXECUTION_LINEAGE_MISMATCH:",
            "ACCOUNT_U19_EXECUTION_QUANTITY_MISMATCH:",
            "ACCOUNT_U19_EXECUTION_PRICE_MISMATCH:",
            "ACCOUNT_U19_EXECUTION_PRICE_UNVERIFIABLE:",
            "ACCOUNT_U19_EXECUTION_TIME_MISMATCH:",
            "ACCOUNT_U19_EXECUTION_TIME_UNVERIFIABLE:",
            "U19_GROUP_POSITION_NOT_INTEGRAL:",
            "OPENING_POSITION_CANNOT_BE_PROJECTED:",
            "FINAL_POSITION_CANNOT_BE_PROJECTED:",
            "ACCOUNT_EXPECTED_GROUP_MANIFEST_",
        )
        if any(issue.startswith(recovery_unsafe_prefixes) for issue in issues):
            return AccountSnapshotU19Reconciliation(
                "RECONCILIATION_REQUIRED", tuple(dict.fromkeys(issues)),
                aggregate_ledger, projected_ledger, broker_snapshot, None,
                tuple(group_ledgers), aggregate_manifest,
            )

        decision = self.recovery_coordinator.recover(
            group_id=aggregate_group,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=projected_ledger,
            expected_group_manifest=aggregate_manifest,
        )
        if decision.status.value not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
            issues.append(f"U19_RECOVERY_{decision.status.value}")
        status = "RECONCILIATION_REQUIRED" if issues else "VALIDATION_ONLY_U19_RECONCILED"
        return AccountSnapshotU19Reconciliation(
            status, tuple(dict.fromkeys(issues)), aggregate_ledger,
            projected_ledger, broker_snapshot, decision, tuple(group_ledgers), aggregate_manifest,
        )
