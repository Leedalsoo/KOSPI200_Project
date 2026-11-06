"""Fail-closed, configuration-driven lifecycle policy for Strategy 6.

This pure state machine is deliberately not an order router. Runtime integration
must persist snapshots and reconcile broker/VSSF orders and positions before
releasing a restored state. Unresolved first_rank/timeout_split values block
entry rather than receiving inferred defaults.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo


class Track6LifecycleError(ValueError):
    pass


class Track6LifecycleStatus(str, Enum):
    BLOCKED_CONFIG = "BLOCKED_CONFIG"
    CONTRACT_PREFLIGHT = "CONTRACT_PREFLIGHT"
    ORDER_WORKING = "ORDER_WORKING"
    CANCEL_PENDING = "CANCEL_PENDING"
    SINGLE_LEG_FILLED = "SINGLE_LEG_FILLED"
    PARTIALLY_EXPOSED = "PARTIALLY_EXPOSED"
    PAIR_ACTIVE = "PAIR_ACTIVE"
    SINGLE_LEG_HELD = "SINGLE_LEG_HELD"
    FORCE_CLOSE_PENDING = "FORCE_CLOSE_PENDING"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    FLAT_CONFIRMED = "FLAT_CONFIRMED"
    ENTRY_WINDOW_CLOSED = "ENTRY_WINDOW_CLOSED"


@dataclass(frozen=True)
class Track6LifecycleConfig:
    first_rank: int | None = None
    timeout_split: str | None = None
    order_timeout_seconds: int = 600
    fallback_on_preflight_unavailable: bool = True
    fallback_on_submitted_order_timeout: bool = False

    def validate(self) -> None:
        if self.first_rank not in {5, 6}:
            raise Track6LifecycleError("TRACK6_FIRST_RANK_UNSET_OR_INVALID")
        if self.timeout_split not in {"per_order", "shared_elapsed"}:
            raise Track6LifecycleError("TRACK6_TIMEOUT_SPLIT_UNSET_OR_INVALID")
        if self.order_timeout_seconds != 600:
            raise Track6LifecycleError("TRACK6_ORDER_TIMEOUT_MUST_BE_600_SECONDS")
        if self.fallback_on_submitted_order_timeout:
            raise Track6LifecycleError("TRACK6_SUBMITTED_TIMEOUT_FALLBACK_FORBIDDEN")


@dataclass(frozen=True)
class Track6RankCandidate:
    rank: int
    put_strike: Decimal
    call_strike: Decimal
    put_identity: Any
    call_identity: Any


@dataclass(frozen=True)
class Track6LifecycleAction:
    kind: str
    leg_id: str | None = None
    client_order_id: str | None = None
    quantity: int = 0
    rank: int | None = None
    reason: str | None = None


@dataclass
class Track6LifecycleSnapshot:
    run_id: str
    trading_date: str
    group_id: str | None = None
    status: Track6LifecycleStatus = Track6LifecycleStatus.BLOCKED_CONFIG
    selected_rank: int | None = None
    candidate_order: tuple[int, ...] = ()
    candidate_cursor: int = 0
    available_candidate_ranks: tuple[int, ...] = ()
    entry_started_at: datetime | None = None
    working_leg: str | None = None
    working_client_order_id: str | None = None
    submitted_at: datetime | None = None
    deadline_at: datetime | None = None
    filled_quantity: dict[str, int] = field(default_factory=lambda: {"put": 0, "call": 0})
    average_fill_price: dict[str, Decimal | None] = field(default_factory=lambda: {"put": None, "call": None})
    open_quantity: dict[str, int] = field(default_factory=lambda: {"put": 0, "call": 0})
    client_order_ids: dict[str, str | None] = field(default_factory=lambda: {"put": None, "call": None})
    force_close_requested_at: datetime | None = None
    last_reason: str | None = None
    version: int = 1


class Track6OrderLifecycle:
    """Deterministic policy for sequential entry, timeout, cancel and recovery."""

    def __init__(self, config: Track6LifecycleConfig, *, run_id: str, trading_date: str) -> None:
        if not run_id.strip() or not trading_date.strip():
            raise Track6LifecycleError("TRACK6_RUN_AND_TRADING_DATE_REQUIRED")
        self.config = config
        self.snapshot = Track6LifecycleSnapshot(run_id=run_id, trading_date=trading_date)
        try:
            config.validate()
        except Track6LifecycleError as exc:
            self.snapshot.last_reason = str(exc)
            self.snapshot.status = Track6LifecycleStatus.BLOCKED_CONFIG
            self.config_valid = False
        else:
            self.config_valid = True

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise Track6LifecycleError("TRACK6_AWARE_TIMESTAMP_REQUIRED")
        return value

    @property
    def entry_rank_order(self) -> tuple[int, ...]:
        if not self.config_valid:
            return ()
        return (self.config.first_rank, 11 - self.config.first_rank)

    def start_preflight(self, candidates: tuple[Track6RankCandidate, ...], now: datetime,
                        *, group_id: str | None = None) -> Track6LifecycleAction:
        now = self._aware(now)
        if not self.config_valid:
            return Track6LifecycleAction("BLOCKED", reason=self.snapshot.last_reason)
        by_rank = {candidate.rank: candidate for candidate in candidates}
        if (not by_rank or len(by_rank) != len(candidates)
                or not set(by_rank).issubset({5, 6})):
            self.snapshot.status = Track6LifecycleStatus.BLOCKED_CONFIG
            self.snapshot.last_reason = "TRACK6_RANK_5_6_CANDIDATES_INVALID"
            return Track6LifecycleAction("BLOCKED", reason=self.snapshot.last_reason)
        self.snapshot.group_id = str(group_id) if group_id else None
        self.snapshot.available_candidate_ranks = tuple(sorted(by_rank))
        self.snapshot.candidate_order = self.entry_rank_order
        self.snapshot.candidate_cursor = 0
        self.snapshot.entry_started_at = now
        self.snapshot.status = Track6LifecycleStatus.CONTRACT_PREFLIGHT
        return Track6LifecycleAction("PREFLIGHT", rank=self.snapshot.candidate_order[0])

    def preflight_result(self, *, rank: int, available: bool, now: datetime) -> Track6LifecycleAction:
        self._aware(now)
        if self.snapshot.status != Track6LifecycleStatus.CONTRACT_PREFLIGHT:
            raise Track6LifecycleError("TRACK6_PREFLIGHT_STATE_REQUIRED")
        expected = self.snapshot.candidate_order[self.snapshot.candidate_cursor]
        if rank != expected:
            raise Track6LifecycleError("TRACK6_RANK_SEQUENCE_VIOLATION")
        available = bool(available and rank in self.snapshot.available_candidate_ranks)
        if available:
            self.snapshot.selected_rank = rank
            return Track6LifecycleAction("SELECT_RANK", rank=rank)
        if self.config.fallback_on_preflight_unavailable and self.snapshot.candidate_cursor == 0:
            self.snapshot.candidate_cursor = 1
            return Track6LifecycleAction("PREFLIGHT", rank=self.snapshot.candidate_order[1],
                                         reason="FIRST_RANK_PREFLIGHT_UNAVAILABLE")
        self.snapshot.status = Track6LifecycleStatus.ENTRY_WINDOW_CLOSED
        self.snapshot.last_reason = "TRACK6_NO_PREFLIGHT_CANDIDATE_AVAILABLE"
        return Track6LifecycleAction("STOP", reason=self.snapshot.last_reason)

    def submit_order(self, *, leg_id: str, client_order_id: str, quantity: int, now: datetime) -> Track6LifecycleAction:
        now = self._aware(now)
        leg = leg_id.lower()
        if leg not in {"put", "call"} or quantity != 1 or not client_order_id.strip():
            raise Track6LifecycleError("TRACK6_SINGLE_LEG_ORDER_INVALID")
        if self.snapshot.working_client_order_id is not None:
            raise Track6LifecycleError("TRACK6_ONLY_ONE_WORKING_ORDER_ALLOWED")
        if self.snapshot.status not in {Track6LifecycleStatus.CONTRACT_PREFLIGHT,
                                        Track6LifecycleStatus.SINGLE_LEG_FILLED}:
            raise Track6LifecycleError("TRACK6_ORDER_SUBMISSION_STATE_INVALID")
        if self.snapshot.open_quantity[leg] > 0 or self.snapshot.filled_quantity[leg] > 0:
            raise Track6LifecycleError("TRACK6_DUPLICATE_LEG_SUBMISSION")
        if self.snapshot.selected_rank is None:
            raise Track6LifecycleError("TRACK6_RANK_NOT_SELECTED")
        if self.snapshot.entry_started_at is None:
            raise Track6LifecycleError("TRACK6_ENTRY_START_REQUIRED")
        base = now if self.config.timeout_split == "per_order" else self.snapshot.entry_started_at
        self.snapshot.working_leg = leg
        self.snapshot.working_client_order_id = client_order_id
        self.snapshot.client_order_ids[leg] = client_order_id
        self.snapshot.submitted_at = now
        self.snapshot.deadline_at = base + timedelta(seconds=self.config.order_timeout_seconds)
        self.snapshot.status = Track6LifecycleStatus.ORDER_WORKING
        return Track6LifecycleAction("SUBMIT", leg, client_order_id, quantity, self.snapshot.selected_rank)

    def timeout_action(self, now: datetime) -> Track6LifecycleAction:
        now = self._aware(now)
        if self.snapshot.status != Track6LifecycleStatus.ORDER_WORKING:
            return Track6LifecycleAction("NOOP")
        if self.snapshot.deadline_at is None or self.snapshot.working_client_order_id is None:
            self._require_reconciliation("TRACK6_TIMEOUT_METADATA_MISSING")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if now < self.snapshot.deadline_at:
            return Track6LifecycleAction("WAIT")
        self.snapshot.status = Track6LifecycleStatus.CANCEL_PENDING
        return Track6LifecycleAction("CANCEL", self.snapshot.working_leg,
                                     self.snapshot.working_client_order_id, reason="TIMEOUT_10M")

    def execution_report(self, *, leg_id: str, client_order_id: str, status: str,
                         filled_quantity: int, remaining_quantity: int,
                         average_fill_price: Decimal | None, now: datetime) -> Track6LifecycleAction:
        self._aware(now)
        leg = leg_id.lower()
        if leg not in {"put", "call"} or client_order_id != self.snapshot.working_client_order_id:
            self._require_reconciliation("TRACK6_ORDER_ID_OR_LEG_MISMATCH")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if filled_quantity < 0 or remaining_quantity < 0 or filled_quantity + remaining_quantity > 1:
            self._require_reconciliation("TRACK6_FILL_QUANTITY_MISMATCH")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if filled_quantity and (average_fill_price is None or Decimal(average_fill_price) <= 0):
            self._require_reconciliation("TRACK6_FILL_PRICE_MISSING")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        status = status.upper()
        if status in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
            self._require_reconciliation("TRACK6_ORDER_STATUS_UNKNOWN")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if status not in {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}:
            self._require_reconciliation("TRACK6_ORDER_STATUS_UNSUPPORTED")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        self.snapshot.filled_quantity[leg] = filled_quantity
        self.snapshot.open_quantity[leg] = filled_quantity
        self.snapshot.average_fill_price[leg] = Decimal(average_fill_price) if average_fill_price is not None else None
        if status == "PARTIALLY_FILLED":
            # Strategy 6 fixes each leg at one indivisible option contract. A
            # partial status cannot be safely represented by fractional lots.
            self._require_reconciliation("TRACK6_PARTIAL_FILL_REQUIRES_EXECUTION_LEVEL_RECONCILIATION")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if status == "NEW":
            self.snapshot.status = Track6LifecycleStatus.ORDER_WORKING
            return Track6LifecycleAction("WAIT_OR_CANCEL", leg, client_order_id,
                                         quantity=remaining_quantity)
        if status == "REJECTED":
            if filled_quantity > 0:
                self._require_reconciliation("TRACK6_REJECTED_REPORT_CONTAINS_FILLS")
                return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
            self.snapshot.working_client_order_id = None
            self.snapshot.working_leg = None
            self.snapshot.status = (Track6LifecycleStatus.SINGLE_LEG_HELD if any(self.snapshot.open_quantity.values())
                                    else Track6LifecycleStatus.ENTRY_WINDOW_CLOSED)
            self.snapshot.last_reason = "TRACK6_ORDER_REJECTED_NO_FALLBACK"
            return Track6LifecycleAction("STOP", reason=self.snapshot.last_reason)
        if status == "CANCELLED":
            self.snapshot.working_client_order_id = None
            self.snapshot.working_leg = None
            if filled_quantity == 0:
                self.snapshot.status = (Track6LifecycleStatus.SINGLE_LEG_HELD if any(self.snapshot.open_quantity.values())
                                        else Track6LifecycleStatus.ENTRY_WINDOW_CLOSED)
                self.snapshot.last_reason = "TRACK6_TIMEOUT_CANCELLED_ZERO_FILL"
            elif filled_quantity == 1:
                self.snapshot.status = Track6LifecycleStatus.SINGLE_LEG_FILLED
            else:
                self.snapshot.status = Track6LifecycleStatus.PARTIALLY_EXPOSED
            return Track6LifecycleAction("RECONCILE_POSITION", leg, client_order_id,
                                         quantity=filled_quantity)
        if status == "FILLED":
            if filled_quantity != 1 or remaining_quantity != 0:
                self._require_reconciliation("TRACK6_FILLED_REPORT_QUANTITY_INCONSISTENT")
                return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
            self.snapshot.working_client_order_id = None
            self.snapshot.working_leg = None
            self.snapshot.status = (Track6LifecycleStatus.PAIR_ACTIVE
                                    if all(self.snapshot.open_quantity.values())
                                    else Track6LifecycleStatus.SINGLE_LEG_FILLED)
            return Track6LifecycleAction("SUBMIT_OPPOSITE" if self.snapshot.status == Track6LifecycleStatus.SINGLE_LEG_FILLED
                                         else "PAIR_COMPLETE", leg, client_order_id, quantity=1)
        return Track6LifecycleAction("NOOP")

    def force_close_due(self, now: datetime) -> Track6LifecycleAction:
        now = self._aware(now)
        kst_now = now.astimezone(ZoneInfo("Asia/Seoul"))
        if kst_now.strftime("%H:%M:%S") < "15:10:00":
            return Track6LifecycleAction("NOOP")
        if self.snapshot.status in {Track6LifecycleStatus.ORDER_WORKING,
                                    Track6LifecycleStatus.CANCEL_PENDING}:
            self.snapshot.status = Track6LifecycleStatus.FORCE_CLOSE_PENDING
            self.snapshot.force_close_requested_at = now
            return Track6LifecycleAction("CANCEL_AND_RECONCILE", self.snapshot.working_leg,
                                         self.snapshot.working_client_order_id,
                                         reason="15:10_FORCE_CLOSE_PRIORITY")
        residuals = {leg: qty for leg, qty in self.snapshot.open_quantity.items() if qty > 0}
        if not residuals:
            self.snapshot.status = Track6LifecycleStatus.FLAT_CONFIRMED
            return Track6LifecycleAction("FLAT_CONFIRMED")
        self.snapshot.status = Track6LifecycleStatus.FORCE_CLOSE_PENDING
        self.snapshot.force_close_requested_at = now
        return Track6LifecycleAction("FORCE_CLOSE", quantity=sum(residuals.values()),
                                     reason="15:10_FORCE_CLOSE_PRIORITY")

    def close_leg_filled(self, *, leg_id: str, filled_quantity: int) -> Track6LifecycleAction:
        leg = str(leg_id).lower()
        if leg not in {"put", "call"} or int(filled_quantity) != 1:
            self._require_reconciliation("TRACK6_EXIT_FILL_IDENTITY_OR_QUANTITY_INVALID")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        if self.snapshot.open_quantity.get(leg, 0) != 1:
            self._require_reconciliation("TRACK6_EXIT_WITHOUT_OPEN_LEG")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        self.snapshot.open_quantity[leg] = 0
        if not any(self.snapshot.open_quantity.values()):
            self.snapshot.status = Track6LifecycleStatus.FLAT_CONFIRMED
            return Track6LifecycleAction("FLAT_CONFIRMED", leg_id=leg)
        self.snapshot.status = Track6LifecycleStatus.SINGLE_LEG_HELD
        return Track6LifecycleAction("LEG_CLOSED", leg_id=leg)

    def complete_force_close(self, *, remaining_positions: dict[str, int], orders_reconciled: bool) -> Track6LifecycleAction:
        if (not orders_reconciled or not {"put", "call"}.issubset(remaining_positions)
                or any(int(qty) != 0 for qty in remaining_positions.values())):
            self._require_reconciliation("TRACK6_FORCE_CLOSE_NOT_FLAT_OR_ORDERS_UNRECONCILED")
            return Track6LifecycleAction("RECONCILE", reason=self.snapshot.last_reason)
        self.snapshot.open_quantity = {"put": 0, "call": 0}
        self.snapshot.status = Track6LifecycleStatus.FLAT_CONFIRMED
        self.snapshot.working_client_order_id = None
        self.snapshot.working_leg = None
        return Track6LifecycleAction("FLAT_CONFIRMED")

    def export_snapshot(self) -> dict[str, Any]:
        payload = asdict(self.snapshot)
        payload["status"] = self.snapshot.status.value
        payload["entry_started_at"] = self.snapshot.entry_started_at.isoformat() if self.snapshot.entry_started_at else None
        payload["submitted_at"] = self.snapshot.submitted_at.isoformat() if self.snapshot.submitted_at else None
        payload["deadline_at"] = self.snapshot.deadline_at.isoformat() if self.snapshot.deadline_at else None
        payload["force_close_requested_at"] = self.snapshot.force_close_requested_at.isoformat() if self.snapshot.force_close_requested_at else None
        payload["average_fill_price"] = {key: str(value) if value is not None else None
                                         for key, value in self.snapshot.average_fill_price.items()}
        return payload

    @classmethod
    def restore_snapshot(cls, config: Track6LifecycleConfig, payload: dict[str, Any]) -> "Track6OrderLifecycle":
        machine = cls(config, run_id=str(payload.get("run_id", "")),
                      trading_date=str(payload.get("trading_date", "")))
        if not machine.config_valid:
            return machine
        try:
            snap = Track6LifecycleSnapshot(
                run_id=str(payload["run_id"]), trading_date=str(payload["trading_date"]),
                group_id=str(payload["group_id"]) if payload.get("group_id") else None,
                status=Track6LifecycleStatus(payload["status"]),
                selected_rank=payload.get("selected_rank"),
                candidate_order=tuple(payload.get("candidate_order", ())),
                candidate_cursor=int(payload.get("candidate_cursor", 0)),
                available_candidate_ranks=tuple(payload.get("available_candidate_ranks", ())),
                entry_started_at=datetime.fromisoformat(payload["entry_started_at"]) if payload.get("entry_started_at") else None,
                working_leg=payload.get("working_leg"),
                working_client_order_id=payload.get("working_client_order_id"),
                submitted_at=datetime.fromisoformat(payload["submitted_at"]) if payload.get("submitted_at") else None,
                deadline_at=datetime.fromisoformat(payload["deadline_at"]) if payload.get("deadline_at") else None,
                filled_quantity={k: int(v) for k, v in payload["filled_quantity"].items()},
                average_fill_price={k: Decimal(v) if v is not None else None for k, v in payload["average_fill_price"].items()},
                open_quantity={k: int(v) for k, v in payload["open_quantity"].items()},
                client_order_ids=dict(payload["client_order_ids"]),
                force_close_requested_at=datetime.fromisoformat(payload["force_close_requested_at"]) if payload.get("force_close_requested_at") else None,
                last_reason=payload.get("last_reason"), version=int(payload.get("version", 1)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            machine._require_reconciliation("TRACK6_PERSISTED_STATE_INVALID")
            return machine
        machine.snapshot = snap
        # A snapshot alone never proves broker/position state after restart.
        machine._require_reconciliation("TRACK6_RESTART_AUTHORITATIVE_RECONCILIATION_REQUIRED")
        return machine

    def complete_restart_reconciliation(self, *, open_orders: dict[str, Any],
                                         positions: dict[str, int],
                                         order_ids_match: bool) -> Track6LifecycleAction:
        if self.snapshot.status != Track6LifecycleStatus.RECONCILIATION_REQUIRED:
            raise Track6LifecycleError("TRACK6_RESTART_RECONCILIATION_STATE_REQUIRED")
        if not order_ids_match:
            return Track6LifecycleAction("BLOCKED", reason="TRACK6_ORDER_ID_RECONCILIATION_FAILED")
        expected_order = self.snapshot.working_client_order_id
        report = open_orders.get(expected_order) if expected_order else None
        if expected_order and report is None:
            return Track6LifecycleAction("BLOCKED", reason="TRACK6_PENDING_ORDER_MISSING_FROM_AUTHORITATIVE_SOURCE")
        if not {"put", "call"}.issubset(positions):
            return Track6LifecycleAction("BLOCKED", reason="TRACK6_AUTHORITATIVE_POSITION_SNAPSHOT_INCOMPLETE")
        normalized = {leg: int(positions[leg]) for leg in ("put", "call")}
        if any(value < 0 or value > 1 for value in normalized.values()):
            return Track6LifecycleAction("BLOCKED", reason="TRACK6_POSITION_QUANTITY_INVALID")
        if expected_order:
            report_id = str(getattr(report, "client_order_id", expected_order))
            status = str(getattr(report, "status", report)).upper()
            if report_id != expected_order:
                return Track6LifecycleAction("BLOCKED", reason="TRACK6_AUTHORITATIVE_ORDER_ID_MISMATCH")
            if status in {"NEW", "PARTIALLY_FILLED"}:
                if normalized != self.snapshot.open_quantity:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_POSITION_STATE_MISMATCH")
            elif status in {"FILLED", "CANCELLED"}:
                leg = self.snapshot.working_leg
                if leg not in {"put", "call"}:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_PERSISTED_WORKING_LEG_MISSING")
                filled = int(getattr(report, "filled_quantity", getattr(report, "executed_qty", 0)) or 0)
                remaining = int(getattr(report, "remaining_quantity", getattr(report, "remaining_qty", 0)) or 0)
                price = getattr(report, "execution_price", getattr(report, "executed_price", None))
                if filled not in {0, 1} or remaining not in {0, 1} or filled + remaining != 1:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_AUTHORITATIVE_FILL_QUANTITY_INVALID")
                if filled == 1:
                    if price is None or Decimal(str(price)) <= 0:
                        return Track6LifecycleAction("BLOCKED", reason="TRACK6_AUTHORITATIVE_FILL_PRICE_MISSING")
                    self.snapshot.filled_quantity[leg] = 1
                    self.snapshot.open_quantity[leg] = 1
                    self.snapshot.average_fill_price[leg] = Decimal(str(price))
                self.snapshot.working_client_order_id = None
                self.snapshot.working_leg = None
                if normalized != self.snapshot.open_quantity:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_POSITION_STATE_MISMATCH")
            elif status == "REJECTED":
                if int(getattr(report, "filled_quantity", getattr(report, "executed_qty", 0)) or 0) != 0:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_REJECTED_ORDER_HAS_FILL")
                self.snapshot.working_client_order_id = None
                self.snapshot.working_leg = None
                if normalized != self.snapshot.open_quantity:
                    return Track6LifecycleAction("BLOCKED", reason="TRACK6_POSITION_STATE_MISMATCH")
            else:
                return Track6LifecycleAction("BLOCKED", reason="TRACK6_PENDING_ORDER_STATUS_MISMATCH")
        elif normalized != self.snapshot.open_quantity:
            return Track6LifecycleAction("BLOCKED", reason="TRACK6_POSITION_STATE_MISMATCH")
        self.snapshot.status = (
            Track6LifecycleStatus.ORDER_WORKING if self.snapshot.working_client_order_id
            else Track6LifecycleStatus.PAIR_ACTIVE if all(normalized.values())
            else Track6LifecycleStatus.SINGLE_LEG_HELD if any(normalized.values())
            else Track6LifecycleStatus.FLAT_CONFIRMED
        )
        self.snapshot.last_reason = None
        return Track6LifecycleAction("RECONCILED")

    def _require_reconciliation(self, reason: str) -> None:
        self.snapshot.status = Track6LifecycleStatus.RECONCILIATION_REQUIRED
        self.snapshot.last_reason = reason