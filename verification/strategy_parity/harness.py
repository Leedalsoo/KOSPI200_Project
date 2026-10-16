from __future__ import annotations
from contracts.trading_date import format_trading_date

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from datetime import datetime, date, time
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ExecutionCallback:
    purpose: str
    result: object


@dataclass(frozen=True)
class ParityStep:
    context: object
    callbacks: tuple[ExecutionCallback, ...] = ()
    reset_after: bool = False
    label: str = ""
    method: str = "evaluate"


@dataclass(frozen=True)
class ParityDifference:
    step_index: int
    step_label: str
    field: str
    left: object
    right: object


@dataclass(frozen=True)
class ParityResult:
    equal: bool
    differences: tuple[ParityDifference, ...]
    left_trace: tuple[Mapping[str, object], ...]
    right_trace: tuple[Mapping[str, object], ...]


def semantic_value(value: Any) -> Any:
    """Serialize every dataclass field and mapping entry without dropping semantics."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return format_trading_date(value)
    if isinstance(value, time):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: semantic_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): semantic_value(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (tuple, list)):
        return [semantic_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((semantic_value(item) for item in value), key=repr)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {key: semantic_value(item) for key, item in sorted(vars(value).items()) if not callable(item)}
    return repr(value)


def plugin_snapshot(plugin: object) -> dict[str, object]:
    values = vars(plugin) if hasattr(plugin, "__dict__") else {}
    state = semantic_value(values.get("state")) if "state" in values else None
    internals = {
        key: semantic_value(value)
        for key, value in sorted(values.items())
        if key.startswith("_") and key != "state" and not callable(value)
    }
    return {"state": state, "internals": internals}


def run_trace(plugin: object, steps: Sequence[ParityStep]) -> tuple[Mapping[str, object], ...]:
    trace: list[Mapping[str, object]] = []
    for index, step in enumerate(steps):
        signals = tuple(getattr(plugin, step.method)(step.context))
        trace.append({
            "step_index": index,
            "step_label": step.label,
            "event": "evaluate",
            "signals": semantic_value(signals),
            "plugin": plugin_snapshot(plugin),
        })
        callback = getattr(plugin, "on_execution_result", None)
        for callback_index, event in enumerate(step.callbacks):
            if callback is None:
                trace.append({"step_index": index, "step_label": step.label, "event": "callback_missing", "callback_index": callback_index})
                continue
            callback(event.purpose, event.result)
            trace.append({
                "step_index": index,
                "step_label": step.label,
                "event": "execution_callback",
                "purpose": event.purpose,
                "result": semantic_value(event.result),
                "plugin": plugin_snapshot(plugin),
            })
        if step.reset_after:
            plugin.reset()
            trace.append({
                "step_index": index,
                "step_label": step.label,
                "event": "reset",
                "plugin": plugin_snapshot(plugin),
            })
    return tuple(trace)


def compare_traces(left_trace: Sequence[Mapping[str, object]], right_trace: Sequence[Mapping[str, object]]) -> ParityResult:
    differences: list[ParityDifference] = []
    max_len = max(len(left_trace), len(right_trace))
    for index in range(max_len):
        left = left_trace[index] if index < len(left_trace) else None
        right = right_trace[index] if index < len(right_trace) else None
        if left == right:
            continue
        label = ""
        if isinstance(left, Mapping):
            label = str(left.get("step_label", ""))
        elif isinstance(right, Mapping):
            label = str(right.get("step_label", ""))
        field = "trace_length" if left is None or right is None else "semantic_event"
        differences.append(ParityDifference(index, label, field, left, right))
    return ParityResult(not differences, tuple(differences), tuple(left_trace), tuple(right_trace))


def compare_plugins(left: object, right: object, steps: Sequence[ParityStep]) -> ParityResult:
    """Run the same ordered contexts/callbacks through two independently initialized plugins."""
    return compare_traces(run_trace(left, steps), run_trace(right, steps))


class TeeStrategy:
    """Verification-only tee: forwards each exact context to two plugin instances."""
    def __init__(self, left: object, right: object) -> None:
        self.left = left
        self.right = right
        self.last_signals: tuple[tuple[object, ...], tuple[object, ...]] = ((), ())

    def evaluate(self, context: object) -> tuple[tuple[object, ...], tuple[object, ...]]:
        left_signals = tuple(self.left.evaluate(context))
        right_signals = tuple(self.right.evaluate(context))
        self.last_signals = (left_signals, right_signals)
        return self.last_signals

    def on_execution_result(self, purpose: str, result: object) -> None:
        for plugin in (self.left, self.right):
            callback = getattr(plugin, "on_execution_result", None)
            if callback is not None:
                callback(purpose, result)