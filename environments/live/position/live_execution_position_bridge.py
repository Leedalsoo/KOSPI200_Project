from __future__ import annotations

from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderState, OrderStateMachine, OrderStateTransitionError


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )


class LiveExecutionPositionBridge:
    """Settle an accepted execution exactly once into OMS and Live Position."""

    def __init__(
        self,
        *,
        order_state_machine: OrderStateMachine,
        position_fill_adapter: LivePositionFillAdapter,
        execution_event_deduplicator,
        position_aggregate,
        settlement_store=None,
    ) -> None:
        self._oms = order_state_machine
        self._fill_adapter = position_fill_adapter
        self._dedup = execution_event_deduplicator
        self._position = position_aggregate
        self._store = settlement_store
        if self._store is not None and getattr(self._dedup, "_persistence_store", None) is None:
            self._dedup.set_persistence_store(self._store)

    @staticmethod
    def _execution_payload(report: ExecutionReport, execution_id: str, **extra) -> dict[str, object]:
        payload = {
            "client_order_id": report.client_order_id,
            "broker_order_id": report.broker_order_id,
            "execution_id": execution_id,
            "status": report.status,
            "filled_quantity": report.filled_quantity,
            "remaining_quantity": report.remaining_quantity,
            "execution_price": str(report.execution_price) if report.execution_price is not None else None,
            "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
            "fee": str(report.fee) if report.fee is not None else None,
            "group_id": report.group_id,
            "leg_id": report.leg_id,
        }
        payload.update(extra)
        return payload

    def settle_authoritatively_reconciled_fill(
        self, report: ExecutionReport, *, authoritative_evidence_ref: str
    ) -> object:
        """Settle a late fill only after an external authoritative inquiry verified it."""
        if self._store is None:
            raise OrderStateTransitionError("SETTLEMENT_STORE_REQUIRED")
        evidence = str(authoritative_evidence_ref).strip()
        if not evidence:
            raise OrderStateTransitionError("AUTHORITATIVE_RECONCILIATION_EVIDENCE_REQUIRED")
        if report.execution_timestamp is None:
            raise OrderStateTransitionError("AUTHORITATIVE_EXECUTION_TIMESTAMP_REQUIRED")
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise OrderStateTransitionError("EXECUTION_EVENT_ID_REQUIRED")
        if execution_id.startswith("REST-CCNL-SNAPSHOT|"):
            raise OrderStateTransitionError("ORDER_LEVEL_SNAPSHOT_CANNOT_RESOLVE_INDIVIDUAL_LATE_FILL")
        state = self._oms.get(report.client_order_id)
        if state is None or state.status != "CANCELLED":
            raise OrderStateTransitionError("CANCELLED_ORDER_REQUIRED_FOR_LATE_FILL_RECONCILIATION")
        report_payload = self._execution_payload(
            report,
            execution_id,
            authoritative_evidence_ref=evidence,
            reconciliation_kind="AUTHORITATIVELY_VERIFIED_LATE_FILL",
        )
        if self._store.check_execution_duplicate(
            execution_id=execution_id,
            client_order_id=report.client_order_id,
            broker_order_id=report.broker_order_id,
            report_payload=report_payload,
        ):
            return state
            raise OrderStateTransitionError("DUPLICATE_EXECUTION_REQUIRES_RECONCILIATION")
        command = self._oms.get_broker_order_command(report.broker_order_id)
        if command.client_order_id != report.client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._position.instrument_id:
            raise OrderStateTransitionError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise OrderStateTransitionError("SIDE_INVALID")
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0 or report.execution_price is None or report.execution_price <= 0:
            raise OrderStateTransitionError("AUTHORITATIVE_FILL_QUANTITY_AND_PRICE_REQUIRED")
        cumulative = state.filled_quantity + report.filled_quantity
        if cumulative > state.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != state.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and state.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")

        average = state.average_execution_price
        if state.filled_quantity == 0 or average is None:
            average = Decimal(report.execution_price)
        else:
            average = (
                average * Decimal(state.filled_quantity)
                + Decimal(report.execution_price) * Decimal(report.filled_quantity)
            ) / Decimal(cumulative)
        projected_state = OrderState(
            client_order_id=state.client_order_id,
            status="CANCELLED",
            broker_order_id=state.broker_order_id,
            order_quantity=state.order_quantity,
            filled_quantity=cumulative,
            broker_order_command=state.broker_order_command,
            average_execution_price=average,
        )
        projected_position = self._position.preview_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )
        position_payload = {
            "instrument_id": projected_position.instrument_id,
            "side": projected_position.side,
            "qty": projected_position.qty,
            "avg_price": str(projected_position.avg_price) if projected_position.avg_price is not None else None,
        }
        committed = self._store.commit_fill(
            execution_id=execution_id,
            client_order_id=report.client_order_id,
            broker_order_id=report.broker_order_id,
            report_payload=report_payload,
            order_state_payload=self._oms.state_to_record(projected_state),
            position_payload=position_payload,
            instrument_id=projected_position.instrument_id,
            resolve_scope_key=report.client_order_id,
            authoritative_evidence_ref=evidence,
        )
        if not committed:
            raise OrderStateTransitionError("DUPLICATE_EXECUTION_REQUIRES_RECONCILIATION")
        try:
            self._oms.replace_state(projected_state, persist=False)
            self._position.restore_snapshot(projected_position)
            self._dedup.remember(execution_id)
        except Exception as exc:
            self._store.mark_reconciliation_pending(
                scope_key=report.client_order_id,
                client_order_id=report.client_order_id,
                broker_order_id=report.broker_order_id,
                reason="POST_COMMIT_MEMORY_PROJECTION_REBUILD_REQUIRED",
                payload={"execution_id": execution_id, "error_type": type(exc).__name__},
                conflict=True,
            )
            raise RuntimeError("SETTLEMENT_COMMITTED_MEMORY_PROJECTION_REBUILD_REQUIRED") from exc
        return projected_state

    def settle(self, report: ExecutionReport) -> object:

        state = self._oms.get(report.client_order_id)
        if state is None:
            if self._store is not None:
                self._store.mark_reconciliation_pending(
                    scope_key=f"UNKNOWN_ORDER:{report.client_order_id}",
                    client_order_id=report.client_order_id,
                    broker_order_id=report.broker_order_id,
                    reason="EXECUTION_ORDER_CORRELATION_UNAVAILABLE",
                    payload={"execution_id": str(report.execution_id or ""), "status": report.status},
                    conflict=True,
                )
                raise OrderStateTransitionError("RECONCILIATION_CONFLICT")
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if execution_id.startswith("REST-CCNL-SNAPSHOT|"):
            if self._store is not None:
                self._store.mark_reconciliation_pending(
                    scope_key=f"RECOVERY_SNAPSHOT:{report.client_order_id}",
                    client_order_id=report.client_order_id,
                    broker_order_id=report.broker_order_id,
                    reason="ORDER_LEVEL_RECOVERY_SNAPSHOT_IS_NOT_AN_INDIVIDUAL_EXECUTION",
                    payload={
                        "snapshot_identity": execution_id,
                        "filled_quantity_delta": report.filled_quantity,
                        "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
                    },
                    conflict=True,
                )
            raise OrderStateTransitionError("ORDER_LEVEL_SNAPSHOT_REQUIRES_RECONCILIATION")

        if self._store is not None:
            report_payload = self._execution_payload(report, execution_id)
            if self._store.check_execution_duplicate(
                execution_id=execution_id,
                client_order_id=report.client_order_id,
                broker_order_id=report.broker_order_id,
                report_payload=report_payload,
            ):
                self._dedup.remember(execution_id)
                return state
            if self._dedup.contains(execution_id):
                raise OrderStateTransitionError("SETTLEMENT_DEDUP_STORE_MISMATCH")

        elif self._dedup.contains(execution_id):
            return state

        if state.status == "CANCELLED":
            if self._store is not None:
                self._store.mark_reconciliation_pending(
                    scope_key=report.client_order_id,
                    client_order_id=report.client_order_id,
                    broker_order_id=report.broker_order_id,
                    reason="LATE_FILL_AFTER_CANCEL_REQUIRES_AUTHORITATIVE_RECONCILIATION",
                    payload={
                        "execution_id": execution_id,
                        "status": report.status,
                        "filled_quantity": report.filled_quantity,
                        "execution_price": str(report.execution_price) if report.execution_price is not None else None,
                        "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
                    },
                )
                raise OrderStateTransitionError("RECONCILIATION_PENDING")
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        command = self._oms.get_broker_order_command(report.broker_order_id)
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._position.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None or report.execution_price <= 0:
            raise ValueError("EXECUTION_PRICE_REQUIRED")

        projected_state = self._oms.preview_execution(report)
        projected_position = self._position.preview_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )

        if self._store is None:
            if not self._dedup.accept(report):
                return state
            state = self._oms.apply_execution(report)
            self._fill_adapter.apply(command, report)
            return state

        report_payload = {
            "client_order_id": report.client_order_id,
            "broker_order_id": report.broker_order_id,
            "execution_id": execution_id,
            "status": report.status,
            "filled_quantity": report.filled_quantity,
            "remaining_quantity": report.remaining_quantity,
            "execution_price": str(report.execution_price),
            "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
            "fee": str(report.fee) if report.fee is not None else None,
            "group_id": report.group_id,
            "leg_id": report.leg_id,
        }
        position_payload = {
            "instrument_id": projected_position.instrument_id,
            "side": projected_position.side,
            "qty": projected_position.qty,
            "avg_price": str(projected_position.avg_price) if projected_position.avg_price is not None else None,
        }
        committed = self._store.commit_fill(
            execution_id=execution_id,
            client_order_id=report.client_order_id,
            broker_order_id=report.broker_order_id,
            report_payload=report_payload,
            order_state_payload=self._oms.state_to_record(projected_state),
            position_payload=position_payload,
            instrument_id=projected_position.instrument_id,
        )
        if not committed:
            self._dedup.remember(execution_id)
            return self._oms.get(report.client_order_id)

        try:
            self._oms.replace_state(projected_state, persist=False)
            self._position.restore_snapshot(projected_position)
            self._dedup.remember(execution_id)
        except Exception as exc:
            try:
                self._store.mark_reconciliation_pending(
                    scope_key=report.client_order_id,
                    client_order_id=report.client_order_id,
                    broker_order_id=report.broker_order_id,
                    reason="POST_COMMIT_MEMORY_PROJECTION_REBUILD_REQUIRED",
                    payload={"execution_id": execution_id, "error_type": type(exc).__name__},
                    conflict=True,
                )
            finally:
                raise RuntimeError("SETTLEMENT_COMMITTED_MEMORY_PROJECTION_REBUILD_REQUIRED") from exc
        return projected_state