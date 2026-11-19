from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.oms.track2_u19_recovery import U19RecoveryDecision, U19RecoveryStatus


@dataclass(frozen=True)
class ValidationOnlyRuntimeEvidenceCandidate:
    """One fully-provenanced candidate assembled from accepted/original or synthetic evidence."""

    group_id: str
    broker_snapshot: Any
    ledger_snapshot: Any
    invariant_inputs: Mapping[str, Any]
    freshness_verdict: Any


@dataclass(frozen=True)
class RuntimeEvidenceSupervisionResult:
    candidate_source: str | None
    attempts: tuple[str, ...]
    invariant_report: Any
    u19_decision: U19RecoveryDecision | None
    stop_snapshot: Any


class ValidationOnlyRuntimeEvidenceSupervisor:
    """Reconcile evidence candidates before X2; never manufacture missing evidence.

    Providers are ordered: primary accepted/original evidence, a reconciliation
    provider that cross-checks Notion decisions and existing source lineage, then
    a provenance-preserving alternative (normally deterministic synthetic data).
    X2 is evaluated only after a candidate passes X1/U19/freshness, or after all
    candidates have been exhausted.
    """

    VERSION = "Q25-A8-TRACK4-T5-EVIDENCE-SUPERVISOR-v1"

    def __init__(
        self,
        *,
        stop_switch: Any,
        invariant_checker: Any,
        u19_recovery_coordinator: Any,
        risk_guard_status_source: Any,
        primary_provider: Callable[[Any], ValidationOnlyRuntimeEvidenceCandidate | None],
        reconciliation_provider: Callable[[Any, tuple[str, ...]], ValidationOnlyRuntimeEvidenceCandidate | None],
        alternative_provider: Callable[[Any, tuple[str, ...]], ValidationOnlyRuntimeEvidenceCandidate | None],
    ) -> None:
        if not callable(getattr(stop_switch, "evaluate", None)):
            raise TypeError("T5_X2_STOP_SWITCH_REQUIRED")
        if not callable(getattr(invariant_checker, "check", None)):
            raise TypeError("T5_X1_INVARIANT_CHECKER_REQUIRED")
        if not callable(getattr(u19_recovery_coordinator, "recover", None)):
            raise TypeError("T5_U19_RECOVERY_COORDINATOR_REQUIRED")
        if not callable(getattr(risk_guard_status_source, "snapshot", None)):
            raise TypeError("T5_RISK_GUARD_STATUS_SOURCE_REQUIRED")
        if not callable(primary_provider):
            raise TypeError("T5_PRIMARY_EVIDENCE_PROVIDER_REQUIRED")
        self.stop_switch = stop_switch
        self.invariant_checker = invariant_checker
        self.u19_recovery_coordinator = u19_recovery_coordinator
        self.risk_guard_status_source = risk_guard_status_source
        if not callable(reconciliation_provider):
            raise TypeError("T5_NOTION_SOURCE_RECONCILIATION_PROVIDER_REQUIRED")
        if not callable(alternative_provider):
            raise TypeError("T5_PROVENANCE_PRESERVING_ALTERNATIVE_PROVIDER_REQUIRED")
        self.providers = (
            ("PRIMARY_ACCEPTED_ORIGINAL", primary_provider),
            ("NOTION_AND_SOURCE_RECONCILIATION", reconciliation_provider),
            ("PROVENANCE_PRESERVING_ALTERNATIVE", alternative_provider),
        )

    @staticmethod
    def _candidate_is_valid(report: Any, decision: Any, freshness: Any) -> bool:
        if getattr(report, "status", None) != "VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS":
            return False
        if tuple(getattr(report, "issues", ())):
            return False
        if not isinstance(decision, U19RecoveryDecision):
            return False
        if decision.status not in {
            U19RecoveryStatus.RESTORE_ALLOWED,
            U19RecoveryStatus.FLAT_CONFIRMED,
        }:
            return False
        if (
            decision.pending_order_ids
            or not decision.restore_allowed
            or not decision.strategy_resume_allowed
            or decision.new_entry_enabled
            or decision.order_submission_enabled
            or decision.runtime_restore_performed
        ):
            return False
        return str(getattr(getattr(freshness, "status", None), "value", getattr(freshness, "status", ""))).upper() == "FRESH"

    def evaluate(self, tick: Any) -> RuntimeEvidenceSupervisionResult:
        attempts: list[str] = []
        selected: tuple[str, Any, Any, Any] | None = None
        for source_name, provider in self.providers:
            if provider is None:
                continue
            try:
                candidate = (
                    provider(tick)
                    if source_name == "PRIMARY_ACCEPTED_ORIGINAL"
                    else provider(tick, tuple(attempts))
                )
                if candidate is None:
                    attempts.append(f"{source_name}:EVIDENCE_UNAVAILABLE")
                    continue
                if not isinstance(candidate, ValidationOnlyRuntimeEvidenceCandidate):
                    attempts.append(f"{source_name}:EVIDENCE_CONTRACT_INVALID")
                    continue
                decision = self.u19_recovery_coordinator.recover(
                    group_id=candidate.group_id,
                    broker_snapshot=candidate.broker_snapshot,
                    ledger_snapshot=candidate.ledger_snapshot,
                )
                invariant_inputs = dict(candidate.invariant_inputs)
                invariant_inputs["u19_decision"] = decision
                report = self.invariant_checker.check(**invariant_inputs)
                if not self._candidate_is_valid(report, decision, candidate.freshness_verdict):
                    issues = tuple(getattr(report, "issues", ()))
                    attempts.append(
                        f"{source_name}:RECONCILIATION_REQUIRED:"
                        + (",".join(issues) if issues else decision.status.value)
                    )
                    continue
                selected = (source_name, candidate, decision, report)
                attempts.append(f"{source_name}:VALIDATED")
                break
            except Exception as exc:  # noqa: BLE001 - continue evidence reconciliation before X2
                attempts.append(f"{source_name}:PROVIDER_OR_VALIDATION_ERROR:{type(exc).__name__}")

        risk_guard_snapshot = None
        try:
            risk_guard_snapshot = self.risk_guard_status_source.snapshot()
        except Exception as exc:  # noqa: BLE001 - X2 receives unavailable evidence
            attempts.append(f"RISK_GUARD_STATUS_UNAVAILABLE:{type(exc).__name__}")

        if selected is None:
            stop = self.stop_switch.evaluate(
                invariant_report=None,
                u19_decision=None,
                risk_guard_snapshot=risk_guard_snapshot,
                freshness_verdict=None,
                manual_stop_reason="T5_EVIDENCE_RECONCILIATION_EXHAUSTED:" + "|".join(attempts),
            )
            return RuntimeEvidenceSupervisionResult(
                candidate_source=None,
                attempts=tuple(attempts),
                invariant_report=None,
                u19_decision=None,
                stop_snapshot=stop,
            )

        source_name, candidate, decision, report = selected
        stop = self.stop_switch.evaluate(
            invariant_report=report,
            u19_decision=decision,
            risk_guard_snapshot=risk_guard_snapshot,
            freshness_verdict=candidate.freshness_verdict,
        )
        return RuntimeEvidenceSupervisionResult(
            candidate_source=source_name,
            attempts=tuple(attempts),
            invariant_report=report,
            u19_decision=decision,
            stop_snapshot=stop,
        )
