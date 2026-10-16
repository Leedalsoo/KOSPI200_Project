from __future__ import annotations

"""Fail-closed KIS WebSocket subscription ACK state machine.

IMPORTANT: KIS VTS subscription ACK schema has not been authoritatively verified.
Do not fill ACK_SCHEMA from guesses. Until all fields are confirmed from official
KIS VTS documentation/sample evidence, the collector must remain blocked before
opening a WebSocket or sending subscription messages.
"""

import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any


ACK_TIMEOUT_SECONDS = 5.0  # Provisional safety timeout; confirm against official KIS evidence.
ACK_SCHEMA_TODO = (
    "TODO(G9-C prerequisite): verify official KIS VTS ACK request-id echo, "
    "status/result fields, TR ID, symbol, action, and success/reject values."
)


class Action(str, Enum):
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"


class State(str, Enum):
    IDLE = "IDLE"
    APPLYING = "APPLYING"
    ROLLING_BACK = "ROLLING_BACK"
    READY = "READY"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AckSchema:
    # Every path/value below is intentionally unset until official evidence exists.
    request_id_out_path: str | None = None
    request_id_in_path: str | None = None
    status_path: str | None = None
    tr_id_path: str | None = None
    symbol_path: str | None = None
    action_path: str | None = None
    success_values: tuple[str, ...] = ()
    reject_values: tuple[str, ...] = ()
    subscribe_action_value: str | None = None
    unsubscribe_action_value: str | None = None

    @property
    def configured(self) -> bool:
        paths = (
            self.request_id_out_path,
            self.request_id_in_path,
            self.status_path,
            self.tr_id_path,
            self.symbol_path,
            self.action_path,
            self.subscribe_action_value,
            self.unsubscribe_action_value,
        )
        return (
            all(isinstance(p, str) and p.strip() for p in paths)
            and bool(self.success_values)
            and bool(self.reject_values)
            and not ({str(v) for v in self.success_values} & {str(v) for v in self.reject_values})
        )


ACK_SCHEMA = AckSchema()


@dataclass(frozen=True)
class SubscriptionAction:
    action: Action
    tr_id: str
    symbol: str


@dataclass
class PendingRequest:
    request_id: str
    action: Action
    tr_id: str
    symbol: str
    session_generation: str
    sent_at: float | None = None
    deadline: float | None = None


@dataclass(frozen=True)
class AckResult:
    kind: str
    request_id: str | None = None
    action: Action | None = None
    tr_id: str | None = None
    symbol: str | None = None
    detail: str = ""


def _read_path(value: Any, dotted_path: str | None) -> Any:
    if not dotted_path:
        return None
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _write_path(value: dict[str, Any], dotted_path: str, item: Any) -> None:
    parts = dotted_path.split(".")
    if not parts or any(not p for p in parts):
        raise ValueError("INVALID_ACK_SCHEMA_OUTGOING_PATH")
    current = value
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ValueError("ACK_SCHEMA_OUTGOING_PATH_CONFLICT")
        current = child
    if parts[-1] in current:
        raise ValueError("ACK_SCHEMA_OUTGOING_PATH_COLLISION")
    current[parts[-1]] = item


def build_request_payload(
    *,
    approval_key: str,
    request: PendingRequest,
    schema: AckSchema,
) -> str:
    if not schema.configured:
        raise RuntimeError("KIS_WS_ACK_SCHEMA_UNVERIFIED")
    tr_type = "1" if request.action is Action.SUBSCRIBE else "2"
    payload: dict[str, Any] = {
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": tr_type,
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": request.tr_id, "tr_key": request.symbol}},
    }
    _write_path(payload, str(schema.request_id_out_path), request.request_id)
    return json.dumps(payload, ensure_ascii=False)


def parse_ack_frame(payload: str, schema: AckSchema) -> AckResult | None:
    """Return None for unrelated control frames; never infer success from unknown fields."""
    if not schema.configured:
        return AckResult(kind="UNKNOWN", detail=ACK_SCHEMA_TODO)
    try:
        message = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    request_id = _read_path(message, schema.request_id_in_path)
    status = _read_path(message, schema.status_path)
    tr_id = _read_path(message, schema.tr_id_path)
    symbol = _read_path(message, schema.symbol_path)
    action_value = _read_path(message, schema.action_path)
    if all(v is None for v in (request_id, status, tr_id, symbol, action_value)):
        return None
    if any(v is None for v in (request_id, status, tr_id, symbol, action_value)):
        return AckResult(kind="UNKNOWN", detail="ACK_FIELDS_INCOMPLETE")
    action_text = str(action_value)
    if action_text == str(schema.subscribe_action_value):
        action = Action.SUBSCRIBE
    elif action_text == str(schema.unsubscribe_action_value):
        action = Action.UNSUBSCRIBE
    else:
        return AckResult(kind="UNKNOWN", detail="ACK_ACTION_UNRECOGNIZED")
    status_text = str(status)
    if status_text in {str(v) for v in schema.success_values}:
        kind = "SUCCESS"
    elif status_text in {str(v) for v in schema.reject_values}:
        kind = "REJECT"
    else:
        kind = "UNKNOWN"
    return AckResult(
        kind=kind,
        request_id=str(request_id),
        action=action,
        tr_id=str(tr_id),
        symbol=str(symbol),
        detail="" if kind in {"SUCCESS", "REJECT"} else "ACK_STATUS_UNRECOGNIZED",
    )


class SubscriptionAckController:
    """Serial ACK-driven subscription transaction controller; no socket operations here."""

    def __init__(
        self,
        *,
        baseline: set[tuple[str, str]],
        pinned: set[tuple[str, str]],
        cap: int,
        schema: AckSchema = ACK_SCHEMA,
        timeout_seconds: float = ACK_TIMEOUT_SECONDS,
    ) -> None:
        self.baseline = set(baseline)
        self.pinned = set(pinned)
        self.cap = int(cap)
        self.schema = schema
        self.timeout_seconds = float(timeout_seconds)
        self.confirmed: set[tuple[str, str]] = set()
        self.state = State.IDLE
        self.mode: str | None = None
        self.target: set[tuple[str, str]] = set()
        self.rollback_target: set[tuple[str, str]] = set()
        self.queue: list[SubscriptionAction] = []
        self.pending: PendingRequest | None = None
        self.completed_request_ids: set[str] = set()
        self.session_generation = uuid.uuid4().hex
        self.last_result = "NOT_STARTED"
        self.last_completed_kind: str | None = None
        self.last_event: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return self.state is State.READY and self.pending is None and not self.queue

    def _block(self, reason: str) -> None:
        self.state = State.BLOCKED
        self.last_result = reason
        self.queue.clear()

    def _make_plan(
        self,
        current: set[tuple[str, str]],
        target: set[tuple[str, str]],
        *,
        rollback: bool = False,
    ) -> list[SubscriptionAction]:
        if len(current) > self.cap or len(target) > self.cap:
            raise ValueError("SUBSCRIPTION_CAP_EXCEEDED")
        additions = sorted(target - current)
        removals = sorted(current - target)
        if rollback:
            # Remove only confirmed non-target subscriptions first, then restore target.
            actions = [
                SubscriptionAction(Action.UNSUBSCRIBE, tr, sym)
                for tr, sym in removals
            ] + [
                SubscriptionAction(Action.SUBSCRIBE, tr, sym)
                for tr, sym in additions
            ]
            after_removals = current - set(removals)
            if len(after_removals | set(additions)) > self.cap:
                raise ValueError("ROLLBACK_PEAK_WOULD_EXCEED_CAP")
            return actions
        # Never remove baseline data merely to make room. If add-first could exceed
        # the cap, block the entire rotation before sending its first request.
        if len(current | set(additions)) > self.cap:
            raise ValueError("ADD_FIRST_PEAK_WOULD_EXCEED_CAP")
        return [
            SubscriptionAction(Action.SUBSCRIBE, tr, sym)
            for tr, sym in additions
        ] + [
            SubscriptionAction(Action.UNSUBSCRIBE, tr, sym)
            for tr, sym in removals
        ]

    def start_initial(self, target: set[tuple[str, str]]) -> None:
        if not self.schema.configured:
            self._block("KIS_WS_ACK_SCHEMA_UNVERIFIED")
            raise RuntimeError("KIS_WS_ACK_SCHEMA_UNVERIFIED")
        if self.state is not State.IDLE:
            raise RuntimeError("INITIAL_SUBSCRIPTION_ALREADY_STARTED")
        self.target = set(target)
        self.rollback_target = set()
        self.mode = "INITIAL"
        self.last_completed_kind = None
        try:
            self.queue = self._make_plan(set(), self.target)
        except ValueError as exc:
            self._block(str(exc))
            raise
        self.state = State.APPLYING
        self.last_result = "INITIAL_SUBSCRIPTION_PENDING"
        self._finish_if_empty()

    def start_rotation(self, desired: set[tuple[str, str]]) -> None:
        if not self.ready:
            raise RuntimeError("SUBSCRIPTION_STATE_NOT_READY")
        if not self.pinned.issubset(desired):
            self._block("PINNED_WEEKLY_SET_MISSING")
            raise RuntimeError("PINNED_WEEKLY_SET_MISSING")
        self.target = set(desired)
        self.rollback_target = self.baseline | self.pinned
        self.mode = "ROTATION"
        self.last_completed_kind = None
        try:
            self.queue = self._make_plan(self.confirmed, self.target)
        except ValueError as exc:
            self._block(str(exc))
            raise
        self.state = State.APPLYING
        self.last_result = "ROTATION_PENDING"
        self._finish_if_empty()

    def _finish_if_empty(self) -> None:
        if self.pending is not None or self.queue:
            return
        if self.mode in {"INITIAL", "ROTATION"}:
            if self.confirmed == self.target:
                self.state = State.READY
                self.last_result = "VERIFIED"
                self.last_completed_kind = self.mode
                self.mode = None
            else:
                self._block("CONFIRMED_SET_DIFFERS_FROM_TARGET")
        elif self.mode == "ROLLBACK":
            if self.confirmed == self.rollback_target:
                self._block("ROLLBACK_VERIFIED_OPERATOR_REVIEW_REQUIRED")
            else:
                self._block("ROLLBACK_STATE_UNVERIFIED")

    def prepare_next(self) -> PendingRequest | None:
        if self.state not in {State.APPLYING, State.ROLLING_BACK} or self.pending is not None:
            return None
        if not self.queue:
            self._finish_if_empty()
            return None
        action = self.queue.pop(0)
        self.pending = PendingRequest(
            request_id=uuid.uuid4().hex,
            action=action.action,
            tr_id=action.tr_id,
            symbol=action.symbol,
            session_generation=self.session_generation,
        )
        return self.pending

    def mark_sent(self, request_id: str, *, now: float | None = None) -> None:
        if self.pending is None or self.pending.request_id != request_id:
            self._block("SENT_REQUEST_NOT_PENDING")
            return
        sent_at = time.monotonic() if now is None else float(now)
        self.pending.sent_at = sent_at
        self.pending.deadline = sent_at + self.timeout_seconds

    def mark_send_error(self, request_id: str) -> None:
        if self.pending is not None and self.pending.request_id == request_id:
            self.pending = None
        self.state = State.UNKNOWN
        self.last_result = "SEND_RESULT_UNKNOWN"
        self.queue.clear()

    def check_timeout(self, *, now: float | None = None) -> bool:
        if self.state not in {State.APPLYING, State.ROLLING_BACK}:
            return False
        if self.pending is None or self.pending.deadline is None:
            return False
        current = time.monotonic() if now is None else float(now)
        if current < self.pending.deadline:
            return False
        self.state = State.UNKNOWN
        self.last_result = "ACK_TIMEOUT_UNKNOWN_SERVER_STATE"
        self.queue.clear()
        # Keep pending as evidence of the unresolved request; no more requests are sent.
        return True

    def handle_frame(self, payload: str) -> str:
        # UNKNOWN/BLOCKED are terminal fail-closed states for this controller
        # instance. In particular, a late ACK after timeout must not confirm a
        # server-side change or reopen the queue without operator review.
        if self.state in {State.UNKNOWN, State.BLOCKED}:
            self.last_event = {
                "event": "ACK_IGNORED_TERMINAL_STATE",
                "state": self.state.value,
            }
            return "ACK_IGNORED_TERMINAL_STATE"
        parsed = parse_ack_frame(payload, self.schema)
        if parsed is None:
            return "NOT_ACK"
        if parsed.request_id in self.completed_request_ids and parsed.kind in {"SUCCESS", "REJECT"}:
            self.last_event = {"event": "ACK_DUPLICATE_IGNORED", "request_id": parsed.request_id}
            return "ACK_DUPLICATE_IGNORED"
        if parsed.kind == "UNKNOWN":
            self.state = State.UNKNOWN
            self.last_result = parsed.detail or "ACK_UNRECOGNIZED"
            self.queue.clear()
            self.last_event = {
                "event": "ACK_UNRECOGNIZED",
                "request_id": parsed.request_id,
                "detail": parsed.detail,
            }
            return "ACK_UNRECOGNIZED"
        pending = self.pending
        if pending is None:
            if parsed.request_id in self.completed_request_ids:
                self.last_event = {"event": "ACK_DUPLICATE_IGNORED", "request_id": parsed.request_id}
                return "ACK_DUPLICATE_IGNORED"
            self.state = State.UNKNOWN
            self.last_result = "ACK_WITHOUT_PENDING_REQUEST"
            self.queue.clear()
            self.last_event = {"event": "ACK_WITHOUT_PENDING_REQUEST", "request_id": parsed.request_id}
            return "ACK_UNMATCHED"
        expected_action_value = pending.action
        if (
            parsed.request_id != pending.request_id
            or parsed.action is not expected_action_value
            or parsed.tr_id != pending.tr_id
            or parsed.symbol != pending.symbol
            or pending.session_generation != self.session_generation
        ):
            self.state = State.UNKNOWN
            self.last_result = "ACK_CORRELATION_MISMATCH"
            self.queue.clear()
            self.last_event = {"event": "ACK_CORRELATION_MISMATCH", "request_id": parsed.request_id}
            return "ACK_UNMATCHED"
        if parsed.kind == "SUCCESS":
            key = (pending.tr_id, pending.symbol)
            if pending.action is Action.SUBSCRIBE:
                self.confirmed.add(key)
            else:
                self.confirmed.discard(key)
            self.completed_request_ids.add(pending.request_id)
            self.pending = None
            self.last_event = {
                "event": "ACK_SUCCESS",
                "request_id": pending.request_id,
                "action": pending.action.value,
                "tr_id": pending.tr_id,
                "symbol": pending.symbol,
                "confirmed_count": len(self.confirmed),
            }
            self._finish_if_empty()
            return "ACK_SUCCESS"
        # An explicit reject is known; rollback only ACK-confirmed state.
        self.last_event = {
            "event": "ACK_REJECTED",
            "request_id": pending.request_id,
            "action": pending.action.value,
            "tr_id": pending.tr_id,
            "symbol": pending.symbol,
        }
        self.completed_request_ids.add(pending.request_id)
        self.pending = None
        if self.mode == "ROLLBACK":
            self._block("ROLLBACK_REQUEST_REJECTED")
            return "ACK_REJECTED_ROLLBACK_FAILED"
        target = set() if self.mode == "INITIAL" else (self.baseline | self.pinned)
        self.rollback_target = target
        self.mode = "ROLLBACK"
        try:
            self.queue = self._make_plan(self.confirmed, target, rollback=True)
        except ValueError as exc:
            self._block(f"ROLLBACK_BLOCKED:{exc}")
            return "ACK_REJECTED_ROLLBACK_BLOCKED"
        self.state = State.ROLLING_BACK
        self.last_result = "ROLLBACK_PENDING"
        self._finish_if_empty()
        return "ACK_REJECTED_ROLLBACK_STARTED"

    def mark_session_lost(self) -> None:
        self.state = State.UNKNOWN
        self.last_result = "SESSION_LOST_SERVER_STATE_UNKNOWN"
        self.queue.clear()
        # Invalidate every outstanding request by advancing the session generation.
        self.session_generation = uuid.uuid4().hex
