from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from contracts.market_data_freshness import FreshnessStatus
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel
from core.oms.track2_u19_recovery import U19RecoveryDecision, U19RecoveryStatus


@dataclass(frozen=True)
class ValidationOnlyRuntimeStopSwitchSnapshot:
    status: str
    reasons: tuple[str, ...]
    tripped_at: datetime | None
    trigger_count: int
    risk_guard_latched: bool
    risk_engine_latched: bool
    latch_errors: tuple[str, ...]
    latch_confirmed: bool
    order_admission_blocked: bool
    cancel_orders_requested: bool = False
    flatten_positions_requested: bool = False
    runtime_stop_requested: bool = False
    reset_supported: bool = False
    persistence_confirmed: bool = False


@dataclass(frozen=True)
class PersistedRuntimeStopState:
    tripped_at: datetime
    reasons: tuple[str, ...]


class RuntimeStopSwitchStateStore(Protocol):
    def load(self) -> PersistedRuntimeStopState | None:
        ...

    def trip(self, reason: str, tripped_at: datetime) -> PersistedRuntimeStopState:
        ...


class SqliteRuntimeStopSwitchStateStore:
    """Durable, append-only validation-only stop latch. There is no reset API."""

    TABLE = "validation_only_runtime_stop_switch"
    KEY = "X2"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {self.TABLE} ("
                "switch_key TEXT PRIMARY KEY, tripped_at TEXT NOT NULL, "
                "reasons_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    def load(self) -> PersistedRuntimeStopState | None:
        with sqlite3.connect(self.path, timeout=10) as connection:
            row = connection.execute(
                f"SELECT tripped_at, reasons_json FROM {self.TABLE} WHERE switch_key = ?",
                (self.KEY,),
            ).fetchone()
        if row is None:
            return None
        reasons = json.loads(row[1])
        if not isinstance(reasons, list) or not reasons or any(not str(x).strip() for x in reasons):
            raise ValueError("X2_PERSISTED_STOP_REASONS_INVALID")
        tripped_at = datetime.fromisoformat(str(row[0]))
        if tripped_at.tzinfo is None or tripped_at.utcoffset() is None:
            raise ValueError("X2_PERSISTED_STOP_TIMESTAMP_INVALID")
        return PersistedRuntimeStopState(tripped_at, tuple(dict.fromkeys(str(x) for x in reasons)))

    def trip(self, reason: str, tripped_at: datetime) -> PersistedRuntimeStopState:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ValueError("X2_STOP_REASON_REQUIRED")
        if tripped_at.tzinfo is None or tripped_at.utcoffset() is None:
            raise ValueError("X2_STOP_TIMESTAMP_TIMEZONE_REQUIRED")
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT tripped_at, reasons_json FROM {self.TABLE} WHERE switch_key = ?",
                (self.KEY,),
            ).fetchone()
            if row is None:
                original_time = tripped_at
                reasons = [normalized]
                connection.execute(
                    f"INSERT INTO {self.TABLE} (switch_key, tripped_at, reasons_json, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (self.KEY, original_time.isoformat(), json.dumps(reasons), datetime.now(UTC).isoformat()),
                )
            else:
                original_time = datetime.fromisoformat(str(row[0]))
                reasons = json.loads(row[1])
                if normalized not in reasons:
                    reasons.append(normalized)
                    connection.execute(
                        f"UPDATE {self.TABLE} SET reasons_json = ?, updated_at = ? WHERE switch_key = ?",
                        (json.dumps(reasons), datetime.now(UTC).isoformat(), self.KEY),
                    )
            connection.execute("COMMIT")
        return PersistedRuntimeStopState(original_time, tuple(reasons))


class ValidationOnlyRuntimeAutoStopSwitch:
    """Latch validation-only order-admission stop on any safety-evidence failure.

    The adapter engages the existing RiskGuard and RiskEngine kill-switches.
    It never cancels orders, flattens positions, stops the RuntimeController,
    enables Live execution, or resets itself automatically.
    """

    VERSION = "Q25-A8-TRACK4-T3-X2-v1"

    def __init__(
        self, *, risk_guard: Any, risk_engine: Any,
        state_store: RuntimeStopSwitchStateStore,
    ) -> None:
        required_guard = ("engage", "evaluate", "snapshot")
        required_engine = ("trigger_kill_switch", "is_kill_switch_active")
        if any(not callable(getattr(risk_guard, name, None)) for name in required_guard):
            raise TypeError("X2_RISK_GUARD_DEPENDENCY_INVALID")
        if any(not callable(getattr(risk_engine, name, None)) for name in required_engine):
            raise TypeError("X2_RISK_ENGINE_DEPENDENCY_INVALID")
        if not callable(getattr(state_store, "load", None)) or not callable(getattr(state_store, "trip", None)):
            raise TypeError("X2_STOP_STATE_STORE_DEPENDENCY_INVALID")
        self._risk_guard = risk_guard
        self._risk_engine = risk_engine
        self._state_store = state_store
        self._tripped_at: datetime | None = None
        self._reasons: list[str] = []
        self._latch_errors: list[str] = []
        self._persistence_confirmed = False
        try:
            persisted = self._state_store.load()
            self._persistence_confirmed = True
            if persisted is not None:
                self._tripped_at = persisted.tripped_at
                self._reasons = list(persisted.reasons)
                self._apply_latches(self._reasons[0])
        except Exception as exc:  # noqa: BLE001 - fail-closed safety latch
            self._latch_errors.append(f"STOP_STATE_LOAD_FAILED:{type(exc).__name__}")
            self._tripped_at = datetime.now(UTC)
            self._reasons = ["X2_STOP_STATE_STORE_UNAVAILABLE"]
            self._apply_latches(self._reasons[0])

    @staticmethod
    def _status(value: Any) -> str:
        return str(getattr(value, "value", value) or "").upper()

    @staticmethod
    def _aware(value: Any) -> bool:
        return (
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() is not None
        )

    def _record_latch_error(self, code: str, exc: Exception) -> None:
        message = f"{code}:{type(exc).__name__}"
        if message not in self._latch_errors:
            self._latch_errors.append(message)

    def _apply_latches(self, reason: str) -> None:
        guard_latched = False
        try:
            guard_snapshot = self._risk_guard.snapshot()
            guard_latched = bool(
                guard_snapshot is not None
                and not guard_snapshot.admission_allowed
                and guard_snapshot.kill_switch_engaged
            )
        except Exception as exc:  # noqa: BLE001 - keep attempting the guard and engine latches
            self._record_latch_error("RISK_GUARD_STATUS_READ_FAILED", exc)
        if not guard_latched:
            try:
                self._risk_guard.engage(reason)
            except Exception as exc:  # noqa: BLE001 - keep attempting the independent status refresh
                self._record_latch_error("RISK_GUARD_ENGAGE_FAILED", exc)
            try:
                self._risk_guard.evaluate(health=None, kill_switch_engaged=True)
            except Exception as exc:  # noqa: BLE001 - fail-closed safety latch
                self._record_latch_error("RISK_GUARD_STATUS_REFRESH_FAILED", exc)
        try:
            if not self._risk_engine.is_kill_switch_active():
                self._risk_engine.trigger_kill_switch(reason)
        except Exception as exc:  # noqa: BLE001 - fail-closed safety latch
            self._record_latch_error("RISK_ENGINE_ENGAGE_FAILED", exc)

    def _engage(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ValueError("X2_STOP_REASON_REQUIRED")
        if normalized not in self._reasons:
            self._reasons.append(normalized)
        if self._tripped_at is not None:
            try:
                persisted = self._state_store.trip(normalized, self._tripped_at)
                self._tripped_at = persisted.tripped_at
                self._reasons = list(persisted.reasons)
                self._persistence_confirmed = True
            except Exception as exc:  # noqa: BLE001 - fail-closed safety latch
                self._record_latch_error("STOP_STATE_PERSIST_FAILED", exc)
                self._persistence_confirmed = False
            self._apply_latches(self._reasons[0])
            return
        now = datetime.now(UTC)
        self._tripped_at = now
        try:
            persisted = self._state_store.trip(normalized, now)
            self._tripped_at = persisted.tripped_at
            self._reasons = list(persisted.reasons)
            self._persistence_confirmed = True
        except Exception as exc:  # noqa: BLE001 - fail-closed safety latch
            self._latch_errors.append(f"STOP_STATE_PERSIST_FAILED:{type(exc).__name__}")
            self._persistence_confirmed = False
        self._apply_latches(normalized)

    def evaluate(
        self,
        *,
        invariant_report: Any,
        u19_decision: U19RecoveryDecision | None,
        risk_guard_snapshot: RiskGuardStatusSnapshot | None,
        freshness_verdict: Any,
        manual_stop_reason: str | None = None,
    ) -> ValidationOnlyRuntimeStopSwitchSnapshot:
        triggers: list[str] = []
        if invariant_report is None:
            triggers.append("X1_INVARIANT_REPORT_UNAVAILABLE")
        elif (
            self._status(getattr(invariant_report, "status", None)) != "VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS"
            or tuple(getattr(invariant_report, "issues", ()))
        ):
            triggers.append("X1_INVARIANT_CHECK_FAILED")

        if not isinstance(u19_decision, U19RecoveryDecision):
            triggers.append("U19_RECOVERY_DECISION_UNAVAILABLE")
        else:
            if u19_decision.status not in {
                U19RecoveryStatus.RESTORE_ALLOWED,
                U19RecoveryStatus.FLAT_CONFIRMED,
            }:
                triggers.append(f"U19_RECOVERY_NOT_ALLOWED:{u19_decision.status.value}")
            if u19_decision.pending_order_ids:
                triggers.append("U19_PENDING_ORDERS_PRESENT")
            if (
                not u19_decision.restore_allowed
                or not u19_decision.strategy_resume_allowed
                or u19_decision.new_entry_enabled
                or u19_decision.order_submission_enabled
                or u19_decision.runtime_restore_performed
            ):
                triggers.append("U19_RECOVERY_FLAGS_INCONSISTENT")

        if risk_guard_snapshot is None:
            triggers.append("RISK_GUARD_STATUS_UNAVAILABLE")
        else:
            if not self._aware(risk_guard_snapshot.observed_at):
                triggers.append("RISK_GUARD_TIMESTAMP_INVALID")
            if (
                not risk_guard_snapshot.admission_allowed
                or risk_guard_snapshot.kill_switch_engaged
                or risk_guard_snapshot.health_level is not SensorLevel.GREEN
            ):
                triggers.append(f"RISK_GUARD_BLOCKED:{risk_guard_snapshot.reason or 'UNKNOWN'}")
            if not str(risk_guard_snapshot.decision_version or "").strip():
                triggers.append("RISK_GUARD_DECISION_VERSION_MISSING")

        if freshness_verdict is None:
            triggers.append("MARKET_DATA_FRESHNESS_UNAVAILABLE")
        elif self._status(getattr(freshness_verdict, "status", None)) != FreshnessStatus.FRESH.value:
            triggers.append(
                f"MARKET_DATA_FRESHNESS_NOT_FRESH:{self._status(getattr(freshness_verdict, 'status', None)) or 'UNKNOWN'}"
            )

        if manual_stop_reason is not None:
            if not str(manual_stop_reason).strip():
                triggers.append("MANUAL_STOP_REASON_INVALID")
            else:
                triggers.append(f"MANUAL_STOP:{str(manual_stop_reason).strip()}")

        for reason in triggers:
            self._engage(reason)
        return self.snapshot()

    def trip(self, reason: str) -> ValidationOnlyRuntimeStopSwitchSnapshot:
        self._engage(reason)
        return self.snapshot()

    def snapshot(self) -> ValidationOnlyRuntimeStopSwitchSnapshot:
        tripped = self._tripped_at is not None
        if tripped:
            self._apply_latches(self._reasons[0] if self._reasons else "X2_STOP_LATCHED")
        try:
            guard_snapshot = self._risk_guard.snapshot()
            guard_latched = bool(
                guard_snapshot is not None
                and not guard_snapshot.admission_allowed
                and guard_snapshot.kill_switch_engaged
            )
        except Exception as exc:  # noqa: BLE001 - report unavailable latch state as false
            self._record_latch_error("RISK_GUARD_STATUS_READ_FAILED", exc)
            guard_latched = False
        try:
            engine_latched = bool(self._risk_engine.is_kill_switch_active())
        except Exception as exc:  # noqa: BLE001 - report unavailable latch state as false
            self._record_latch_error("RISK_ENGINE_STATUS_READ_FAILED", exc)
            engine_latched = False
        latch_confirmed = guard_latched or engine_latched
        return ValidationOnlyRuntimeStopSwitchSnapshot(
            status=("TRIPPED" if latch_confirmed else "TRIP_LATCH_FAILED") if tripped else "ARMED",
            reasons=tuple(self._reasons),
            tripped_at=self._tripped_at,
            trigger_count=len(self._reasons),
            risk_guard_latched=guard_latched,
            risk_engine_latched=engine_latched,
            latch_errors=tuple(self._latch_errors),
            latch_confirmed=latch_confirmed,
            order_admission_blocked=latch_confirmed,
            persistence_confirmed=self._persistence_confirmed,
        )


class ValidationOnlyRuntimeStopAdmissionSource:
    """Overlay X2's durable latch on the existing Virtual RiskGuard status source."""

    def __init__(self, base_source: Any, stop_switch: ValidationOnlyRuntimeAutoStopSwitch) -> None:
        if not callable(getattr(base_source, "snapshot", None)):
            raise TypeError("X2_BASE_RISK_GUARD_STATUS_SOURCE_REQUIRED")
        if not isinstance(stop_switch, ValidationOnlyRuntimeAutoStopSwitch):
            raise TypeError("X2_STOP_SWITCH_REQUIRED")
        self._base_source = base_source
        self._stop_switch = stop_switch

    def snapshot(self) -> RiskGuardStatusSnapshot | None:
        stop = self._stop_switch.snapshot()
        if stop.status == "ARMED":
            return self._base_source.snapshot()
        return RiskGuardStatusSnapshot(
            observed_at=datetime.now(UTC),
            admission_allowed=False,
            kill_switch_engaged=True,
            health_level=SensorLevel.RED,
            reason="X2_RUNTIME_STOP_LATCHED:" + ";".join(stop.reasons),
            decision_version=self._stop_switch.VERSION,
        )
