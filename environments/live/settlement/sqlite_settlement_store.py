"""Durable SQLite settlement journal for one local, single-writer Live runtime.

The database is the settlement source of truth. Market-data JSONL stores are
intentionally unrelated. This module never performs broker or KIS API calls.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


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
                resolved = connection.execute(
                    """UPDATE reconciliation_state
                       SET status='RESOLVED', evidence_ref=?, updated_at=CURRENT_TIMESTAMP
                       WHERE scope_key=? AND status IN ('PENDING','CONFLICT')""",
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

    def mark_startup_reconciliation_pending(self) -> None:
        """Require a fresh authoritative broker/position reconciliation each startup."""
        with self._connection() as connection:
            self._begin(connection)
            connection.execute(
                """INSERT INTO reconciliation_state
                   (scope_key,client_order_id,broker_order_id,status,reason,payload_json,updated_at)
                   VALUES('__startup_reconciliation__','__startup_reconciliation__',NULL,'PENDING',
                          'STARTUP_AUTHORITATIVE_RECONCILIATION_REQUIRED',
                          '{"requirement":"orders_fills_positions"}',CURRENT_TIMESTAMP)
                   ON CONFLICT(scope_key) DO UPDATE SET status='PENDING',
                     reason=excluded.reason,evidence_ref=NULL,payload_json=excluded.payload_json,
                     updated_at=CURRENT_TIMESTAMP"""
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

    def resolve_reconciliation(self, *, scope_key: str, authoritative_evidence_ref: str) -> None:
        scope = str(scope_key).strip()
        evidence = str(authoritative_evidence_ref).strip()
        if not scope or not evidence:
            raise ValueError("AUTHORITATIVE_RECONCILIATION_EVIDENCE_REQUIRED")
        with self._connection() as connection:
            self._begin(connection)
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
