"""Append-only durable snapshots for validation-only Track6 lifecycle runs.

This store is intentionally separate from production/Live settlement storage.
It records no credentials and refuses to rewrite an existing event stream.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class Track6ValidationStateStoreError(RuntimeError):
    pass


class Track6ValidationStateStore:
    def __init__(self, root: str | Path, *, run_id: str) -> None:
        safe_run_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(run_id)).strip("._-")
        if not safe_run_id or safe_run_id != str(run_id):
            raise ValueError("TRACK6_VALIDATION_RUN_ID_INVALID")
        self.root = Path(root)
        self.run_id = safe_run_id
        self.path = self.root / f"{safe_run_id}.jsonl"
        self._last_record: dict[str, Any] | None = None

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def append(self, snapshot: dict[str, Any]) -> str:
        if str(snapshot.get("run_id", "")) != self.run_id:
            raise Track6ValidationStateStoreError("TRACK6_VALIDATION_RUN_ID_MISMATCH")
        self.root.mkdir(parents=True, exist_ok=True)
        prior = self._last_record
        if prior is None and self.path.exists():
            prior = self.load_latest()
        sequence = int(prior.get("sequence", 0)) + 1 if prior else 1
        previous_hash = str(prior.get("record_sha256", "")) if prior else None
        body = {
            "schema_version": 1,
            "run_id": self.run_id,
            "sequence": sequence,
            "previous_record_sha256": previous_hash,
            "snapshot": snapshot,
        }
        digest = hashlib.sha256(self._canonical(body)).hexdigest()
        record = dict(body, record_sha256=digest)
        encoded = self._canonical(record) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "ab", closefd=True) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            raise
        self._last_record = {
            "sequence": sequence,
            "record_sha256": digest,
            "snapshot": snapshot,
        }
        return digest

    def load_latest(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        previous_hash = None
        latest = None
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for expected_sequence, line in enumerate(stream, start=1):
                    if not line.endswith("\n"):
                        raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_TORN_RECORD")
                    record = json.loads(line)
                    digest = record.pop("record_sha256")
                    if record.get("schema_version") != 1 or record.get("run_id") != self.run_id:
                        raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_IDENTITY_INVALID")
                    if int(record.get("sequence", 0)) != expected_sequence:
                        raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_SEQUENCE_INVALID")
                    if record.get("previous_record_sha256") != previous_hash:
                        raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_CHAIN_INVALID")
                    actual = hashlib.sha256(self._canonical(record)).hexdigest()
                    if actual != digest:
                        raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_HASH_MISMATCH")
                    previous_hash = digest
                    latest = {
                        "sequence": expected_sequence,
                        "record_sha256": digest,
                        "snapshot": record["snapshot"],
                    }
        except Track6ValidationStateStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Track6ValidationStateStoreError("TRACK6_VALIDATION_STATE_READ_FAILED") from exc
        self._last_record = latest
        return latest
