"""Durable SQLite settlement journal for one local, single-writer Live runtime.

The database is the settlement source of truth. Market-data JSONL stores are
intentionally unrelated. This module never performs broker or KIS API calls.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class SettlementStoreError(RuntimeError):
    """Raised when durable settlement cannot be committed safely."""


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"__type__": "Decimal", "value": str(value)}
    if isinstance(value, (datetime, date)):
        return {"__type__": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, Enum):
        return {"__type__": "Enum", "value": value.value}
    if is_dataclass(value):
        return {
            "__type__": f"{type(value).__module__}.{type(value).__name__}",
            "fields": asdict(value),
        }
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"UNSUPPORTED_SETTLEMENT_VALUE:{type(value).__name__}")


def encode_record(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"))


class SQLiteSettlementStore:
    """SQLite journal and transactional projections for one active writer."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0) -> None:
        raw_path = str(path).strip()
        if not raw_path:
            raise ValueError("SETTLEMENT_DATABASE_PATH_REQUIRED")
        self.path = raw_path
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("SETTLEMENT_DATABASE_TIMEOUT_INVALID")
        if raw_path != ":memory:":
            Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_journal (
                    execution_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL,
                    broker_order_id TEXT,
                    report_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS order_states (
                    client_order_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS position_states (
                    instrument_id TEXT PRIMARY KEY,
                    position_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settlement_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reconciliation_state (
                    scope_key TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL,
                    broker_order_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','CONFLICT','RESOLVED')),
                    reason TEXT NOT NULL,
                    evidence_ref TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reconciliation_inbox (
                    inbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL UNIQUE,
                    scope_key TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    broker_order_id TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','RESOLVED','CONFLICT')),
                    payload_json TEXT NOT NULL,
                    evidence_ref TEXT,
                    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS validation_baseline_history (
                    generation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL CHECK(event_type IN ('INITIAL_IMPORT','VALIDATION_ONLY_RESET')),
                    previous_payload_sha256 TEXT,
                    new_payload_sha256 TEXT NOT NULL,
                    snapshot_ids_json TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    source TEXT NOT NULL,
                    reset_reason TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TRIGGER IF NOT EXISTS validation_baseline_history_no_update
                BEFORE UPDATE ON validation_baseline_history
                BEGIN SELECT RAISE(ABORT, 'VALIDATION_BASELINE_HISTORY_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS validation_baseline_history_no_delete
                BEFORE DELETE ON validation_baseline_history
                BEGIN SELECT RAISE(ABORT, 'VALIDATION_BASELINE_HISTORY_APPEND_ONLY'); END;
                CREATE TABLE IF NOT EXISTS startup_reconciliation_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL CHECK(event_type IN (
                        'GATE_REGISTERED','GATE_REARMED','GATE_REARM_BLOCKED_CONFLICT','STARTUP_RESOLVED'
                    )),
                    gate_status TEXT NOT NULL CHECK(gate_status IN ('PENDING','CONFLICT','RESOLVED')),
                    evidence_sha256 TEXT,
                    manifest_version TEXT,
                    baseline_evidence_sha256 TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TRIGGER IF NOT EXISTS startup_reconciliation_history_no_update
                BEFORE UPDATE ON startup_reconciliation_history
                BEGIN SELECT RAISE(ABORT, 'STARTUP_RECONCILIATION_HISTORY_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS startup_reconciliation_history_no_delete
                BEFORE DELETE ON startup_reconciliation_history
                BEGIN SELECT RAISE(ABORT, 'STARTUP_RECONCILIATION_HISTORY_APPEND_ONLY'); END;
                CREATE TABLE IF NOT EXISTS order_replacement_links (
                    link_id TEXT PRIMARY KEY,
                    original_client_order_id TEXT NOT NULL,
                    original_broker_order_id TEXT NOT NULL,
                    replacement_client_order_id TEXT NOT NULL UNIQUE,
                    replacement_broker_order_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    leg_id TEXT NOT NULL,
                    cancel_request_ref TEXT NOT NULL,
                    cancel_ack_ref TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TRIGGER IF NOT EXISTS order_replacement_links_no_update
                BEFORE UPDATE ON order_replacement_links
                BEGIN SELECT RAISE(ABORT, 'ORDER_REPLACEMENT_LINKS_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS order_replacement_links_no_delete
                BEFORE DELETE ON order_replacement_links
                BEGIN SELECT RAISE(ABORT, 'ORDER_REPLACEMENT_LINKS_APPEND_ONLY'); END;
                """
            )

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def save_order_state(self, client_order_id: str, state_payload: Mapping[str, Any]) -> None:
        key = str(client_order_id).strip()
        if not key:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        payload = encode_record(dict(state_payload))
        with self._connection() as connection:
            self._begin(connection)
            connection.execute(
                """INSERT INTO order_states(client_order_id,state_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(client_order_id) DO UPDATE SET
                     state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP""",
                (key, payload),
            )
            connection.commit()

    def load_order_state_payloads(self) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT state_json FROM order_states ORDER BY client_order_id"
            ).fetchall()
        return tuple(json.loads(row["state_json"]) for row in rows)

    def record_order_replacement_link(
        self,
        *,
        link_id: str,
        original_client_order_id: str,
        original_broker_order_id: str,
        replacement_client_order_id: str,
        replacement_broker_order_id: str,
        group_id: str,
        leg_id: str,
        cancel_request_ref: str,
        cancel_ack_ref: str,
        source: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Persist explicit order replacement lineage without inferring broker IDs."""
        values = {
            "link_id": link_id,
            "original_client_order_id": original_client_order_id,
            "original_broker_order_id": original_broker_order_id,
            "replacement_client_order_id": replacement_client_order_id,
            "replacement_broker_order_id": replacement_broker_order_id,
            "group_id": group_id,
            "leg_id": leg_id,
            "cancel_request_ref": cancel_request_ref,
            "cancel_ack_ref": cancel_ack_ref,
            "source": source,
        }
        normalized = {key: str(value or "").strip() for key, value in values.items()}
        if any(not value for value in normalized.values()):
            raise ValueError("ORDER_REPLACEMENT_LINEAGE_FIELDS_REQUIRED")
        if normalized["original_client_order_id"] == normalized["replacement_client_order_id"]:
            raise ValueError("ORDER_REPLACEMENT_SELF_LINK_INVALID")
        if normalized["cancel_request_ref"] == normalized["cancel_ack_ref"]:
            raise ValueError("ORDER_REPLACEMENT_CANCEL_REQUEST_ACK_MUST_DIFFER")
        encoded = encode_record(dict(payload))
        columns = tuple(normalized)
        with self._connection() as connection:
            self._begin(connection)
            existing = connection.execute(
                "SELECT * FROM order_replacement_links WHERE link_id=?",
                (normalized["link_id"],),
            ).fetchone()
            if existing is not None:
                identical = all(existing[key] == normalized[key] for key in columns) and existing["payload_json"] == encoded
                connection.rollback()
                if identical:
                    return False
                raise SettlementStoreError("ORDER_REPLACEMENT_LINK_ID_COLLISION")
            try:
                connection.execute(
                    """INSERT INTO order_replacement_links
                       (link_id,original_client_order_id,original_broker_order_id,
                        replacement_client_order_id,replacement_broker_order_id,group_id,leg_id,
                        cancel_request_ref,cancel_ack_ref,source,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(normalized[key] for key in columns) + (encoded,),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise SettlementStoreError("ORDER_REPLACEMENT_CLIENT_ALREADY_LINKED") from exc
            connection.commit()
            return True

    def load_order_replacement_links(self) -> tuple[dict[str, Any], ...]:
        """Read immutable original-to-replacement order lineage in insertion order."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT link_id,original_client_order_id,original_broker_order_id,
                          replacement_client_order_id,replacement_broker_order_id,group_id,leg_id,
                          cancel_request_ref,cancel_ack_ref,source,payload_json,created_at
                   FROM order_replacement_links ORDER BY rowid"""
            ).fetchall()
        return tuple({
            "link_id": row["link_id"],
            "original_client_order_id": row["original_client_order_id"],
            "original_broker_order_id": row["original_broker_order_id"],
            "replacement_client_order_id": row["replacement_client_order_id"],
            "replacement_broker_order_id": row["replacement_broker_order_id"],
            "group_id": row["group_id"],
            "leg_id": row["leg_id"],
            "cancel_request_ref": row["cancel_request_ref"],
            "cancel_ack_ref": row["cancel_ack_ref"],
            "source": row["source"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        } for row in rows)

    def load_execution_journal_records(self) -> tuple[dict[str, Any], ...]:
        """Read committed execution rows in SQLite insertion order without mutation."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT execution_id,client_order_id,broker_order_id,report_json,committed_at
                   FROM execution_journal ORDER BY rowid"""
            ).fetchall()
        return tuple({
            "execution_id": row["execution_id"],
            "client_order_id": row["client_order_id"],
            "broker_order_id": row["broker_order_id"],
            "report": json.loads(row["report_json"]),
            "report_json": row["report_json"],
            "committed_at": row["committed_at"],
        } for row in rows)

    def save_position_state(self, instrument_id: str, position_payload: Mapping[str, Any]) -> None:
        key = str(instrument_id).strip()
        if not key:
            raise ValueError("INSTRUMENT_ID_REQUIRED")
        payload = encode_record(dict(position_payload))
        with self._connection() as connection:
            self._begin(connection)
            connection.execute(
                """INSERT INTO position_states(instrument_id,position_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     position_json=excluded.position_json, updated_at=CURRENT_TIMESTAMP""",
                (key, payload),
            )
            connection.commit()

    def load_position_state(self, instrument_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT position_json FROM position_states WHERE instrument_id=?",
                (str(instrument_id).strip(),),
            ).fetchone()
        return None if row is None else json.loads(row["position_json"])

    def check_execution_duplicate(
        self,
        *,
        execution_id: str,
        client_order_id: str,
        broker_order_id: str | None,
        report_payload: Mapping[str, Any],
    ) -> bool:
        """Return True only for an identical replay; flag identity collisions."""
        key = str(execution_id).strip()
        client = str(client_order_id).strip()
        encoded = encode_record(dict(report_payload))
        with self._connection() as connection:
            row = connection.execute(
                "SELECT client_order_id,broker_order_id,report_json FROM execution_journal WHERE execution_id=?",
                (key,),
            ).fetchone()
        if row is None:
            return False
        if (
            row["client_order_id"] == client
            and row["broker_order_id"] == broker_order_id
            and row["report_json"] == encoded
        ):
            return True
        self.mark_reconciliation_pending(
            scope_key=client,
            client_order_id=client,
            broker_order_id=broker_order_id,
            reason="EXECUTION_ID_COLLISION",
            payload={"execution_id": key, "collision": True},
            conflict=True,
        )
        raise SettlementStoreError("EXECUTION_ID_COLLISION")

    def has_execution(self, execution_id: str) -> bool:
        key = str(execution_id).strip()
        if not key:
            return False
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM execution_journal WHERE execution_id=?", (key,)
            ).fetchone()
        return row is not None

    def commit_fill(
        self,
        *,
        execution_id: str,
        client_order_id: str,
        broker_order_id: str | None,
        report_payload: Mapping[str, Any],
        order_state_payload: Mapping[str, Any],
        position_payload: Mapping[str, Any],
        instrument_id: str,
        resolve_scope_key: str | None = None,
        authoritative_evidence_ref: str | None = None,
    ) -> bool:
        """Atomically journal a unique fill and update OMS/Position projections.

        Returns False for a duplicate execution ID; no projection is changed.
        Any exception rolls back the complete transaction.
        """
        execution_key = str(execution_id).strip()
        client_key = str(client_order_id).strip()
        instrument_key = str(instrument_id).strip()
        if not execution_key:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if not client_key:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        if not instrument_key:
            raise ValueError("INSTRUMENT_ID_REQUIRED")
        report_json = encode_record(dict(report_payload))
        order_json = encode_record(dict(order_state_payload))
        position_json = encode_record(dict(position_payload))
        connection = self._connect()
        try:
            self._begin(connection)
            cursor = connection.execute(
                """INSERT INTO execution_journal
                   (execution_id,client_order_id,broker_order_id,report_json)
                   VALUES(?,?,?,?) ON CONFLICT(execution_id) DO NOTHING""",
                (execution_key, client_key, broker_order_id, report_json),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT client_order_id,broker_order_id,report_json FROM execution_journal WHERE execution_id=?",
                    (execution_key,),
                ).fetchone()
                connection.rollback()
                if (
                    existing is not None
                    and existing["client_order_id"] == client_key
                    and existing["broker_order_id"] == broker_order_id
                    and existing["report_json"] == report_json
                ):
                    return False
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """INSERT INTO reconciliation_state
                           (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                           VALUES(?,?,?,'CONFLICT','EXECUTION_ID_COLLISION',?,CURRENT_TIMESTAMP)
                           ON CONFLICT(scope_key) DO UPDATE SET status='CONFLICT',
                             reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                             updated_at=CURRENT_TIMESTAMP""",
                        (client_key, client_key, broker_order_id,
                         encode_record({"execution_id": execution_key, "collision": True})),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                raise SettlementStoreError("EXECUTION_ID_COLLISION")
            connection.execute(
                """INSERT INTO order_states(client_order_id,state_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(client_order_id) DO UPDATE SET
                     state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP""",
                (client_key, order_json),
            )
            connection.execute(
                """INSERT INTO position_states(instrument_id,position_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     position_json=excluded.position_json, updated_at=CURRENT_TIMESTAMP""",
                (instrument_key, position_json),
            )
            if resolve_scope_key is not None:
                scope = str(resolve_scope_key).strip()
                evidence = str(authoritative_evidence_ref or "").strip()
                if not scope or not evidence:
                    raise ValueError("AUTHORITATIVE_RECONCILIATION_EVIDENCE_REQUIRED")
                connection.execute(
                    """UPDATE reconciliation_inbox SET status='RESOLVED', evidence_ref=?
                       WHERE execution_id=? AND scope_key=? AND status='PENDING'""",
                    (evidence, execution_key, scope),
                )
                remaining_inbox = connection.execute(
                    "SELECT COUNT(*) AS n FROM reconciliation_inbox WHERE scope_key=? AND status IN ('PENDING','CONFLICT')",
                    (scope,),
                ).fetchone()["n"]
                if remaining_inbox == 0:
                    state = connection.execute(
                        "SELECT status FROM reconciliation_state WHERE scope_key=?",
                        (scope,),
                    ).fetchone()
                    if state is None or state["status"] == "CONFLICT":
                        raise SettlementStoreError("RECONCILIATION_SCOPE_CONFLICT_REQUIRES_MANUAL_REVIEW")
                    resolved = connection.execute(
                        """UPDATE reconciliation_state
                           SET status='RESOLVED', evidence_ref=?, updated_at=CURRENT_TIMESTAMP
                           WHERE scope_key=? AND status='PENDING'""",
                        (evidence, scope),
                    )
                    if resolved.rowcount != 1:
                        raise SettlementStoreError("UNRESOLVED_RECONCILIATION_NOT_FOUND")
            connection.commit()
            return True
        except Exception as exc:
            connection.rollback()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO reconciliation_state
                       (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                       VALUES(?,?,?,'CONFLICT','SETTLEMENT_TRANSACTION_FAILED',?,CURRENT_TIMESTAMP)
                       ON CONFLICT(scope_key) DO UPDATE SET status='CONFLICT',
                         reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                         updated_at=CURRENT_TIMESTAMP""",
                    (client_key, client_key, broker_order_id,
                     encode_record({"execution_id": execution_key, "error_type": type(exc).__name__})),
                )
                connection.commit()
            except Exception:
                connection.rollback()
            raise SettlementStoreError("SETTLEMENT_TRANSACTION_FAILED") from exc
        finally:
            connection.close()

    def record_reconciliation_event_pending(
        self,
        *,
        event_id: str,
        client_order_id: str,
        broker_order_id: str | None,
        event_kind: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Persist a non-fill recovery event for explicit later reconciliation."""
        event_key = str(event_id).strip()
        client_key = str(client_order_id).strip()
        kind = str(event_kind).strip()
        if not event_key or not client_key or not kind:
            raise ValueError("RECONCILIATION_EVENT_IDENTITY_AND_KIND_REQUIRED")
        scope = client_key
        payload_record = dict(payload)
        payload_record["reconciliation_event_kind"] = kind
        encoded = encode_record(payload_record)
        with self._connection() as connection:
            self._begin(connection)
            existing = connection.execute(
                "SELECT scope_key,client_order_id,broker_order_id,payload_json "
                "FROM reconciliation_inbox WHERE execution_id=?",
                (event_key,),
            ).fetchone()
            if existing is not None:
                identical = (
                    existing["scope_key"] == scope
                    and existing["client_order_id"] == client_key
                    and existing["broker_order_id"] == broker_order_id
                    and existing["payload_json"] == encoded
                )
                if identical:
                    connection.rollback()
                    return False
                connection.execute(
                    "UPDATE reconciliation_inbox SET status='CONFLICT' WHERE execution_id=?",
                    (event_key,),
                )
                connection.execute(
                    """INSERT INTO reconciliation_state
                       (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                       VALUES(?,?,?,'CONFLICT','RECONCILIATION_EVENT_ID_COLLISION',?,CURRENT_TIMESTAMP)
                       ON CONFLICT(scope_key) DO UPDATE SET status='CONFLICT',
                         reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                         updated_at=CURRENT_TIMESTAMP""",
                    (scope, client_key, broker_order_id,
                     encode_record({"event_id": event_key, "event_kind": kind, "collision": True})),
                )
                connection.commit()
                raise SettlementStoreError("RECONCILIATION_EVENT_ID_COLLISION")

            connection.execute(
                """INSERT INTO reconciliation_inbox
                   (execution_id,scope_key,client_order_id,broker_order_id,payload_json)
                   VALUES(?,?,?,?,?)""",
                (event_key, scope, client_key, broker_order_id, encoded),
            )
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                   VALUES(?,?,?,'PENDING',?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET
                     client_order_id=excluded.client_order_id,
                     broker_order_id=excluded.broker_order_id,
                     status=CASE WHEN reconciliation_state.status='CONFLICT' THEN 'CONFLICT' ELSE 'PENDING' END,
                     reason=CASE WHEN reconciliation_state.status='CONFLICT' THEN reconciliation_state.reason ELSE excluded.reason END,
                     evidence_ref=NULL, payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (scope, client_key, broker_order_id,
                 f"{kind}_REQUIRES_AUTHORITATIVE_RECONCILIATION",
                 encode_record({"reconciliation_event_id": event_key, "event_kind": kind})),
            )
            connection.commit()
            return True

    def resolve_reconciliation_event(
        self,
        *,
        event_id: str,
        scope_key: str,
        evidence_ref: str,
    ) -> bool:
        """Resolve one pending REST snapshot only after an external evidence reference is supplied."""
        event_key = str(event_id).strip()
        scope = str(scope_key).strip()
        evidence = str(evidence_ref).strip()
        if not event_key or not scope or not evidence:
            raise ValueError("RECONCILIATION_EVENT_EVIDENCE_FIELDS_REQUIRED")
        with self._connection() as connection:
            self._begin(connection)
            row = connection.execute(
                """SELECT status,scope_key,payload_json FROM reconciliation_inbox
                   WHERE execution_id=?""",
                (event_key,),
            ).fetchone()
            if row is None or row["scope_key"] != scope:
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_EVENT_NOT_FOUND")
            if row["status"] == "RESOLVED":
                connection.rollback()
                return False
            if row["status"] == "CONFLICT":
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_EVENT_CONFLICT_REQUIRES_MANUAL_REVIEW")
            payload = json.loads(row["payload_json"])
            if payload.get("reconciliation_event_kind") != "KIS_REST_CUMULATIVE_ORDER_SNAPSHOT":
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_EVENT_KIND_NOT_EXTERNALLY_RESOLVABLE")
            state = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key=?",
                (scope,),
            ).fetchone()
            if state is None:
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_SCOPE_STATE_MISSING")
            if state["status"] == "CONFLICT":
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_SCOPE_CONFLICT_REQUIRES_MANUAL_REVIEW")
            if state["status"] != "PENDING":
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_SCOPE_NOT_PENDING")
            connection.execute(
                """UPDATE reconciliation_inbox SET status='RESOLVED',evidence_ref=?
                   WHERE execution_id=? AND scope_key=? AND status='PENDING'""",
                (evidence, event_key, scope),
            )
            remaining = connection.execute(
                """SELECT COUNT(*) AS n FROM reconciliation_inbox
                   WHERE scope_key=? AND status IN ('PENDING','CONFLICT')""",
                (scope,),
            ).fetchone()["n"]
            if remaining == 0:
                resolved = connection.execute(
                    """UPDATE reconciliation_state SET status='RESOLVED',evidence_ref=?,
                       updated_at=CURRENT_TIMESTAMP WHERE scope_key=? AND status='PENDING'""",
                    (evidence, scope),
                )
                if resolved.rowcount != 1:
                    raise SettlementStoreError("RECONCILIATION_SCOPE_RESOLUTION_FAILED")
            connection.commit()
            return True

    def record_late_fill_pending(
        self,
        *,
        execution_id: str,
        client_order_id: str,
        broker_order_id: str | None,
        payload: Mapping[str, Any],
    ) -> bool:
        """Append one late-fill event and keep its order reconciliation gate pending.

        Returns False for an identical replay. A reused execution ID with a
        different order identity or payload is retained as a reconciliation conflict.
        """
        execution_key = str(execution_id).strip()
        client_key = str(client_order_id).strip()
        if not execution_key or not client_key:
            raise ValueError("LATE_FILL_EVENT_IDENTITY_REQUIRED")
        scope = client_key
        encoded = encode_record(dict(payload))
        with self._connection() as connection:
            self._begin(connection)
            existing = connection.execute(
                "SELECT scope_key,client_order_id,broker_order_id,payload_json "
                "FROM reconciliation_inbox WHERE execution_id=?",
                (execution_key,),
            ).fetchone()
            if existing is not None:
                identical = (
                    existing["scope_key"] == scope
                    and existing["client_order_id"] == client_key
                    and existing["broker_order_id"] == broker_order_id
                    and existing["payload_json"] == encoded
                )
                if identical:
                    connection.rollback()
                    return False
                connection.execute(
                    "UPDATE reconciliation_inbox SET status='CONFLICT' WHERE execution_id=?",
                    (execution_key,),
                )
                connection.execute(
                    """INSERT INTO reconciliation_state
                       (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                       VALUES(?,?,?,'CONFLICT','RECONCILIATION_INBOX_EXECUTION_ID_COLLISION',?,CURRENT_TIMESTAMP)
                       ON CONFLICT(scope_key) DO UPDATE SET status='CONFLICT',
                         reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                         updated_at=CURRENT_TIMESTAMP""",
                    (scope, client_key, broker_order_id,
                     encode_record({"execution_id": execution_key, "collision": True})),
                )
                connection.commit()
                raise SettlementStoreError("RECONCILIATION_INBOX_EXECUTION_ID_COLLISION")

            connection.execute(
                """INSERT INTO reconciliation_inbox
                   (execution_id,scope_key,client_order_id,broker_order_id,payload_json)
                   VALUES(?,?,?,?,?)""",
                (execution_key, scope, client_key, broker_order_id, encoded),
            )
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                   VALUES(?,?,?,'PENDING','LATE_FILL_AFTER_CANCEL_REQUIRES_AUTHORITATIVE_RECONCILIATION',?,CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET
                     client_order_id=excluded.client_order_id,
                     broker_order_id=excluded.broker_order_id,
                     status=CASE WHEN reconciliation_state.status='CONFLICT' THEN 'CONFLICT' ELSE 'PENDING' END,
                     reason=CASE WHEN reconciliation_state.status='CONFLICT' THEN reconciliation_state.reason ELSE excluded.reason END,
                     evidence_ref=NULL, payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (scope, client_key, broker_order_id,
                 encode_record({"inbox_execution_id": execution_key})),
            )
            connection.commit()
            return True

    def open_reconciliation_events(
        self, *, scope_key: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return pending and conflicting inbox events for startup recovery gates."""
        with self._connection() as connection:
            if scope_key is None:
                rows = connection.execute(
                    """SELECT execution_id,scope_key,client_order_id,broker_order_id,status,payload_json,evidence_ref,received_at
                       FROM reconciliation_inbox WHERE status IN ('PENDING','CONFLICT') ORDER BY inbox_id"""
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT execution_id,scope_key,client_order_id,broker_order_id,status,payload_json,evidence_ref,received_at
                       FROM reconciliation_inbox WHERE scope_key=? AND status IN ('PENDING','CONFLICT') ORDER BY inbox_id""",
                    (str(scope_key).strip(),),
                ).fetchall()
        return tuple({
            "execution_id": row["execution_id"],
            "scope_key": row["scope_key"],
            "client_order_id": row["client_order_id"],
            "broker_order_id": row["broker_order_id"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
            "evidence_ref": row["evidence_ref"],
            "received_at": row["received_at"],
        } for row in rows)

    def pending_reconciliation_events(
        self, *, scope_key: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Read append-only late-fill events in deterministic receive order."""
        with self._connection() as connection:
            if scope_key is None:
                rows = connection.execute(
                    """SELECT execution_id,scope_key,client_order_id,broker_order_id,status,payload_json,evidence_ref,received_at
                       FROM reconciliation_inbox WHERE status='PENDING' ORDER BY inbox_id"""
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT execution_id,scope_key,client_order_id,broker_order_id,status,payload_json,evidence_ref,received_at
                       FROM reconciliation_inbox WHERE scope_key=? AND status='PENDING' ORDER BY inbox_id""",
                    (str(scope_key).strip(),),
                ).fetchall()
        return tuple({
            "execution_id": row["execution_id"],
            "scope_key": row["scope_key"],
            "client_order_id": row["client_order_id"],
            "broker_order_id": row["broker_order_id"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
            "evidence_ref": row["evidence_ref"],
            "received_at": row["received_at"],
        } for row in rows)

    def mark_reconciliation_pending(
        self,
        *,
        scope_key: str,
        client_order_id: str,
        broker_order_id: str | None,
        reason: str,
        payload: Mapping[str, Any],
        conflict: bool = False,
    ) -> None:
        scope = str(scope_key).strip()
        client = str(client_order_id).strip()
        why = str(reason).strip()
        if not scope or not client or not why:
            raise ValueError("RECONCILIATION_IDENTITY_AND_REASON_REQUIRED")
        status = "CONFLICT" if conflict else "PENDING"
        with self._connection() as connection:
            self._begin(connection)
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                   VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET
                     client_order_id=excluded.client_order_id,
                     broker_order_id=excluded.broker_order_id,
                     status=excluded.status, reason=excluded.reason,
                     evidence_ref=NULL, payload_json=excluded.payload_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (scope, client, broker_order_id, status, why, encode_record(dict(payload))),
            )
            connection.commit()

    def has_unresolved_reconciliation(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM reconciliation_state WHERE status IN ('PENDING','CONFLICT') LIMIT 1"
            ).fetchone()
        return row is not None

    def unresolved_reconciliations(self) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT scope_key,client_order_id,broker_order_id,status,reason,
                          evidence_ref,payload_json,updated_at
                   FROM reconciliation_state
                   WHERE status IN ('PENDING','CONFLICT') ORDER BY updated_at,scope_key"""
            ).fetchall()
        return tuple({
            "scope_key": row["scope_key"],
            "client_order_id": row["client_order_id"],
            "broker_order_id": row["broker_order_id"],
            "status": row["status"],
            "reason": row["reason"],
            "evidence_ref": row["evidence_ref"],
            "payload": json.loads(row["payload_json"]),
            "updated_at": row["updated_at"],
        } for row in rows)

    def establish_authoritative_baseline(
        self, *, position_payload: Mapping[str, Any], authoritative_evidence_ref: str
    ) -> None:
        """Persist an externally reconciled baseline and release the bootstrap gate."""
        instrument_id = str(position_payload.get("instrument_id", "")).strip()
        evidence = str(authoritative_evidence_ref).strip()
        if not instrument_id or not evidence:
            raise ValueError("AUTHORITATIVE_BASELINE_AND_EVIDENCE_REQUIRED")
        if int(position_payload.get("qty", -1)) < 0:
            raise ValueError("AUTHORITATIVE_BASELINE_POSITION_QUANTITY_INVALID")
        if int(position_payload.get("qty", 0)) > 0 and not position_payload.get("avg_price"):
            raise ValueError("AUTHORITATIVE_BASELINE_AVERAGE_PRICE_REQUIRED")
        connection = self._connect()
        try:
            self._begin(connection)
            bootstrap = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__runtime_bootstrap__'"
            ).fetchone()
            if bootstrap is not None and bootstrap["status"] == "CONFLICT":
                raise SettlementStoreError("RUNTIME_BOOTSTRAP_CONFLICT_REQUIRES_MANUAL_REVIEW")
            connection.execute(
                """INSERT INTO position_states(instrument_id,position_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     position_json=excluded.position_json,updated_at=CURRENT_TIMESTAMP""",
                (instrument_id, encode_record(dict(position_payload))),
            )
            connection.execute(
                """INSERT INTO settlement_meta(key,value,updated_at)
                   VALUES('authoritative_baseline_ready','1',CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value='1',updated_at=CURRENT_TIMESTAMP"""
            )
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,evidence_ref,payload_json,updated_at)
                   VALUES('__runtime_bootstrap__','__runtime_bootstrap__',NULL,'RESOLVED',
                          'AUTHORITATIVE_BASELINE_ESTABLISHED',?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET status='RESOLVED',reason=excluded.reason,
                     evidence_ref=excluded.evidence_ref,payload_json=excluded.payload_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (evidence, encode_record(dict(position_payload))),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise SettlementStoreError("AUTHORITATIVE_BASELINE_TRANSACTION_FAILED") from exc
        finally:
            connection.close()

    def authoritative_baseline_evidence(self) -> dict[str, Any] | None:
        """Return persisted baseline evidence without mutating settlement state."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_evidence'"
            ).fetchone()
        return json.loads(row["value"]) if row is not None else None

    def startup_reconciliation_evidence(self) -> dict[str, Any] | None:
        """Return persisted startup evidence without mutating settlement state."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settlement_meta WHERE key='startup_reconciliation_evidence'"
            ).fetchone()
        return json.loads(row["value"]) if row is not None else None

    def reconciliation_status(self, scope_key: str) -> str | None:
        """Read one reconciliation scope status without changing its gate."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key=?", (str(scope_key),)
            ).fetchone()
        return str(row["status"]) if row is not None else None

    def establish_authoritative_baseline_snapshot(self, **snapshot_kwargs: Any) -> None:
        """Create the first baseline; replacement requires the explicit validation-only reset API."""
        self._write_authoritative_baseline_snapshot(**snapshot_kwargs)

    def replace_validation_only_baseline_snapshot(
        self,
        *,
        expected_previous_payload_sha256: str,
        reset_reason: str,
        **snapshot_kwargs: Any,
    ) -> None:
        """Append a new validation-only baseline generation without discarding prior lineage."""
        self._write_authoritative_baseline_snapshot(
            **snapshot_kwargs,
            _validation_only_reset=True,
            _expected_previous_payload_sha256=expected_previous_payload_sha256,
            _reset_reason=reset_reason,
        )

    def validation_baseline_history(self) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT generation_id,event_type,previous_payload_sha256,new_payload_sha256,
                          snapshot_ids_json,as_of,source,reset_reason,payload_json,created_at
                   FROM validation_baseline_history ORDER BY generation_id"""
            ).fetchall()
        return tuple({
            "generation_id": row["generation_id"],
            "event_type": row["event_type"],
            "previous_payload_sha256": row["previous_payload_sha256"],
            "new_payload_sha256": row["new_payload_sha256"],
            "snapshot_ids": json.loads(row["snapshot_ids_json"]),
            "as_of": row["as_of"],
            "source": row["source"],
            "reset_reason": row["reset_reason"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        } for row in rows)

    def _write_authoritative_baseline_snapshot(
        self,
        *,
        positions_payload: Sequence[Mapping[str, Any]],
        orders_snapshot_id: str,
        executions_snapshot_id: str,
        positions_snapshot_id: str,
        as_of: datetime,
        source: str,
        payload_sha256: str,
        authoritative_evidence_ref: str,
        _validation_only_reset: bool = False,
        _expected_previous_payload_sha256: str | None = None,
        _reset_reason: str | None = None,
    ) -> None:
        """Atomically import or explicitly reset a multi-instrument validation baseline.

        This releases only the initial runtime bootstrap gate. The separate
        per-startup orders/fills/positions reconciliation gate remains pending.
        """
        snapshot_ids = tuple(str(value).strip() for value in (
            orders_snapshot_id, executions_snapshot_id, positions_snapshot_id
        ))
        source_value = str(source).strip()
        digest = str(payload_sha256).strip().lower()
        evidence = str(authoritative_evidence_ref).strip()
        if any(not value for value in snapshot_ids) or len(set(snapshot_ids)) != 3:
            raise ValueError("BASELINE_ORDERS_EXECUTIONS_POSITIONS_SNAPSHOT_IDS_REQUIRED_AND_DISTINCT")
        if not source_value or not evidence:
            raise ValueError("BASELINE_SOURCE_AND_EVIDENCE_REQUIRED")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("BASELINE_SNAPSHOT_AS_OF_MUST_BE_TIMEZONE_AWARE")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("BASELINE_SNAPSHOT_SHA256_INVALID")

        normalized_positions: list[dict[str, Any]] = []
        seen_instruments: set[str] = set()
        for raw in positions_payload:
            item = dict(raw)
            instrument_id = str(item.get("instrument_id") or "").strip()
            quantity = item.get("qty")
            side = item.get("side")
            average = item.get("avg_price")
            if not instrument_id or instrument_id in seen_instruments:
                raise ValueError("BASELINE_POSITION_INSTRUMENT_ID_MISSING_OR_DUPLICATE")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
                raise ValueError("BASELINE_POSITION_QUANTITY_INVALID")
            if quantity > 0 and (side not in {"LONG", "SHORT"} or average is None):
                raise ValueError("BASELINE_POSITION_SIDE_AND_AVERAGE_PRICE_REQUIRED")
            if quantity == 0 and side not in {None, "FLAT"}:
                raise ValueError("BASELINE_FLAT_POSITION_SIDE_INVALID")
            if average is not None:
                try:
                    average_value = Decimal(str(average))
                except (InvalidOperation, TypeError) as exc:
                    raise ValueError("BASELINE_POSITION_AVERAGE_PRICE_INVALID") from exc
                if not average_value.is_finite() or average_value <= 0:
                    raise ValueError("BASELINE_POSITION_AVERAGE_PRICE_INVALID")
                item["avg_price"] = str(average_value)
            item["instrument_id"] = instrument_id
            seen_instruments.add(instrument_id)
            normalized_positions.append(item)

        payload = {
            "source": source_value,
            "orders_snapshot_id": snapshot_ids[0],
            "executions_snapshot_id": snapshot_ids[1],
            "positions_snapshot_id": snapshot_ids[2],
            "as_of": as_of.isoformat(),
            "payload_sha256": digest,
            "evidence_ref": evidence,
            "position_count": len(normalized_positions),
            "positions": normalized_positions,
            "coverage": ["orders", "fills", "positions"],
        }
        encoded = encode_record(payload)
        connection = self._connect()
        try:
            self._begin(connection)
            bootstrap = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__runtime_bootstrap__'"
            ).fetchone()
            if bootstrap is not None and bootstrap["status"] == "CONFLICT":
                raise SettlementStoreError("RUNTIME_BOOTSTRAP_CONFLICT_REQUIRES_MANUAL_REVIEW")
            open_inbox = connection.execute(
                "SELECT COUNT(*) AS n FROM reconciliation_inbox WHERE status IN ('PENDING','CONFLICT')"
            ).fetchone()["n"]
            other_unresolved = connection.execute(
                """SELECT COUNT(*) AS n FROM reconciliation_state
                   WHERE status IN ('PENDING','CONFLICT')
                     AND scope_key NOT IN ('__runtime_bootstrap__','__startup_reconciliation__')"""
            ).fetchone()["n"]
            if open_inbox or other_unresolved:
                raise SettlementStoreError("BASELINE_IMPORT_HAS_OTHER_UNRESOLVED_RECONCILIATION")

            previous_row = connection.execute(
                "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_evidence'"
            ).fetchone()
            previous_payload = json.loads(previous_row["value"]) if previous_row is not None else None
            previous_digest = previous_payload.get("payload_sha256") if previous_payload else None
            if previous_payload is not None and not _validation_only_reset:
                raise SettlementStoreError("BASELINE_ALREADY_EXISTS_USE_EXPLICIT_VALIDATION_ONLY_RESET")
            if _validation_only_reset:
                if not source_value.startswith("VALIDATION_ONLY:"):
                    raise SettlementStoreError("BASELINE_RESET_VALIDATION_ONLY_SOURCE_REQUIRED")
                if previous_payload is None or not _expected_previous_payload_sha256:
                    raise SettlementStoreError("BASELINE_RESET_PREVIOUS_EVIDENCE_REQUIRED")
                if previous_digest != str(_expected_previous_payload_sha256).strip().lower():
                    raise SettlementStoreError("BASELINE_RESET_PREVIOUS_EVIDENCE_MISMATCH")
                if not str(_reset_reason or "").strip():
                    raise SettlementStoreError("BASELINE_RESET_REASON_REQUIRED")
                order_count = connection.execute("SELECT COUNT(*) AS n FROM order_states").fetchone()["n"]
                if order_count:
                    raise SettlementStoreError("BASELINE_RESET_PERSISTED_ORDERS_PRESENT")
                current_positions = {
                    row["instrument_id"]: json.loads(row["position_json"])
                    for row in connection.execute(
                        "SELECT instrument_id,position_json FROM position_states"
                    ).fetchall()
                }
                new_positions = {item["instrument_id"]: item for item in normalized_positions}
                if current_positions != new_positions:
                    raise SettlementStoreError("BASELINE_RESET_POSITION_STATE_CHANGE_REQUIRES_SEPARATE_RECONCILIATION")
                startup_gate = connection.execute(
                    "SELECT status FROM reconciliation_state WHERE scope_key='__startup_reconciliation__'"
                ).fetchone()
                if startup_gate is not None and startup_gate["status"] == "CONFLICT":
                    raise SettlementStoreError("BASELINE_RESET_STARTUP_CONFLICT_REQUIRES_MANUAL_REVIEW")

            connection.execute(
                """INSERT INTO validation_baseline_history
                   (event_type,previous_payload_sha256,new_payload_sha256,snapshot_ids_json,
                    as_of,source,reset_reason,payload_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    "VALIDATION_ONLY_RESET" if _validation_only_reset else "INITIAL_IMPORT",
                    previous_digest,
                    digest,
                    encode_record(list(snapshot_ids)),
                    as_of.isoformat(),
                    source_value,
                    str(_reset_reason).strip() if _validation_only_reset else None,
                    encoded,
                ),
            )
            connection.execute("DELETE FROM position_states")
            for item in normalized_positions:
                connection.execute(
                    """INSERT INTO position_states(instrument_id,position_json,updated_at)
                       VALUES(?,?,CURRENT_TIMESTAMP)""",
                    (item["instrument_id"], encode_record(item)),
                )
            connection.execute(
                """INSERT INTO settlement_meta(key,value,updated_at)
                   VALUES('authoritative_baseline_ready','1',CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value='1',updated_at=CURRENT_TIMESTAMP"""
            )
            connection.execute(
                """INSERT INTO settlement_meta(key,value,updated_at)
                   VALUES('authoritative_baseline_evidence',?,CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                (encoded,),
            )
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,evidence_ref,payload_json,updated_at)
                   VALUES('__runtime_bootstrap__','__runtime_bootstrap__',NULL,'RESOLVED',
                          'AUTHORITATIVE_MULTI_INSTRUMENT_BASELINE_ESTABLISHED',?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET status='RESOLVED',reason=excluded.reason,
                     evidence_ref=excluded.evidence_ref,payload_json=excluded.payload_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (evidence, encoded),
            )
            if _validation_only_reset:
                connection.execute(
                    """INSERT INTO reconciliation_state
                       (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                       VALUES('__startup_reconciliation__','__startup_reconciliation__',NULL,'PENDING',
                              'VALIDATION_ONLY_BASELINE_GENERATION_CHANGED',
                              '{"requirement":"orders_fills_positions"}',CURRENT_TIMESTAMP)
                       ON CONFLICT(scope_key) DO UPDATE SET status='PENDING',
                         reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                         updated_at=CURRENT_TIMESTAMP"""
                )
                connection.execute(
                    """INSERT INTO startup_reconciliation_history
                       (event_type,gate_status,baseline_evidence_sha256,payload_json)
                       VALUES('GATE_REARMED','PENDING',?,?)""",
                    (digest, encode_record({
                        "reason": "VALIDATION_ONLY_BASELINE_GENERATION_CHANGED",
                        "previous_baseline_evidence_sha256": previous_digest,
                        "new_baseline_evidence_sha256": digest,
                    })),
                )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            if isinstance(exc, (ValueError, SettlementStoreError)):
                raise
            raise SettlementStoreError("AUTHORITATIVE_BASELINE_SNAPSHOT_TRANSACTION_FAILED") from exc
        finally:
            connection.close()

    def startup_reconciliation_history(self) -> tuple[dict[str, Any], ...]:
        """Return append-only startup gate transitions and successful resolutions."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT event_id,event_type,gate_status,evidence_sha256,manifest_version,
                          baseline_evidence_sha256,payload_json,created_at
                   FROM startup_reconciliation_history ORDER BY event_id"""
            ).fetchall()
        return tuple({
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "gate_status": row["gate_status"],
            "evidence_sha256": row["evidence_sha256"],
            "manifest_version": row["manifest_version"],
            "baseline_evidence_sha256": row["baseline_evidence_sha256"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        } for row in rows)

    def validation_baseline_lineage_audit(self) -> dict[str, Any]:
        """Verify the append-only baseline generation chain against the current baseline."""
        history = self.validation_baseline_history()
        baseline = self.authoritative_baseline_evidence()
        current_digest = baseline.get("payload_sha256") if baseline else None
        previous_digest = None
        audited = []
        chain_valid = True
        for item in history:
            expected_previous = previous_digest
            payload_digest = item["payload"].get("payload_sha256")
            event_valid = (
                item["previous_payload_sha256"] == expected_previous
                and item["new_payload_sha256"] == payload_digest
                and item["source"].startswith("VALIDATION_ONLY:")
            )
            if item["event_type"] == "INITIAL_IMPORT":
                event_valid = event_valid and expected_previous is None
            elif item["event_type"] == "VALIDATION_ONLY_RESET":
                event_valid = event_valid and bool(item["reset_reason"])
            else:
                event_valid = False
            chain_valid = chain_valid and event_valid
            row = dict(item)
            row["lineage_status"] = "CHAIN_VALID" if event_valid else "BASELINE_HISTORY_CHAIN_MISMATCH"
            audited.append(row)
            previous_digest = item["new_payload_sha256"]
        current_matches = (
            (not history and current_digest is None)
            or (bool(history) and previous_digest == current_digest)
        )
        if not current_matches:
            chain_valid = False
        return {
            "generation_count": len(audited),
            "current_baseline_evidence_sha256": current_digest,
            "history_chain_valid": chain_valid,
            "current_baseline_matches_latest_generation": current_matches,
            "history": tuple(audited),
        }

    def startup_lineage_audit(self) -> dict[str, Any]:
        """Audit persisted startup lineage without changing gate or evidence state."""
        history = self.startup_reconciliation_history()
        baseline_history_audit = self.validation_baseline_lineage_audit()
        baseline = self.authoritative_baseline_evidence()
        current_baseline_hash = baseline.get("payload_sha256") if baseline else None
        audited = []
        for event in history:
            item = dict(event)
            if event["event_type"] != "STARTUP_RESOLVED":
                item["lineage_status"] = "GATE_TRANSITION"
            else:
                payload = event["payload"]
                manifest = payload.get("lineage_manifest")
                if not isinstance(manifest, dict):
                    status = "LEGACY_UNVERSIONED"
                elif manifest.get("manifest_version") != "Q25-A8-U19-BASELINE-STARTUP-LINEAGE-v1":
                    status = "UNSUPPORTED_MANIFEST_VERSION"
                elif hashlib.sha256(encode_record(manifest).encode("utf-8")).hexdigest() != event["evidence_sha256"]:
                    status = "MANIFEST_HASH_MISMATCH"
                elif manifest.get("baseline_import_evidence_sha256") != current_baseline_hash:
                    status = "BASELINE_EVIDENCE_CHANGED_SINCE_RESOLUTION"
                else:
                    status = "SUPPORTED_CURRENT_BASELINE"
                item["lineage_status"] = status
            audited.append(item)
        current_startup = self.startup_reconciliation_evidence()
        if current_startup is not None:
            current_digest = current_startup.get("payload_sha256")
            recorded = any(
                item["event_type"] == "STARTUP_RESOLVED"
                and item["evidence_sha256"] == current_digest
                for item in audited
            )
            if not recorded:
                manifest = current_startup.get("lineage_manifest")
                if not isinstance(manifest, dict):
                    legacy_status = "LEGACY_UNVERSIONED"
                elif manifest.get("manifest_version") != "Q25-A8-U19-BASELINE-STARTUP-LINEAGE-v1":
                    legacy_status = "UNSUPPORTED_MANIFEST_VERSION"
                elif hashlib.sha256(encode_record(manifest).encode("utf-8")).hexdigest() != current_digest:
                    legacy_status = "MANIFEST_HASH_MISMATCH"
                elif manifest.get("baseline_import_evidence_sha256") != current_baseline_hash:
                    legacy_status = "BASELINE_EVIDENCE_CHANGED_SINCE_RESOLUTION"
                else:
                    legacy_status = "SUPPORTED_CURRENT_BASELINE"
                audited.append({
                    "event_id": None,
                    "event_type": "LEGACY_EXISTING_EVIDENCE",
                    "gate_status": self.reconciliation_status("__startup_reconciliation__") or "UNREGISTERED",
                    "evidence_sha256": current_digest,
                    "manifest_version": manifest.get("manifest_version") if isinstance(manifest, dict) else None,
                    "baseline_evidence_sha256": (
                        manifest.get("baseline_import_evidence_sha256") if isinstance(manifest, dict) else None
                    ),
                    "payload": current_startup,
                    "created_at": None,
                    "lineage_status": legacy_status,
                })
        with self._connection() as connection:
            gate = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__startup_reconciliation__'"
            ).fetchone()
            open_inbox = connection.execute(
                "SELECT COUNT(*) AS n FROM reconciliation_inbox WHERE status IN ('PENDING','CONFLICT')"
            ).fetchone()["n"]
            unresolved = connection.execute(
                "SELECT COUNT(*) AS n FROM reconciliation_state WHERE status IN ('PENDING','CONFLICT')"
            ).fetchone()["n"]
        return {
            "current_gate_status": str(gate["status"]) if gate else "UNREGISTERED",
            "current_baseline_evidence_sha256": current_baseline_hash,
            "history_count": len(audited),
            "resolution_count": sum(item["event_type"] == "STARTUP_RESOLVED" for item in audited),
            "open_inbox_count": int(open_inbox),
            "unresolved_scope_count": int(unresolved),
            "baseline_lineage": baseline_history_audit,
            "history": tuple(audited),
        }

    def mark_startup_reconciliation_pending(self) -> None:
        """Require a fresh authoritative broker/position reconciliation each startup."""
        with self._connection() as connection:
            self._begin(connection)
            previous = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__startup_reconciliation__'"
            ).fetchone()
            previous_status = str(previous["status"]) if previous else None
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                   VALUES('__startup_reconciliation__','__startup_reconciliation__',NULL,'PENDING',
                          'STARTUP_AUTHORITATIVE_RECONCILIATION_REQUIRED',
                          '{"requirement":"orders_fills_positions"}',CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET
                     status=CASE WHEN reconciliation_state.status='CONFLICT' THEN 'CONFLICT' ELSE 'PENDING' END,
                     reason=CASE WHEN reconciliation_state.status='CONFLICT' THEN reconciliation_state.reason ELSE excluded.reason END,
                     evidence_ref=NULL,payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP"""
            )
            current = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__startup_reconciliation__'"
            ).fetchone()
            current_status = str(current["status"]) if current else "PENDING"
            event_type = None
            if current_status == "CONFLICT":
                event_type = "GATE_REARM_BLOCKED_CONFLICT"
            elif previous_status != "PENDING":
                event_type = "GATE_REARMED" if previous_status == "RESOLVED" else "GATE_REGISTERED"
            if event_type is not None:
                connection.execute(
                    """INSERT INTO startup_reconciliation_history
                       (event_type,gate_status,payload_json)
                       VALUES(?,?,?)""",
                    (event_type, current_status, encode_record({
                        "previous_status": previous_status,
                        "resulting_status": current_status,
                        "reason": "FRESH_STARTUP_RECONCILIATION_REQUIRED",
                    })),
                )
            connection.commit()

    def ensure_authoritative_baseline_gate(self) -> None:
        """Block new exposure until durable OMS and Position baseline exist."""
        with self._connection() as connection:
            self._begin(connection)
            orders = connection.execute("SELECT COUNT(*) AS n FROM order_states").fetchone()["n"]
            positions = connection.execute("SELECT COUNT(*) AS n FROM position_states").fetchone()["n"]
            baseline = connection.execute("SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'").fetchone()
            if baseline is None or baseline["value"] != "1":
                connection.execute(
                    """INSERT INTO reconciliation_state
                       (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                       VALUES('__runtime_bootstrap__','__runtime_bootstrap__',NULL,'PENDING',
                              'INITIAL_AUTHORITATIVE_STATE_IMPORT_REQUIRED','{}',CURRENT_TIMESTAMP)
                       ON CONFLICT(scope_key) DO NOTHING"""
                )
            connection.commit()

    def resolve_startup_reconciliation(
        self,
        *,
        orders_snapshot_id: str,
        executions_snapshot_id: str,
        positions_snapshot_id: str,
        as_of: datetime,
        source: str,
        payload_sha256: str,
        authoritative_evidence_ref: str,
        evidence_manifest: Mapping[str, Any] | None = None,
    ) -> bool:
        """Release the startup gate only with a complete, time-aligned three-snapshot evidence set."""
        snapshot_ids = tuple(str(value).strip() for value in (
            orders_snapshot_id, executions_snapshot_id, positions_snapshot_id
        ))
        source_value = str(source).strip()
        digest = str(payload_sha256).strip().lower()
        evidence = str(authoritative_evidence_ref).strip()
        if any(not value for value in snapshot_ids) or len(set(snapshot_ids)) != 3:
            raise ValueError("STARTUP_ORDERS_EXECUTIONS_POSITIONS_SNAPSHOT_IDS_REQUIRED_AND_DISTINCT")
        if not source_value or not evidence:
            raise ValueError("STARTUP_RECONCILIATION_SOURCE_AND_EVIDENCE_REQUIRED")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("STARTUP_RECONCILIATION_AS_OF_MUST_BE_TIMEZONE_AWARE")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("STARTUP_RECONCILIATION_SHA256_INVALID")
        payload = {
            "source": source_value,
            "orders_snapshot_id": snapshot_ids[0],
            "executions_snapshot_id": snapshot_ids[1],
            "positions_snapshot_id": snapshot_ids[2],
            "as_of": as_of.isoformat(),
            "payload_sha256": digest,
            "evidence_ref": evidence,
            "coverage": ["orders", "fills", "positions"],
        }
        if evidence_manifest is not None:
            manifest = dict(evidence_manifest)
            manifest_digest = hashlib.sha256(encode_record(manifest).encode("utf-8")).hexdigest()
            if manifest_digest != digest:
                raise ValueError("STARTUP_RECONCILIATION_MANIFEST_DIGEST_MISMATCH")
            payload["lineage_manifest"] = manifest
        encoded = encode_record(payload)
        with self._connection() as connection:
            self._begin(connection)
            baseline = connection.execute(
                "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'"
            ).fetchone()
            if baseline is None or baseline["value"] != "1":
                connection.rollback()
                raise SettlementStoreError("AUTHORITATIVE_BASELINE_REQUIRED_BEFORE_STARTUP_RECONCILIATION")
            startup = connection.execute(
                "SELECT status FROM reconciliation_state WHERE scope_key='__startup_reconciliation__'"
            ).fetchone()
            if startup is None:
                connection.rollback()
                raise SettlementStoreError("STARTUP_RECONCILIATION_GATE_NOT_REGISTERED")
            existing_evidence = connection.execute(
                "SELECT value FROM settlement_meta WHERE key='startup_reconciliation_evidence'"
            ).fetchone()
            if startup["status"] == "RESOLVED":
                connection.rollback()
                if existing_evidence is not None and existing_evidence["value"] == encoded:
                    return False
                raise SettlementStoreError("STARTUP_RECONCILIATION_NOT_PENDING")
            if startup["status"] == "CONFLICT":
                connection.rollback()
                raise SettlementStoreError("STARTUP_RECONCILIATION_CONFLICT_REQUIRES_MANUAL_REVIEW")
            open_inbox = connection.execute(
                "SELECT COUNT(*) AS n FROM reconciliation_inbox WHERE status IN ('PENDING','CONFLICT')"
            ).fetchone()["n"]
            other_unresolved = connection.execute(
                """SELECT COUNT(*) AS n FROM reconciliation_state
                   WHERE status IN ('PENDING','CONFLICT')
                     AND scope_key NOT IN ('__startup_reconciliation__')"""
            ).fetchone()["n"]
            if open_inbox or other_unresolved:
                connection.rollback()
                raise SettlementStoreError("STARTUP_RECONCILIATION_HAS_OTHER_UNRESOLVED_EVENTS")
            connection.execute(
                """INSERT INTO settlement_meta(key,value,updated_at)
                   VALUES('startup_reconciliation_evidence',?,CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                (encoded,),
            )
            resolved = connection.execute(
                """UPDATE reconciliation_state SET status='RESOLVED',reason='STARTUP_ORDERS_FILLS_POSITIONS_RECONCILED',
                   evidence_ref=?,payload_json=?,updated_at=CURRENT_TIMESTAMP
                   WHERE scope_key='__startup_reconciliation__' AND status='PENDING'""",
                (evidence, encoded),
            )
            if resolved.rowcount != 1:
                raise SettlementStoreError("STARTUP_RECONCILIATION_RESOLUTION_FAILED")
            manifest = payload.get("lineage_manifest")
            connection.execute(
                """INSERT INTO startup_reconciliation_history
                   (event_type,gate_status,evidence_sha256,manifest_version,
                    baseline_evidence_sha256,payload_json)
                   VALUES('STARTUP_RESOLVED','RESOLVED',?,?,?,?)""",
                (
                    digest,
                    manifest.get("manifest_version") if isinstance(manifest, dict) else None,
                    manifest.get("baseline_import_evidence_sha256") if isinstance(manifest, dict) else None,
                    encoded,
                ),
            )
            connection.commit()
            return True

    def resolve_reconciliation(self, *, scope_key: str, authoritative_evidence_ref: str) -> None:
        scope = str(scope_key).strip()
        evidence = str(authoritative_evidence_ref).strip()
        if not scope or not evidence:
            raise ValueError("AUTHORITATIVE_RECONCILIATION_EVIDENCE_REQUIRED")
        if scope in {"__startup_reconciliation__", "__runtime_bootstrap__"}:
            raise SettlementStoreError("GLOBAL_RECONCILIATION_REQUIRES_DEDICATED_EVIDENCE_API")
        with self._connection() as connection:
            self._begin(connection)
            open_events = connection.execute(
                """SELECT COUNT(*) AS n FROM reconciliation_inbox
                   WHERE scope_key=? AND status IN ('PENDING','CONFLICT')""",
                (scope,),
            ).fetchone()["n"]
            if open_events:
                connection.rollback()
                raise SettlementStoreError("RECONCILIATION_INBOX_EVENTS_MUST_BE_SETTLED_INDIVIDUALLY")
            cursor = connection.execute(
                """UPDATE reconciliation_state
                   SET status='RESOLVED', evidence_ref=?, updated_at=CURRENT_TIMESTAMP
                   WHERE scope_key=? AND status IN ('PENDING','CONFLICT')""",
                (evidence, scope),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise SettlementStoreError("UNRESOLVED_RECONCILIATION_NOT_FOUND")
            connection.commit()
