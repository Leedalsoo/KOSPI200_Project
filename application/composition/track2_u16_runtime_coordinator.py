"""Validation-only Runtime orchestration for the Track2 U16 repair lifecycle.

The coordinator has no broker dependency. Its submission ports must be explicitly
injected by a validation harness; production/live composition must not construct it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Any

from core.strategy.track2_u16_repair_lifecycle import (
    U16RepairInput, U16RepairEvaluation, U16RepairState, evaluate_u16_repair,
)


@dataclass(frozen=True)
class U16RuntimeResult:
    evaluation: U16RepairEvaluation
    action: str
    submitted_quantity: int = 0
    client_order_id: str | None = None
    terminal: bool = False
    reconciled: bool = False


class ValidationOnlyU16RuntimeCoordinator:
    """Drive evaluator -> validation broker port -> reconciliation in test Runtime.

    State is supplied by the caller so a Runtime restart can restore it from its
    durable validation store. No retries occur until the previous attempt is both
    terminal and position-reconciled.
    """

    def __init__(self, *, validation_only: bool,
                 submit_repair: Callable[[str, str, int, str, datetime], Any],
                 submit_flatten: Callable[[str, str, int, str], Any],
                 state_store: Any | None = None) -> None:
        if validation_only is not True:
            raise ValueError("U16_RUNTIME_VALIDATION_ONLY_REQUIRED")
        if not callable(submit_repair) or not callable(submit_flatten):
            raise ValueError("U16_RUNTIME_SUBMISSION_PORTS_REQUIRED")
        self._submit_repair = submit_repair
        self._submit_flatten = submit_flatten
        self._state_store = state_store
        self._state: dict[str, dict[str, Any]] = {}

    def _persist_group(self, group_id: str) -> None:
        if self._state_store is None:
            return
        prefix = f"{group_id}|"
        scoped = {key: dict(value) for key, value in self._state.items() if key.startswith(prefix)}
        self._state_store.save(group_id, scoped)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._state.items()}

    def restore(self, snapshot: dict[str, dict[str, Any]]) -> None:
        if not isinstance(snapshot, dict):
            raise ValueError("U16_RUNTIME_SNAPSHOT_INVALID")
        self._state = {str(key): dict(value) for key, value in snapshot.items()}

    def restore_after_u19_recovery(self, group_id: str, decision: Any) -> bool:
        """Restore persisted retry state only after U19 authorizes strategy resume."""
        status = str(getattr(getattr(decision, "status", None), "value", getattr(decision, "status", "")))
        if (status != "RESTORE_ALLOWED"
                or getattr(decision, "restore_allowed", False) is not True
                or getattr(decision, "strategy_resume_allowed", False) is not True):
            raise ValueError("U16_RUNTIME_U19_RECOVERY_NOT_AUTHORIZED")
        if self._state_store is None:
            raise ValueError("U16_RUNTIME_STATE_STORE_REQUIRED")
        snapshot = self._state_store.load_latest(group_id)
        if snapshot is None:
            return False
        self._state.update(snapshot)
        return True

    def record_repair_reconciliation(self, group_id: str, leg_id: str, *, terminal: bool, reconciled: bool) -> None:
        """Record broker-terminal and position-reconciliation evidence for the latest repair."""
        if not group_id.strip() or not leg_id.strip():
            raise ValueError("U16_RUNTIME_RECONCILIATION_IDENTITY_REQUIRED")
        key = f"{group_id}|{leg_id}"
        prior = self._state.get(key)
        if not prior or not prior.get("last_client_order_id"):
            raise ValueError("U16_RUNTIME_REPAIR_ATTEMPT_NOT_FOUND")
        self._state[key] = {
            **prior,
            "previous_repair_terminal": bool(terminal),
            "previous_repair_reconciled": bool(reconciled),
        }
        self._persist_group(group_id)

    def record_flatten_reconciliation(self, group_id: str, leg_id: str, *, terminal: bool, reconciled: bool) -> None:
        """Record terminal/position evidence for the single persisted flatten intent."""
        if not group_id.strip() or not leg_id.strip():
            raise ValueError("U16_RUNTIME_RECONCILIATION_IDENTITY_REQUIRED")
        key = f"{group_id}|{leg_id}"
        prior = self._state.get(key)
        if not prior or not prior.get("flatten_client_order_id"):
            raise ValueError("U16_RUNTIME_FLATTEN_ATTEMPT_NOT_FOUND")
        self._state[key] = {
            **prior,
            "flatten_terminal": bool(terminal),
            "flatten_reconciled": bool(reconciled),
        }
        self._persist_group(group_id)

    def process(self, data: U16RepairInput) -> U16RuntimeResult:
        key = f"{data.group_id}|{data.leg_id}"
        prior = self._state.get(key, {})
        first_at = prior.get("first_repair_submitted_at", data.first_repair_submitted_at)
        retry_count = int(prior.get("additional_retry_count", data.additional_retry_count))
        previous_terminal = bool(prior.get("previous_repair_terminal", data.previous_repair_terminal))
        previous_reconciled = bool(prior.get("previous_repair_reconciled", data.previous_repair_reconciled))
        effective = replace(
            data, first_repair_submitted_at=first_at,
            additional_retry_count=retry_count,
            previous_repair_terminal=previous_terminal,
            previous_repair_reconciled=previous_reconciled,
        )
        verdict = evaluate_u16_repair(effective)

        if verdict.state == U16RepairState.REPAIR_READY:
            if first_at is not None:
                retry_count += 1
            # The evaluator's READY is a policy verdict, not a broker authorization.
            # This coordinator can only call the explicitly injected validation port.
            outcome = self._submit_repair(data.group_id, data.leg_id, verdict.missing_quantity, verdict.client_order_id or "", data.now)
            terminal = bool(getattr(outcome, "terminal", False))
            reconciled = bool(getattr(outcome, "reconciled", False))
            self._state[key] = {
                "first_repair_submitted_at": first_at or data.now,
                "additional_retry_count": retry_count,
                "previous_repair_terminal": terminal,
                "previous_repair_reconciled": reconciled,
                "last_client_order_id": getattr(outcome, "client_order_id", None) or verdict.client_order_id,
            }
            self._persist_group(data.group_id)
            return U16RuntimeResult(verdict, "REPAIR_SUBMITTED", verdict.missing_quantity,
                                    getattr(outcome, "client_order_id", None) or verdict.client_order_id, terminal, reconciled)

        if verdict.state == U16RepairState.FLATTEN_REQUIRED_BLOCKED:
            # Never flatten while a prior repair order is still open or unreconciled.
            if prior.get("first_repair_submitted_at") is not None and not (
                previous_terminal and previous_reconciled
            ):
                return U16RuntimeResult(verdict, "FLATTEN_BLOCKED_REPAIR_UNRECONCILED")
            # A submitted flatten is immutable until its own reconciliation completes.
            existing_flatten_id = prior.get("flatten_client_order_id")
            if existing_flatten_id:
                return U16RuntimeResult(
                    verdict, "FLATTEN_ALREADY_SUBMITTED",
                    int(prior.get("flatten_quantity", 0)), existing_flatten_id,
                    bool(prior.get("flatten_terminal", False)),
                    bool(prior.get("flatten_reconciled", False)),
                )
            # Flatten only from reconciled position evidence. Never guess exposure.
            group_quantity = (
                data.group_position_quantity
                if data.group_position_confirmed and data.group_position_quantity is not None
                else data.position_quantity
            )
            if group_quantity is None or group_quantity <= 0:
                return U16RuntimeResult(verdict, "FLATTEN_BLOCKED_UNCONFIRMED_POSITION")
            flatten_id = f"u16f-{data.group_id}-{data.leg_id}-{int(data.now.timestamp())}"
            outcome = self._submit_flatten(data.group_id, data.leg_id, group_quantity, flatten_id)
            terminal = bool(getattr(outcome, "terminal", False))
            reconciled = bool(getattr(outcome, "reconciled", False))
            actual_flatten_id = getattr(outcome, "client_order_id", None) or flatten_id
            self._state[key] = {**prior, "flatten_client_order_id": actual_flatten_id,
                                "flatten_client_order_ids": tuple(getattr(outcome, "client_order_ids", ()) or ()),
                                "flatten_quantity": group_quantity,
                                "flatten_terminal": terminal, "flatten_reconciled": reconciled}
            self._persist_group(data.group_id)
            return U16RuntimeResult(verdict, "FLATTEN_SUBMITTED", group_quantity,
                                    actual_flatten_id, terminal, reconciled)

        self._state[key] = {
            **prior,
            "first_repair_submitted_at": first_at,
            "additional_retry_count": retry_count,
            "previous_repair_terminal": previous_terminal,
            "previous_repair_reconciled": previous_reconciled,
            "last_state": verdict.state.value,
        }
        self._persist_group(data.group_id)
        return U16RuntimeResult(verdict, "NO_SUBMISSION")
