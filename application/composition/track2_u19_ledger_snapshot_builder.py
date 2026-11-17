from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from core.oms.track2_u19_recovery import (
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
)


class U19LedgerSnapshotBuildError(ValueError):
    """Raised when persisted OMS/execution lineage cannot safely form a U19 ledger."""


class ValidationOnlyU19LedgerSnapshotBuilder:
    """Build a validation-only group ledger from persisted OMS commands and fills."""

    SOURCE = "VALIDATION_ONLY:EXECUTION_LEDGER"

    def __init__(self, settlement_store) -> None:
        self.settlement_store = settlement_store

    def build(
        self, *, group_id: str, snapshot_id: str, as_of: datetime
    ) -> U19ExecutionLedgerSnapshot:
        group = str(group_id).strip()
        snapshot = str(snapshot_id).strip()
        if not group or not snapshot:
            raise U19LedgerSnapshotBuildError("U19_LEDGER_GROUP_AND_SNAPSHOT_ID_REQUIRED")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise U19LedgerSnapshotBuildError("U19_LEDGER_AS_OF_MUST_BE_TIMEZONE_AWARE")

        states = self.settlement_store.load_order_state_payloads()
        commands: dict[str, dict] = {}
        states_by_client: dict[str, dict] = {}
        for state in states:
            client_id = str(state.get("client_order_id", "")).strip()
            command = state.get("broker_order_command")
            if not client_id or not isinstance(command, dict):
                continue
            if str(command.get("client_order_id", "")).strip() != client_id:
                raise U19LedgerSnapshotBuildError("U19_OMS_COMMAND_CLIENT_ORDER_ID_MISMATCH")
            commands[client_id] = command
            states_by_client[client_id] = state

        replacement_links_for_group: list[dict[str, str]] = []
        replacement_graph: dict[str, set[str]] = {}
        replacement_edges: dict[str, str] = {}
        for link in self.settlement_store.load_order_replacement_links():
            if not str(link.get("source") or "").startswith("VALIDATION_ONLY:"):
                raise U19LedgerSnapshotBuildError("U19_REPLACEMENT_LINK_SOURCE_NOT_VALIDATION_ONLY")
            original_id = link["original_client_order_id"]
            replacement_id = link["replacement_client_order_id"]
            original_command = commands.get(original_id)
            replacement_command = commands.get(replacement_id)
            if original_command is None or replacement_command is None:
                raise U19LedgerSnapshotBuildError("U19_REPLACEMENT_ORDER_COMMAND_LINEAGE_MISSING")
            original_state = states_by_client[original_id]
            replacement_state = states_by_client[replacement_id]
            original_group = str(original_command.get("group_id") or "").strip()
            replacement_group = str(replacement_command.get("group_id") or "").strip()
            original_leg = str(original_command.get("leg_id") or "").strip()
            replacement_leg = str(replacement_command.get("leg_id") or "").strip()
            original_instrument = str(original_command.get("instrument_id") or "").strip()
            replacement_instrument = str(replacement_command.get("instrument_id") or "").strip()
            original_side = str(original_command.get("side") or "").strip().upper()
            replacement_side = str(replacement_command.get("side") or "").strip().upper()
            if (
                original_state.get("status") != "CANCELLED"
                or not link.get("cancel_request_ref") or not link.get("cancel_ack_ref")
                or link["cancel_request_ref"] == link["cancel_ack_ref"]
                or str(original_state.get("broker_order_id") or "") != link["original_broker_order_id"]
                or str(replacement_state.get("broker_order_id") or "") != link["replacement_broker_order_id"]
                or original_group != replacement_group
                or original_leg != replacement_leg
                or original_instrument != replacement_instrument
                or original_side != replacement_side
                or link["group_id"] != original_group
                or link["leg_id"] != original_leg
            ):
                raise U19LedgerSnapshotBuildError("U19_REPLACEMENT_ORDER_LINEAGE_IDENTITY_CONFLICT")
            previous_parent = replacement_edges.get(replacement_id)
            if previous_parent is not None and previous_parent != original_id:
                raise U19LedgerSnapshotBuildError("U19_REPLACEMENT_ORDER_MULTIPLE_PARENTS")
            replacement_edges[replacement_id] = original_id
            replacement_graph.setdefault(original_id, set()).add(replacement_id)
            replacement_graph.setdefault(replacement_id, set()).add(original_id)
            if original_group == group:
                replacement_links_for_group.append({
                    "link_id": link["link_id"],
                    "original_client_order_id": original_id,
                    "original_broker_order_id": link["original_broker_order_id"],
                    "replacement_client_order_id": replacement_id,
                    "replacement_broker_order_id": link["replacement_broker_order_id"],
                    "group_id": original_group,
                    "leg_id": original_leg,
                    "cancel_request_ref": link["cancel_request_ref"],
                    "cancel_ack_ref": link["cancel_ack_ref"],
                    "source": link["source"],
                })

        group_orders_by_leg: dict[str, set[str]] = {}
        for client_id, command in commands.items():
            if str(command.get("group_id") or "").strip() == group:
                leg = str(command.get("leg_id") or "").strip()
                if not leg:
                    raise U19LedgerSnapshotBuildError("U19_GROUP_ORDER_LEG_ID_REQUIRED")
                group_orders_by_leg.setdefault(leg, set()).add(client_id)
        for leg, order_ids in group_orders_by_leg.items():
            if len(order_ids) <= 1:
                continue
            start = next(iter(order_ids))
            visited: set[str] = set()
            pending = [start]
            while pending:
                current = pending.pop()
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(replacement_graph.get(current, set()) - visited)
            if not order_ids.issubset(visited):
                raise U19LedgerSnapshotBuildError("U19_MULTIPLE_ORDERS_FOR_LEG_WITHOUT_REPLACEMENT_LINEAGE")

        # Directed replacement links must form an acyclic chain.
        for start in replacement_edges:
            seen: set[str] = set()
            current = start
            while current in replacement_edges:
                if current in seen:
                    raise U19LedgerSnapshotBuildError("U19_REPLACEMENT_LINEAGE_CYCLE")
                seen.add(current)
                current = replacement_edges[current]

        signed_quantities: dict[str, int] = {}
        order_fill_totals: dict[str, int] = {}
        events: list[U19ExecutionEvent] = []
        seen_execution_ids: dict[str, str] = {}
        leg_instruments: dict[str, str] = {}
        for row in self.settlement_store.load_execution_journal_records():
            client_id = row["client_order_id"]
            command = commands.get(client_id)
            if command is None:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_ORDER_COMMAND_LINEAGE_MISSING")
            command_group = str(command.get("group_id") or "").strip()
            if not command_group:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_GROUP_LINEAGE_MISSING")
            if command_group != group:
                continue

            instrument_id = str(command.get("instrument_id") or "").strip()
            side = str(command.get("side") or "").strip().upper()
            leg_id = str(command.get("leg_id") or "").strip()
            broker_id = row.get("broker_order_id")
            state = states_by_client[client_id]
            identity = command.get("instrument_identity")
            identity_fields = identity.get("fields", {}) if isinstance(identity, dict) else {}
            if (
                not instrument_id or not leg_id or side not in {"BUY", "SELL"}
                or not broker_id or str(state.get("broker_order_id") or "") != str(broker_id)
                or (identity_fields and str(identity_fields.get("instrument_id") or "") != instrument_id)
            ):
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_ORDER_IDENTITY_LINEAGE_INVALID")

            report = row["report"]
            if report.get("status") not in {"PARTIALLY_FILLED", "FILLED"}:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_STATUS_INVALID")
            try:
                execution_time = datetime.fromisoformat(str(report.get("execution_timestamp") or ""))
            except ValueError as exc:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_TIMESTAMP_INVALID") from exc
            if execution_time.tzinfo is None or execution_time.utcoffset() is None:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_TIMESTAMP_MUST_BE_AWARE")
            if execution_time.astimezone(timezone.utc) > as_of.astimezone(timezone.utc):
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_AFTER_LEDGER_AS_OF")
            try:
                execution_price = Decimal(str(report.get("execution_price")))
            except (InvalidOperation, TypeError) as exc:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_PRICE_INVALID") from exc
            if not execution_price.is_finite() or execution_price <= 0:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_PRICE_INVALID")
            report_group = str(report.get("group_id") or "").strip()
            report_leg = str(report.get("leg_id") or "").strip()
            if report_group and report_group != command_group:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_GROUP_ID_CONFLICT")
            if report_leg and report_leg != leg_id:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_LEG_ID_CONFLICT")
            execution_id = str(row["execution_id"]).strip()
            quantity = report.get("filled_quantity")
            if not execution_id or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_ID_OR_QUANTITY_INVALID")
            fingerprint = hashlib.sha256(row["report_json"].encode("utf-8")).hexdigest()
            prior_instrument = leg_instruments.get(leg_id)
            if prior_instrument is not None and prior_instrument != instrument_id:
                raise U19LedgerSnapshotBuildError("U19_LEG_INSTRUMENT_IDENTITY_CONFLICT")
            leg_instruments[leg_id] = instrument_id
            previous = seen_execution_ids.get(execution_id)
            if previous is not None and previous != fingerprint:
                raise U19LedgerSnapshotBuildError("U19_EXECUTION_ID_FINGERPRINT_CONFLICT")
            if previous is not None:
                continue
            seen_execution_ids[execution_id] = fingerprint
            events.append(U19ExecutionEvent(execution_id, fingerprint))
            order_fill_totals[client_id] = order_fill_totals.get(client_id, 0) + quantity
            if order_fill_totals[client_id] > int(command.get("quantity", 0)):
                raise U19LedgerSnapshotBuildError("U19_ORDER_CUMULATIVE_FILL_EXCEEDS_ORDER_QUANTITY")
            signed_quantities[instrument_id] = signed_quantities.get(instrument_id, 0) + (
                quantity if side == "BUY" else -quantity
            )

        positions = tuple(
            U19Position(instrument_id, Decimal(quantity))
            for instrument_id, quantity in sorted(signed_quantities.items()) if quantity != 0
        )

        pending_ids: list[str] = []
        for event in self.settlement_store.open_reconciliation_events():
            client_id = str(event.get("client_order_id") or "").strip()
            command = commands.get(client_id)
            if command is None or not str(command.get("group_id") or "").strip():
                pending_ids.append("__GLOBAL_RECONCILIATION__")
            elif str(command.get("group_id") or "").strip() == group:
                pending_ids.append(client_id)
        for unresolved in self.settlement_store.unresolved_reconciliations():
            client_id = str(unresolved.get("client_order_id") or "").strip()
            if client_id in {"__startup_reconciliation__", "__runtime_bootstrap__"}:
                pending_ids.append("__GLOBAL_RECONCILIATION__")
                continue
            command = commands.get(client_id)
            if command is None or not str(command.get("group_id") or "").strip():
                pending_ids.append("__GLOBAL_RECONCILIATION__")
            elif str(command.get("group_id") or "").strip() == group:
                pending_ids.append(client_id)
        pending = tuple(dict.fromkeys(pending_ids))

        payload = {
            "group_id": group,
            "snapshot_id": snapshot,
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
            "source": self.SOURCE,
            "positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in positions
            ],
            "execution_events": [
                {"execution_id": item.execution_id, "fingerprint": item.fingerprint}
                for item in events
            ],
            "order_replacement_links": replacement_links_for_group,
            "pending_order_ids": list(pending),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return U19ExecutionLedgerSnapshot(
            group_id=group,
            snapshot_id=snapshot,
            as_of=as_of,
            source=self.SOURCE,
            positions=positions,
            complete=True,
            payload_sha256=digest,
            execution_events=tuple(events),
            pending_order_ids=pending,
        )
