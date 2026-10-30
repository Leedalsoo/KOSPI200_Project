from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any


class ReplayLogMode(str, Enum):
    FAST = "fast"
    DETAILED = "detailed"


class ReplayTraceController:
    """Observation-only replay trace. Logging must never drive runtime decisions."""

    SCHEMA = "high-speed-replay-trace-v1"

    def __init__(self, mode: ReplayLogMode | str = ReplayLogMode.FAST, *, output_path: str | Path | None = None):
        try:
            self.mode = ReplayLogMode(mode)
        except ValueError as exc:
            raise ValueError("REPLAY_LOG_MODE_UNSUPPORTED") from exc
        self.output_path = Path(output_path) if output_path is not None else None
        if self.mode is ReplayLogMode.DETAILED:
            if self.output_path is None:
                raise ValueError("DETAILED_REPLAY_TRACE_OUTPUT_REQUIRED")
            if self.output_path.exists():
                raise FileExistsError("DETAILED_REPLAY_TRACE_OUTPUT_ALREADY_EXISTS")
            if not self.output_path.parent.is_dir():
                raise FileNotFoundError("DETAILED_REPLAY_TRACE_PARENT_DIRECTORY_REQUIRED")
            self.status = "CONNECTED"
        elif self.output_path is not None:
            raise ValueError("FAST_REPLAY_TRACE_OUTPUT_FORBIDDEN")
        else:
            self.status = "DISABLED_FAST_MODE"
        self.write_errors: list[str] = []
        self._trace_sequence = 0
        self._created = False

    def emit(
        self,
        event_type: str,
        *,
        run_id: str,
        event_sequence: int | None = None,
        timestamp: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.mode is ReplayLogMode.FAST or self.status == "TRACE_WRITE_FAILED":
            return
        if not event_type or not run_id:
            raise ValueError("REPLAY_TRACE_EVENT_TYPE_AND_RUN_ID_REQUIRED")
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("REPLAY_TRACE_PAYLOAD_MUST_BE_OBJECT")
        record = {
            "schema": self.SCHEMA,
            "trace_sequence": self._trace_sequence,
            "event_type": event_type,
            "run_id": run_id,
            "event_sequence": event_sequence,
            "timestamp": timestamp,
            "payload": payload or {},
        }
        try:
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            mode = "a" if self._created else "x"
            with self.output_path.open(mode, encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.write("\n")
        except Exception as exc:
            # Trace serialization/storage failures must not interrupt market replay.
            self.status = "TRACE_WRITE_FAILED"
            self.write_errors.append(type(exc).__name__)
            return
        self._created = True
        self._trace_sequence += 1


def _trace_value(value: Any) -> Any:
    """Convert canonical command/report dataclasses to JSON-safe, loss-aware values."""
    from collections.abc import Mapping
    from dataclasses import fields, is_dataclass
    from datetime import datetime
    from decimal import Decimal

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _trace_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _trace_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _trace_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_trace_value(item) for item in value]
    return {"unavailable_type": type(value).__name__}


class ReplayExecutionObserver:
    """Temporarily observe Virtual broker submissions without changing their results."""

    def __init__(self, trace: ReplayTraceController, *, run_id: str) -> None:
        if not run_id:
            raise ValueError("REPLAY_EXECUTION_OBSERVER_RUN_ID_REQUIRED")
        self.trace = trace
        self.run_id = run_id
        self.event_sequence: int | None = None
        self.status = "CONNECTED"
        self.trace_write_errors: list[str] = []
        self.order_commands_observed = 0
        self.execution_reports_observed = 0
        self.fills_observed = 0
        self._attachments: list[tuple[Any, bool, Any]] = []

    def _emit(self, event_type: str, *, payload: dict[str, Any]) -> None:
        try:
            self.trace.emit(
                event_type,
                run_id=self.run_id,
                event_sequence=self.event_sequence,
                payload=payload,
            )
            if self.trace.status == "TRACE_WRITE_FAILED":
                self.status = "TRACE_WRITE_FAILED"
                self.trace_write_errors.extend(self.trace.write_errors)
        except Exception as exc:
            # Observation/storage failures must not change broker submission outcomes.
            self.status = "TRACE_WRITE_FAILED"
            self.trace_write_errors.append(type(exc).__name__)

    def attach(self, adapter: Any, *, adapter_name: str) -> None:
        original_submit = getattr(adapter, "submit", None)
        if not callable(original_submit):
            raise TypeError("REPLAY_EXECUTION_OBSERVER_SUBMIT_HOOK_REQUIRED")
        instance_dict = getattr(adapter, "__dict__", {})
        had_instance_submit = "submit" in instance_dict
        original_instance_submit = instance_dict.get("submit")
        observer = self

        def observed_submit(command: Any, *args: Any, **kwargs: Any) -> Any:
            prior_report = getattr(adapter, "last_report", None)
            try:
                response = original_submit(command, *args, **kwargs)
            except Exception as exc:
                report = getattr(adapter, "last_report", None)
                observer._record_command(command, adapter_name)
                if report is not None and report is not prior_report:
                    observer._record_report(report, adapter_name)
                else:
                    observer._emit(
                        "execution_report_unavailable",
                        payload={
                            "adapter": adapter_name,
                            "client_order_id": getattr(command, "client_order_id", None),
                            "reason": "SUBMIT_RAISED_WITHOUT_NEW_CANONICAL_REPORT",
                            "exception_type": type(exc).__name__,
                        },
                    )
                raise
            report = getattr(adapter, "last_report", None)
            observer._record_command(command, adapter_name)
            if report is not None:
                observer._record_report(report, adapter_name)
            else:
                observer._emit(
                    "execution_report_unavailable",
                    payload={
                        "adapter": adapter_name,
                        "client_order_id": getattr(command, "client_order_id", None),
                        "reason": "CANONICAL_REPORT_NOT_EXPOSED",
                    },
                )
            return response

        try:
            setattr(adapter, "submit", observed_submit)
        except Exception as exc:
            raise RuntimeError("REPLAY_EXECUTION_OBSERVER_ATTACH_FAILED") from exc
        self._attachments.append((adapter, had_instance_submit, original_instance_submit))

    def _record_command(self, command: Any, adapter_name: str) -> None:
        self.order_commands_observed += 1
        self._emit(
            "order_command",
            payload={"adapter": adapter_name, "command": _trace_value(command)},
        )

    def _record_report(self, report: Any, adapter_name: str) -> None:
        report_payload = _trace_value(report)
        if not isinstance(report_payload, dict):
            report_payload = {"unavailable_type": type(report).__name__}
        self.execution_reports_observed += 1
        self._emit(
            "execution_report",
            payload={"adapter": adapter_name, "report": report_payload},
        )
        filled_quantity = getattr(report, "filled_quantity", 0)
        execution_id = getattr(report, "execution_id", None)
        try:
            has_fill = int(filled_quantity or 0) > 0
        except (TypeError, ValueError):
            has_fill = False
        if has_fill and execution_id:
            self.fills_observed += 1
            self._emit(
                "fill",
                payload={
                    "adapter": adapter_name,
                    "client_order_id": getattr(report, "client_order_id", None),
                    "execution_id": execution_id,
                    "status": getattr(report, "status", None),
                    "filled_quantity": int(filled_quantity),
                    "remaining_quantity": getattr(report, "remaining_quantity", None),
                    "execution_price": _trace_value(getattr(report, "execution_price", None)),
                    "execution_timestamp": _trace_value(getattr(report, "execution_timestamp", None)),
                    "fee": _trace_value(getattr(report, "fee", None)),
                    "group_id": getattr(report, "group_id", None),
                    "leg_id": getattr(report, "leg_id", None),
                },
            )
        elif has_fill:
            self._emit(
                "fill_identity_unavailable",
                payload={
                    "adapter": adapter_name,
                    "client_order_id": getattr(report, "client_order_id", None),
                    "reason": "FILLED_QUANTITY_WITHOUT_EXECUTION_ID",
                },
            )

    def summary(self) -> dict[str, Any]:
        failed = self.status == "TRACE_WRITE_FAILED" or self.trace.status == "TRACE_WRITE_FAILED"
        status = "TRACE_WRITE_FAILED" if failed else "CONNECTED"
        return {
            "status": status,
            "order_commands_observed": self.order_commands_observed,
            "execution_reports_observed": self.execution_reports_observed,
            "fills_observed": self.fills_observed,
            "trace_write_errors": list(dict.fromkeys(self.trace_write_errors + self.trace.write_errors)),
            "order_records_status": (
                "TRACE_WRITE_FAILED" if failed else
                "OBSERVED_READ_ONLY" if self.order_commands_observed else
                "NO_ORDER_COMMANDS_OBSERVED"
            ),
            "fill_records_status": (
                "TRACE_WRITE_FAILED" if failed else
                "CANONICAL_FILLS_OBSERVED" if self.fills_observed else
                "NO_CANONICAL_FILL_EVIDENCE"
            ),
        }

    def detach(self) -> None:
        for adapter, had_instance_submit, original_instance_submit in reversed(self._attachments):
            try:
                if had_instance_submit:
                    setattr(adapter, "submit", original_instance_submit)
                else:
                    delattr(adapter, "submit")
            except AttributeError:
                pass
        self._attachments.clear()
