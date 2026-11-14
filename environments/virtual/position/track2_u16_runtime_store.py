from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class SqliteTrack2U16RuntimeStore:
    """Append-only validation runtime snapshots with payload integrity checks."""

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
                CREATE TABLE IF NOT EXISTS track2_u16_runtime_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS track2_u16_snapshot_no_update
                BEFORE UPDATE ON track2_u16_runtime_snapshot
                BEGIN SELECT RAISE(ABORT, 'TRACK2_U16_SNAPSHOT_APPEND_ONLY'); END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS track2_u16_snapshot_no_delete
                BEFORE DELETE ON track2_u16_runtime_snapshot
                BEGIN SELECT RAISE(ABORT, 'TRACK2_U16_SNAPSHOT_APPEND_ONLY'); END
                """
            )

    @staticmethod
    def _canonical(group_id: str, state: dict[str, dict[str, Any]]) -> tuple[str, str]:
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("TRACK2_U16_GROUP_ID_REQUIRED")
        if not isinstance(state, dict):
            raise ValueError("TRACK2_U16_STATE_SNAPSHOT_INVALID")
        prefix = f"{group_id}|"
        if any(not isinstance(key, str) or not key.startswith(prefix) for key in state):
            raise ValueError("TRACK2_U16_STATE_GROUP_SCOPE_MISMATCH")
        payload = {
            "schema_version": SqliteTrack2U16RuntimeStore.SCHEMA_VERSION,
            "group_id": group_id,
            "state": state,
        }
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
        )
        return body, hashlib.sha256(body.encode("utf-8")).hexdigest()

    def save(self, group_id: str, state: dict[str, dict[str, Any]]) -> str:
        body, digest = self._canonical(group_id, state)
        snapshot_id = f"u16-{digest[:32]}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_sha256 FROM track2_u16_runtime_snapshot WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("TRACK2_U16_SNAPSHOT_ID_CONFLICT")
                return snapshot_id
            connection.execute(
                """INSERT INTO track2_u16_runtime_snapshot
                   (snapshot_id, group_id, payload_json, payload_sha256)
                   VALUES (?, ?, ?, ?)""",
                (snapshot_id, group_id, body, digest),
            )
        return snapshot_id

    def load_latest(self, group_id: str) -> dict[str, dict[str, Any]] | None:
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("TRACK2_U16_GROUP_ID_REQUIRED")
        with self._connect() as connection:
            row = connection.execute(
                """SELECT payload_json, payload_sha256
                   FROM track2_u16_runtime_snapshot WHERE group_id=?
                   ORDER BY rowid DESC LIMIT 1""",
                (group_id,),
            ).fetchone()
        if row is None:
            return None
        body, expected = row
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != expected:
            raise ValueError("TRACK2_U16_SNAPSHOT_INTEGRITY_FAILURE")
        payload = json.loads(body)
        if payload.get("schema_version") != self.SCHEMA_VERSION or payload.get("group_id") != group_id:
            raise ValueError("TRACK2_U16_SNAPSHOT_SCHEMA_OR_SCOPE_INVALID")
        state = payload.get("state")
        if not isinstance(state, dict):
            raise ValueError("TRACK2_U16_STATE_SNAPSHOT_INVALID")
        for item in state.values():
            raw = item.get("first_repair_submitted_at") if isinstance(item, dict) else None
            if isinstance(raw, str):
                item["first_repair_submitted_at"] = datetime.fromisoformat(raw)
        return state
