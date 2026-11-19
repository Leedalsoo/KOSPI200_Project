from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from application.composition.validation_only_runtime_ledger_comparator import (
    ValidationOnlyRuntimeLedgerComparator,
)
from core.oms.track2_u19_recovery import U19RecoveryDecision, U19RecoveryStatus


@dataclass(frozen=True)
class ValidationOnlyRuntimeInvariantReport:
    status: str
    issues: tuple[str, ...]
    checks: Mapping[str, str]
    manifest: Mapping[str, Any]
    manifest_sha256: str | None


class ValidationOnlyRuntimeInvariantChecker:
    """Read-only cross-check of order/fill lineage, ledger, VSSF and U19 invariants."""

    VERSION = "Q25-A8-TRACK4-T2-X1-v1"
    PASS = "VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

    @staticmethod
    def _aware(value: Any) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RUNTIME_INVARIANT_TIMEZONE_REQUIRED")
        return value.astimezone(UTC)

    @staticmethod
    def _decimal(value: Any, code: str) -> Decimal:
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(code) from exc
        if not result.is_finite():
            raise ValueError(code)
        return result

    @staticmethod
    def _fingerprint(row: Mapping[str, Any]) -> str:
        fields = (
            "execution_id", "client_order_id", "broker_order_id", "group_id",
            "leg_id", "instrument_id", "side", "quantity", "price",
            "contract_multiplier", "executed_at",
        )
        payload = {}
        for key in fields:
            value = row.get(key)
            payload[key] = value.isoformat() if isinstance(value, datetime) else str(value)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def check(
        self,
        *,
        order_commands: Sequence[Mapping[str, Any]],
        executions: Sequence[Mapping[str, Any]],
        ledger_evidence: Mapping[str, Any],
        u19_decision: U19RecoveryDecision,
        source_namespace: str,
        deterministic_rule_id: str,
        source_manifest_sha256: str,
        source_anchor_refs: Sequence[str],
        source_anchor_as_of: Any,
        scenario_timestamp: Any,
        evidence_refs: Sequence[str],
    ) -> ValidationOnlyRuntimeInvariantReport:
        issues: list[str] = []
        checks: dict[str, str] = {}

        if not str(source_namespace).startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            issues.append("RUNTIME_INVARIANT_SYNTHETIC_NAMESPACE_REQUIRED")
        if not str(deterministic_rule_id).strip():
            issues.append("RUNTIME_INVARIANT_DETERMINISTIC_RULE_REQUIRED")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(source_manifest_sha256 or "")):
            issues.append("RUNTIME_INVARIANT_SOURCE_MANIFEST_SHA256_REQUIRED")
        if not source_anchor_refs or not evidence_refs:
            issues.append("RUNTIME_INVARIANT_PROVENANCE_REFS_REQUIRED")
        try:
            anchor = self._aware(source_anchor_as_of)
            scenario = self._aware(scenario_timestamp)
            if anchor > scenario:
                issues.append("RUNTIME_INVARIANT_FUTURE_SOURCE_ANCHOR")
        except (TypeError, ValueError):
            anchor = scenario = None
            issues.append("RUNTIME_INVARIANT_SCENARIO_TIME_INVALID")

        orders_by_id: dict[str, Mapping[str, Any]] = {}
        for row in order_commands:
            client_id = str(row.get("client_order_id") or "").strip()
            if not client_id or client_id in orders_by_id:
                issues.append("RUNTIME_INVARIANT_ORDER_ID_MISSING_OR_DUPLICATE")
                continue
            orders_by_id[client_id] = row
            try:
                quantity = int(row.get("quantity"))
                if quantity <= 0:
                    raise ValueError
                side = str(row.get("side") or "").upper()
                if side not in {"BUY", "SELL"}:
                    raise ValueError
                for field in ("group_id", "leg_id", "instrument_id"):
                    if not str(row.get(field) or "").strip():
                        raise ValueError
            except (TypeError, ValueError):
                issues.append(f"RUNTIME_INVARIANT_ORDER_CONTRACT_INVALID:{client_id}")

        fills_by_order: dict[str, int] = {}
        execution_fingerprints: dict[str, str] = {}
        unique_execution_ids: set[str] = set()
        for row in executions:
            execution_id = str(row.get("execution_id") or "").strip()
            client_id = str(row.get("client_order_id") or "").strip()
            if not execution_id:
                issues.append("RUNTIME_INVARIANT_EXECUTION_ID_MISSING")
                continue
            fingerprint = str(row.get("fingerprint") or self._fingerprint(row))
            prior = execution_fingerprints.get(execution_id)
            if prior is not None:
                issues.append(
                    "RUNTIME_INVARIANT_EXECUTION_ID_DUPLICATE"
                    if prior == fingerprint else "RUNTIME_INVARIANT_EXECUTION_ID_CONFLICT"
                )
                continue
            execution_fingerprints[execution_id] = fingerprint
            unique_execution_ids.add(execution_id)
            order = orders_by_id.get(client_id)
            if order is None:
                issues.append(f"RUNTIME_INVARIANT_EXECUTION_ORDER_MISSING:{execution_id}")
                continue
            for field in ("group_id", "leg_id", "instrument_id"):
                if str(row.get(field) or "") != str(order.get(field) or ""):
                    issues.append(f"RUNTIME_INVARIANT_EXECUTION_{field.upper()}_MISMATCH:{execution_id}")
            if str(row.get("side") or "").upper() != str(order.get("side") or "").upper():
                issues.append(f"RUNTIME_INVARIANT_EXECUTION_SIDE_MISMATCH:{execution_id}")
            try:
                quantity = int(row.get("quantity"))
                price = self._decimal(row.get("price"), "RUNTIME_INVARIANT_EXECUTION_PRICE_INVALID")
                multiplier = self._decimal(row.get("contract_multiplier"), "RUNTIME_INVARIANT_MULTIPLIER_INVALID")
                self._aware(row.get("executed_at"))
                if quantity <= 0 or price <= 0 or multiplier <= 0:
                    raise ValueError
                fills_by_order[client_id] = fills_by_order.get(client_id, 0) + quantity
            except (TypeError, ValueError):
                issues.append(f"RUNTIME_INVARIANT_EXECUTION_VALUE_INVALID:{execution_id}")

        for client_id, order in orders_by_id.items():
            try:
                ordered_qty = int(order.get("quantity"))
                filled_qty = fills_by_order.get(client_id, 0)
                reported_qty = order.get("filled_quantity")
                if filled_qty > ordered_qty:
                    issues.append(f"RUNTIME_INVARIANT_ORDER_OVERFILLED:{client_id}")
                if reported_qty is not None and int(reported_qty) != filled_qty:
                    issues.append(f"RUNTIME_INVARIANT_ORDER_FILL_TOTAL_MISMATCH:{client_id}")
                status = str(order.get("status") or "").upper()
                if status == "FILLED" and filled_qty != ordered_qty:
                    issues.append(f"RUNTIME_INVARIANT_FILLED_ORDER_QUANTITY_MISMATCH:{client_id}")
                if status == "PARTIALLY_FILLED" and not (0 < filled_qty < ordered_qty):
                    issues.append(f"RUNTIME_INVARIANT_PARTIAL_ORDER_QUANTITY_MISMATCH:{client_id}")
                if status == "REJECTED" and filled_qty:
                    issues.append(f"RUNTIME_INVARIANT_REJECTED_ORDER_HAS_FILLS:{client_id}")
            except (TypeError, ValueError):
                issues.append(f"RUNTIME_INVARIANT_ORDER_FILL_TOTAL_INVALID:{client_id}")

        ledger_result = None
        try:
            ledger_result = ValidationOnlyRuntimeLedgerComparator().compare(**dict(ledger_evidence))
            if ledger_result.status != "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED":
                issues.extend(ledger_result.issues or ("RUNTIME_INVARIANT_LEDGER_NOT_RECONCILED",))
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"RUNTIME_INVARIANT_LEDGER_EVIDENCE_INVALID:{exc!s}")

        if not isinstance(u19_decision, U19RecoveryDecision):
            issues.append("RUNTIME_INVARIANT_U19_DECISION_REQUIRED")
        else:
            decision_ids = [event.execution_id for event in u19_decision.execution_events]
            if len(decision_ids) != len(set(decision_ids)):
                issues.append("RUNTIME_INVARIANT_U19_EXECUTION_ID_DUPLICATE")
            if set(decision_ids) != unique_execution_ids:
                issues.append("RUNTIME_INVARIANT_U19_EXECUTION_ID_SET_MISMATCH")
            pending = tuple(u19_decision.pending_order_ids)
            if len(pending) != len(set(pending)):
                issues.append("RUNTIME_INVARIANT_U19_PENDING_ORDER_DUPLICATE")
            known_order_refs = {
                str(value).strip()
                for row in order_commands
                for value in (row.get("client_order_id"), row.get("broker_order_id"))
                if value is not None and str(value).strip()
            }
            if any(str(value).strip() not in known_order_refs for value in pending):
                issues.append("RUNTIME_INVARIANT_U19_PENDING_ORDER_NOT_IN_ORDER_SET")
            pending_refs = {str(value).strip() for value in pending}
            active_order_states = {
                "NEW", "SUBMITTED", "PENDING", "OPEN", "ACKNOWLEDGED",
                "PARTIALLY_FILLED", "CANCEL_PENDING", "REPLACE_PENDING",
                "UNKNOWN", "PENDING_RECONCILIATION",
            }
            terminal_order_states = {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}
            for client_id, order in orders_by_id.items():
                broker_id = str(order.get("broker_order_id") or "").strip()
                order_refs = {client_id, broker_id} - {""}
                status = str(order.get("status") or "").upper()
                if status in active_order_states and not order_refs.intersection(pending_refs):
                    issues.append(f"RUNTIME_INVARIANT_ACTIVE_ORDER_MISSING_FROM_U19_PENDING:{client_id}")
                if order_refs.intersection(pending_refs) and status in terminal_order_states:
                    issues.append(f"RUNTIME_INVARIANT_TERMINAL_ORDER_REPORTED_PENDING:{client_id}")
            if pending and u19_decision.status in {
                U19RecoveryStatus.RESTORE_ALLOWED, U19RecoveryStatus.FLAT_CONFIRMED,
            }:
                issues.append("RUNTIME_INVARIANT_PENDING_ORDER_WITH_ALLOWED_RECOVERY")
            if u19_decision.status is U19RecoveryStatus.FLAT_CONFIRMED:
                if u19_decision.positions or u19_decision.broker_positions or u19_decision.ledger_positions:
                    issues.append("RUNTIME_INVARIANT_FLAT_STATUS_HAS_POSITIONS")
                if pending or ledger_evidence.get("actual_open_position_lots"):
                    issues.append("RUNTIME_INVARIANT_FLAT_STATUS_HAS_OPEN_EXPOSURE")
                if ledger_evidence.get("vssf_positions"):
                    issues.append("RUNTIME_INVARIANT_FLAT_STATUS_HAS_VSSF_POSITIONS")
            elif u19_decision.status is U19RecoveryStatus.RESTORE_ALLOWED:
                if not u19_decision.positions:
                    issues.append("RUNTIME_INVARIANT_RESTORE_ALLOWED_WITHOUT_POSITIONS")
            elif u19_decision.restore_allowed or u19_decision.strategy_resume_allowed:
                issues.append("RUNTIME_INVARIANT_DENIED_RECOVERY_HAS_ALLOW_FLAGS")
            if u19_decision.restore_allowed != (u19_decision.status in {
                U19RecoveryStatus.RESTORE_ALLOWED, U19RecoveryStatus.FLAT_CONFIRMED,
            }):
                issues.append("RUNTIME_INVARIANT_U19_RESTORE_FLAG_STATUS_MISMATCH")
            if u19_decision.strategy_resume_allowed != u19_decision.restore_allowed:
                issues.append("RUNTIME_INVARIANT_U19_RESUME_FLAG_STATUS_MISMATCH")
            if u19_decision.new_entry_enabled or u19_decision.order_submission_enabled or u19_decision.runtime_restore_performed:
                issues.append("RUNTIME_INVARIANT_VALIDATION_ONLY_SIDE_EFFECT_FLAG_ENABLED")

        checks = {
            "provenance_and_time": "PASS" if not any(x.startswith("RUNTIME_INVARIANT_") and ("PROVENANCE" in x or "TIME" in x or "NAMESPACE" in x or "MANIFEST" in x) for x in issues) else "FAIL",
            "order_execution_lineage_and_quantity": "PASS" if not any("ORDER_" in x or "EXECUTION_" in x for x in issues) else "FAIL",
            "position_fee_vssf_ledger": "PASS" if ledger_result is not None and ledger_result.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED" else "FAIL",
            "u19_recovery_and_flat_state": "PASS" if not any("U19_" in x or "FLAT_" in x or "RESTORE_ALLOWED" in x or "OPEN_EXPOSURE" in x or "VSSF_POSITIONS" in x or "ALLOWED_RECOVERY" in x for x in issues) else "FAIL",
            "validation_only_no_side_effects": "PASS" if not any("SIDE_EFFECT" in x for x in issues) else "FAIL",
        }
        unique_issues = tuple(dict.fromkeys(issues))
        manifest = {
            "version": self.VERSION,
            "source_namespace": str(source_namespace),
            "deterministic_rule_id": str(deterministic_rule_id),
            "source_manifest_sha256": str(source_manifest_sha256).lower(),
            "source_anchor_refs": sorted(str(x) for x in source_anchor_refs),
            "source_anchor_as_of": anchor.isoformat() if anchor else None,
            "scenario_timestamp": scenario.isoformat() if scenario else None,
            "evidence_refs": sorted(str(x) for x in evidence_refs),
            "order_count": len(order_commands),
            "execution_row_count": len(executions),
            "unique_execution_count": len(unique_execution_ids),
            "u19_status": u19_decision.status.value if isinstance(u19_decision, U19RecoveryDecision) else None,
            "pending_order_count": len(u19_decision.pending_order_ids) if isinstance(u19_decision, U19RecoveryDecision) else None,
            "ledger_status": ledger_result.status if ledger_result is not None else None,
            "ledger_manifest_sha256": ledger_result.manifest_sha256 if ledger_result is not None else None,
            "checks": checks,
            "issues": list(unique_issues),
            "read_only": True,
            "new_entry_enabled": False,
            "order_submission_enabled": False,
            "runtime_restore_performed": False,
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return ValidationOnlyRuntimeInvariantReport(
            status=self.PASS if not unique_issues else self.RECONCILIATION_REQUIRED,
            issues=unique_issues,
            checks=checks,
            manifest=manifest,
            manifest_sha256=digest if not unique_issues else None,
        )
