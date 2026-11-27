from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class S4ExecutionStage(str, Enum):
    RECEIVED = "RECEIVED"
    ACCOUNT_APPLIED = "ACCOUNT_APPLIED"
    BRIDGE_APPLIED = "BRIDGE_APPLIED"
    CALLBACK_APPLIED = "CALLBACK_APPLIED"
    ACKED = "ACKED"


_STAGE_ORDER = {
    S4ExecutionStage.RECEIVED: 0,
    S4ExecutionStage.ACCOUNT_APPLIED: 1,
    S4ExecutionStage.BRIDGE_APPLIED: 2,
    S4ExecutionStage.CALLBACK_APPLIED: 3,
    S4ExecutionStage.ACKED: 4,
}
_REQUIRED_STATE_SECTIONS = frozenset({
    "account_state",
    "bridge_state",
    "strategy_state",
    "pending_orders",
    "position_lots",
    "fee_ledger",
    "execution_watermarks",
    "callback_state",
})


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)
    return value


def _canonical_json(payload: dict[str, Any], code: str) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise TypeError(code)
    try:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class S4ExecutionEventIdentity:
    """Synthetic validation event key; no fallback to client_order_id is allowed."""

    source_namespace: str
    account_id: str
    execution_source_id: str
    execution_id: str

    def __post_init__(self) -> None:
        _required_text(self.source_namespace, "S4_CHECKPOINT_EXECUTION_IDENTITY_REQUIRED")
        _required_text(self.account_id, "S4_CHECKPOINT_EXECUTION_IDENTITY_REQUIRED")
        _required_text(self.execution_source_id, "S4_CHECKPOINT_EXECUTION_IDENTITY_REQUIRED")
        _required_text(self.execution_id, "S4_CHECKPOINT_EXECUTION_IDENTITY_REQUIRED")
        if not self.source_namespace.startswith(("SYNTHETIC:", "VALIDATION_ONLY:")):
            raise ValueError("S4_CHECKPOINT_VALIDATION_NAMESPACE_REQUIRED")

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.source_namespace, self.account_id, self.execution_source_id, self.execution_id)

    def as_dict(self) -> dict[str, str]:
        return {
            "source_namespace": self.source_namespace,
            "account_id": self.account_id,
            "execution_source_id": self.execution_source_id,
            "execution_id": self.execution_id,
        }


class SqliteS4ValidationCheckpointStore:
    """Validation-only append-only inbox and atomic composite checkpoint journal.

    This store never submits orders. Callers persist RECEIVED before applying a
    projection, then commit a complete composite snapshot with each completed
    projection stage. After a process failure, callers must discard uncommitted
    in-memory objects and rebuild from the last committed snapshot before replay.
    """

    SCHEMA_VERSION = 1
    RUNTIME_USE = "PROHIBITED_OUTSIDE_VALIDATION"

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            if connection.in_transaction:
                connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS s4_execution_event (
                    source_namespace TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    execution_source_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    PRIMARY KEY (source_namespace, account_id, execution_source_id, execution_id)
                );

                CREATE TABLE IF NOT EXISTS s4_execution_event_stage (
                    source_namespace TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    execution_source_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    stage_order INTEGER NOT NULL,
                    checkpoint_id TEXT,
                    checkpoint_sha256 TEXT,
                    PRIMARY KEY (source_namespace, account_id, execution_source_id, execution_id, stage),
                    FOREIGN KEY (source_namespace, account_id, execution_source_id, execution_id)
                        REFERENCES s4_execution_event(source_namespace, account_id, execution_source_id, execution_id),
                    FOREIGN KEY (checkpoint_id) REFERENCES s4_checkpoint(checkpoint_id)
                );

                CREATE TABLE IF NOT EXISTS s4_checkpoint (
                    checkpoint_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    previous_checkpoint_id TEXT,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    UNIQUE (run_id, strategy_id, group_id, account_id, revision)
                );

                CREATE INDEX IF NOT EXISTS s4_checkpoint_scope_revision
                    ON s4_checkpoint(run_id, strategy_id, group_id, account_id, revision DESC);

                CREATE TRIGGER IF NOT EXISTS s4_event_no_update
                BEFORE UPDATE ON s4_execution_event
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS s4_event_no_delete
                BEFORE DELETE ON s4_execution_event
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS s4_stage_no_update
                BEFORE UPDATE ON s4_execution_event_stage
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS s4_stage_no_delete
                BEFORE DELETE ON s4_execution_event_stage
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS s4_checkpoint_no_update
                BEFORE UPDATE ON s4_checkpoint
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS s4_checkpoint_no_delete
                BEFORE DELETE ON s4_checkpoint
                BEGIN SELECT RAISE(ABORT, 'S4_CHECKPOINT_APPEND_ONLY'); END;
                """
            )

    @staticmethod
    def _identity_where(identity: S4ExecutionEventIdentity) -> tuple[str, tuple[str, ...]]:
        return (
            "source_namespace=? AND account_id=? AND execution_source_id=? AND execution_id=?",
            identity.as_tuple(),
        )

    @staticmethod
    def _validate_event_payload(payload: dict[str, Any]) -> tuple[str, str]:
        body, digest = _canonical_json(payload, "S4_EXECUTION_EVENT_PAYLOAD_INVALID")
        for key in ("run_id", "strategy_id", "group_id", "fingerprint", "client_order_id", "execution_timestamp"):
            _required_text(payload.get(key), "S4_EXECUTION_EVENT_PAYLOAD_INVALID")
        if payload.get("status") not in {"FILLED", "PARTIALLY_FILLED"}:
            raise ValueError("S4_EXECUTION_EVENT_STATUS_INVALID")
        filled = payload.get("filled_quantity")
        remaining = payload.get("remaining_quantity")
        if isinstance(filled, bool) or not isinstance(filled, int) or filled <= 0:
            raise ValueError("S4_EXECUTION_EVENT_QUANTITY_INVALID")
        if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
            raise ValueError("S4_EXECUTION_EVENT_QUANTITY_INVALID")
        try:
            event_time = datetime.fromisoformat(payload["execution_timestamp"])
        except ValueError as exc:
            raise ValueError("S4_EXECUTION_EVENT_TIME_INVALID") from exc
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError("S4_EXECUTION_EVENT_TIME_INVALID")
        return body, digest

    def record_received(self, identity: S4ExecutionEventIdentity, payload: dict[str, Any]) -> str:
        body, digest = self._validate_event_payload(payload)
        where, values = self._identity_where(identity)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT payload_json, payload_sha256 FROM s4_execution_event WHERE {where}", values,
            ).fetchone()
            if existing:
                if hashlib.sha256(existing[0].encode("utf-8")).hexdigest() != existing[1]:
                    raise ValueError("S4_EXECUTION_EVENT_INTEGRITY_FAILURE")
                if existing[1] != digest:
                    raise ValueError("S4_EXECUTION_ID_PAYLOAD_CONFLICT")
                return self._status_in_transaction(connection, identity)

            in_flight = connection.execute(
                """SELECT e.source_namespace, e.account_id, e.execution_source_id, e.execution_id
                   FROM s4_execution_event AS e
                   JOIN s4_execution_event_stage AS s
                     ON s.source_namespace=e.source_namespace AND s.account_id=e.account_id
                    AND s.execution_source_id=e.execution_source_id AND s.execution_id=e.execution_id
                   WHERE e.run_id=? AND e.strategy_id=? AND e.group_id=? AND e.account_id=?
                     AND s.stage_order=(
                         SELECT MAX(s2.stage_order) FROM s4_execution_event_stage AS s2
                         WHERE s2.source_namespace=e.source_namespace AND s2.account_id=e.account_id
                           AND s2.execution_source_id=e.execution_source_id AND s2.execution_id=e.execution_id
                     ) AND s.stage != ?
                   LIMIT 1""",
                (payload["run_id"], payload["strategy_id"], payload["group_id"],
                 identity.account_id, S4ExecutionStage.ACKED.value),
            ).fetchone()
            if in_flight is not None:
                raise ValueError("S4_GROUP_EVENT_IN_FLIGHT")

            prior_checkpoint = connection.execute(
                """SELECT payload_json FROM s4_checkpoint
                   WHERE run_id=? AND strategy_id=? AND group_id=? AND account_id=?
                   ORDER BY revision DESC LIMIT 1""",
                (payload["run_id"], payload["strategy_id"], payload["group_id"], identity.account_id),
            ).fetchone()
            if prior_checkpoint is not None:
                prior_payload = json.loads(prior_checkpoint[0])
                if (
                    prior_payload.get("source_namespace") != identity.source_namespace
                    or prior_payload.get("execution_source_id") != identity.execution_source_id
                ):
                    raise ValueError("S4_CHECKPOINT_EXECUTION_SOURCE_CHANGED")

            connection.execute(
                """INSERT INTO s4_execution_event
                   (source_namespace, account_id, execution_source_id, execution_id,
                    run_id, strategy_id, group_id, payload_json, payload_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*identity.as_tuple(), payload["run_id"], payload["strategy_id"],
                 payload["group_id"], body, digest),
            )
            connection.execute(
                """INSERT INTO s4_execution_event_stage
                   (source_namespace, account_id, execution_source_id, execution_id, stage, stage_order)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (*identity.as_tuple(), S4ExecutionStage.RECEIVED.value, _STAGE_ORDER[S4ExecutionStage.RECEIVED]),
            )
        return S4ExecutionStage.RECEIVED.value

    @staticmethod
    def _status_in_transaction(connection: sqlite3.Connection, identity: S4ExecutionEventIdentity) -> str:
        where, values = SqliteS4ValidationCheckpointStore._identity_where(identity)
        row = connection.execute(
            f"SELECT stage FROM s4_execution_event_stage WHERE {where} ORDER BY stage_order DESC LIMIT 1",
            values,
        ).fetchone()
        if row is None:
            raise ValueError("S4_EXECUTION_EVENT_STAGE_MISSING")
        return str(row[0])

    def get_event_status(self, identity: S4ExecutionEventIdentity) -> str | None:
        where, values = self._identity_where(identity)
        with self._connection() as connection:
            exists = connection.execute(
                f"SELECT 1 FROM s4_execution_event WHERE {where}", values,
            ).fetchone()
            if exists is None:
                return None
            return self._status_in_transaction(connection, identity)

    def _validate_checkpoint(
        self,
        identity: S4ExecutionEventIdentity,
        event_payload: dict[str, Any],
        stage: S4ExecutionStage,
        checkpoint: dict[str, Any],
    ) -> tuple[str, str]:
        body, digest = _canonical_json(checkpoint, "S4_CHECKPOINT_PAYLOAD_INVALID")
        if checkpoint.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("S4_CHECKPOINT_SCHEMA_UNSUPPORTED")
        if checkpoint.get("validation_only") is not True or checkpoint.get("runtime_use") != self.RUNTIME_USE:
            raise ValueError("S4_CHECKPOINT_VALIDATION_ONLY_REQUIRED")
        if checkpoint.get("phase") != stage.value:
            raise ValueError("S4_CHECKPOINT_PHASE_MISMATCH")
        for key in ("checkpoint_id", "run_id", "strategy_id", "group_id"):
            _required_text(checkpoint.get(key), "S4_CHECKPOINT_IDENTITY_REQUIRED")
        for key, value in identity.as_dict().items():
            if checkpoint.get(key) != value:
                raise ValueError("S4_CHECKPOINT_SCOPE_MISMATCH")
        for key in ("run_id", "strategy_id", "group_id"):
            if checkpoint.get(key) != event_payload.get(key):
                raise ValueError("S4_CHECKPOINT_SCOPE_MISMATCH")
        revision = checkpoint.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("S4_CHECKPOINT_REVISION_INVALID")
        previous = checkpoint.get("previous_checkpoint_id")
        if previous is not None and (not isinstance(previous, str) or not previous.strip()):
            raise ValueError("S4_CHECKPOINT_PREVIOUS_ID_INVALID")
        state = checkpoint.get("state")
        if not isinstance(state, dict) or not _REQUIRED_STATE_SECTIONS.issubset(state):
            raise ValueError("S4_CHECKPOINT_STATE_INCOMPLETE")
        return body, digest

    def commit_stage(
        self,
        identity: S4ExecutionEventIdentity,
        stage: S4ExecutionStage,
        checkpoint: dict[str, Any],
    ) -> None:
        if not isinstance(stage, S4ExecutionStage) or stage is S4ExecutionStage.RECEIVED:
            raise ValueError("S4_CHECKPOINT_STAGE_INVALID")
        where, values = self._identity_where(identity)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            event_row = connection.execute(
                f"SELECT payload_json, payload_sha256 FROM s4_execution_event WHERE {where}", values,
            ).fetchone()
            if event_row is None:
                raise ValueError("S4_EXECUTION_EVENT_NOT_RECEIVED")
            if hashlib.sha256(event_row[0].encode("utf-8")).hexdigest() != event_row[1]:
                raise ValueError("S4_EXECUTION_EVENT_INTEGRITY_FAILURE")
            event_payload = json.loads(event_row[0])
            body, digest = self._validate_checkpoint(identity, event_payload, stage, checkpoint)

            existing_checkpoint = connection.execute(
                "SELECT payload_sha256 FROM s4_checkpoint WHERE checkpoint_id=?",
                (checkpoint["checkpoint_id"],),
            ).fetchone()
            if existing_checkpoint is not None and existing_checkpoint[0] != digest:
                raise ValueError("S4_CHECKPOINT_ID_CONFLICT")

            existing_stage = connection.execute(
                f"SELECT checkpoint_id, checkpoint_sha256 FROM s4_execution_event_stage WHERE {where} AND stage=?",
                (*values, stage.value),
            ).fetchone()
            if existing_stage is not None:
                if existing_stage[0] != checkpoint["checkpoint_id"] or existing_stage[1] != digest:
                    raise ValueError("S4_CHECKPOINT_STAGE_CONFLICT")
                return

            current = self._status_in_transaction(connection, identity)
            current_stage = S4ExecutionStage(current)
            if _STAGE_ORDER[stage] != _STAGE_ORDER[current_stage] + 1:
                raise ValueError("S4_CHECKPOINT_STAGE_OUT_OF_ORDER")

            run_id, strategy_id, group_id = (
                checkpoint["run_id"], checkpoint["strategy_id"], checkpoint["group_id"],
            )
            latest = connection.execute(
                """SELECT checkpoint_id, revision, payload_json FROM s4_checkpoint
                   WHERE run_id=? AND strategy_id=? AND group_id=? AND account_id=?
                   ORDER BY revision DESC LIMIT 1""",
                (run_id, strategy_id, group_id, identity.account_id),
            ).fetchone()
            expected_revision = 1 if latest is None else int(latest[1]) + 1
            expected_previous = None if latest is None else str(latest[0])
            if latest is not None:
                prior_payload = json.loads(latest[2])
                if (
                    prior_payload.get("source_namespace") != identity.source_namespace
                    or prior_payload.get("execution_source_id") != identity.execution_source_id
                ):
                    raise ValueError("S4_CHECKPOINT_EXECUTION_SOURCE_CHANGED")
            if checkpoint["revision"] != expected_revision or checkpoint.get("previous_checkpoint_id") != expected_previous:
                raise ValueError("S4_CHECKPOINT_REVISION_CONFLICT")

            if existing_checkpoint is not None:
                raise ValueError("S4_CHECKPOINT_ID_ALREADY_USED")

            connection.execute(
                """INSERT INTO s4_checkpoint
                   (checkpoint_id, run_id, strategy_id, group_id, account_id, revision,
                    previous_checkpoint_id, payload_json, payload_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (checkpoint["checkpoint_id"], run_id, strategy_id, group_id, identity.account_id,
                 checkpoint["revision"], expected_previous, body, digest),
            )
            connection.execute(
                """INSERT INTO s4_execution_event_stage
                   (source_namespace, account_id, execution_source_id, execution_id,
                    stage, stage_order, checkpoint_id, checkpoint_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (*identity.as_tuple(), stage.value, _STAGE_ORDER[stage], checkpoint["checkpoint_id"], digest),
            )

    def load_latest_checkpoint(
        self, run_id: str, strategy_id: str, group_id: str, account_id: str,
    ) -> dict[str, Any] | None:
        for value in (run_id, strategy_id, group_id, account_id):
            _required_text(value, "S4_CHECKPOINT_SCOPE_REQUIRED")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT checkpoint_id, revision, previous_checkpoint_id, payload_json, payload_sha256
                   FROM s4_checkpoint WHERE run_id=? AND strategy_id=? AND group_id=? AND account_id=?
                   ORDER BY revision ASC""",
                (run_id, strategy_id, group_id, account_id),
            ).fetchall()
        if not rows:
            return None
        previous_id = None
        latest_payload = None
        for expected_revision, row in enumerate(rows, start=1):
            checkpoint_id, revision, previous_checkpoint_id, body, expected_digest = row
            if revision != expected_revision or previous_checkpoint_id != previous_id:
                raise ValueError("S4_CHECKPOINT_CHAIN_INVALID")
            if hashlib.sha256(body.encode("utf-8")).hexdigest() != expected_digest:
                raise ValueError("S4_CHECKPOINT_INTEGRITY_FAILURE")
            payload = json.loads(body)
            if payload.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("S4_CHECKPOINT_SCHEMA_UNSUPPORTED")
            if (
                payload.get("checkpoint_id") != checkpoint_id
                or payload.get("revision") != revision
                or payload.get("previous_checkpoint_id") != previous_checkpoint_id
                or payload.get("run_id") != run_id
                or payload.get("strategy_id") != strategy_id
                or payload.get("group_id") != group_id
                or payload.get("account_id") != account_id
            ):
                raise ValueError("S4_CHECKPOINT_SCOPE_MISMATCH")
            previous_id = checkpoint_id
            latest_payload = payload
        return latest_payload

    def pending_events(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT e.source_namespace, e.account_id, e.execution_source_id, e.execution_id,
                          e.payload_json, e.payload_sha256, s.stage
                   FROM s4_execution_event AS e
                   JOIN s4_execution_event_stage AS s
                     ON s.source_namespace=e.source_namespace AND s.account_id=e.account_id
                    AND s.execution_source_id=e.execution_source_id AND s.execution_id=e.execution_id
                   WHERE s.stage_order=(
                       SELECT MAX(s2.stage_order) FROM s4_execution_event_stage AS s2
                       WHERE s2.source_namespace=e.source_namespace AND s2.account_id=e.account_id
                         AND s2.execution_source_id=e.execution_source_id AND s2.execution_id=e.execution_id
                   ) AND s.stage != ?
                   ORDER BY e.rowid""",
                (S4ExecutionStage.ACKED.value,),
            ).fetchall()
        result = []
        for source, account, execution_source, execution_id, body, expected_digest, stage in rows:
            if hashlib.sha256(body.encode("utf-8")).hexdigest() != expected_digest:
                raise ValueError("S4_EXECUTION_EVENT_INTEGRITY_FAILURE")
            current_stage = S4ExecutionStage(stage)
            next_stage = next(
                (candidate.value for candidate, order in _STAGE_ORDER.items()
                 if order == _STAGE_ORDER[current_stage] + 1),
                None,
            )
            result.append({
                "identity": {
                    "source_namespace": source,
                    "account_id": account,
                    "execution_source_id": execution_source,
                    "execution_id": execution_id,
                },
                "payload": json.loads(body),
                "stage": stage,
                "next_stage": next_stage,
            })
        return result

class ValidationOnlyS4CheckpointCoordinator:
    """Single validation-only owner for event receipt, stage ACK and recovery work."""

    def __init__(self, store: SqliteS4ValidationCheckpointStore) -> None:
        if not isinstance(store, SqliteS4ValidationCheckpointStore):
            raise TypeError("S4_CHECKPOINT_STORE_REQUIRED")
        self.store = store

    def receive_execution(self, identity: S4ExecutionEventIdentity, payload: dict[str, Any]) -> str:
        return self.store.record_received(identity, payload)

    def commit_projection(
        self,
        identity: S4ExecutionEventIdentity,
        stage: S4ExecutionStage,
        complete_state_checkpoint: dict[str, Any],
    ) -> None:
        self.store.commit_stage(identity, stage, complete_state_checkpoint)

    def recovery_work(self) -> list[dict[str, Any]]:
        """Describe the next required stage; deliberately performs no automatic replay."""
        work = self.store.pending_events()
        for item in work:
            payload = item["payload"]
            item["last_committed_checkpoint"] = self.store.load_latest_checkpoint(
                payload["run_id"], payload["strategy_id"], payload["group_id"],
                item["identity"]["account_id"],
            )
        return work
