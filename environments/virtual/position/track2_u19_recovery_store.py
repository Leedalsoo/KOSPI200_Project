from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class SqliteTrack2U19RecoveryStore:
    """Append-only validation checkpoint store with payload integrity verification."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS track2_u19_recovery_checkpoint (
                    checkpoint_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS track2_u19_checkpoint_no_update
                BEFORE UPDATE ON track2_u19_recovery_checkpoint
                BEGIN SELECT RAISE(ABORT, 'TRACK2_U19_CHECKPOINT_APPEND_ONLY'); END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS track2_u19_checkpoint_no_delete
                BEFORE DELETE ON track2_u19_recovery_checkpoint
                BEGIN SELECT RAISE(ABORT, 'TRACK2_U19_CHECKPOINT_APPEND_ONLY'); END
                """
            )

    @staticmethod
    def _canonical_payload(payload: dict[str, Any]) -> tuple[str, str]:
        if payload.get("schema_version") != SqliteTrack2U19RecoveryStore.SCHEMA_VERSION:
            raise ValueError("TRACK2_U19_CHECKPOINT_SCHEMA_UNSUPPORTED")
        checkpoint_id = payload.get("checkpoint_id")
        group_id = payload.get("group_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            raise ValueError("TRACK2_U19_CHECKPOINT_ID_REQUIRED")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("TRACK2_U19_GROUP_ID_REQUIRED")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return body, hashlib.sha256(body.encode("utf-8")).hexdigest()

    def save(self, payload: dict[str, Any]) -> None:
        body, digest = self._canonical_payload(payload)
        checkpoint_id = payload["checkpoint_id"]
        group_id = payload["group_id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_sha256 FROM track2_u19_recovery_checkpoint WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("TRACK2_U19_CHECKPOINT_ID_CONFLICT")
                return
            connection.execute(
                """
                INSERT INTO track2_u19_recovery_checkpoint
                    (checkpoint_id, group_id, payload_json, payload_sha256)
                VALUES (?, ?, ?, ?)
                """,
                (checkpoint_id, group_id, body, digest),
            )

    def load_latest(self, group_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, payload_sha256
                FROM track2_u19_recovery_checkpoint
                WHERE group_id=?
                ORDER BY rowid DESC LIMIT 1
                """,
                (group_id,),
            ).fetchone()
        if row is None:
            return None
        body, expected_digest = row
        actual_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError("TRACK2_U19_CHECKPOINT_INTEGRITY_FAILURE")
        payload = json.loads(body)
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("TRACK2_U19_CHECKPOINT_SCHEMA_UNSUPPORTED")
        return payload
