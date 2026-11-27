from __future__ import annotations

import math
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.position_provenance import (
    PositionLotCloseEvent,
    PositionLotProvenance,
    PositionRole,
)
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import (
    BrokerOrderCommand,
    DataQuality,
    ExecutionFill,
    ExecutionLeg,
    ExecutionReport,
    MultiLegExecutionPlan,
    OptionInstrumentIdentity,
)
from core.oms.position_group import (
    LegStatus,
    PositionGroup,
    PositionGroupLeg,
    PositionGroupLegPnL,
    PositionGroupSnapshot,
)
from core.strategy.track4_gamma_scalping import Track4State
from environments.virtual.authoritative_vssf.canonical import (
    CanonicalExecutionReport,
    VSSFExecutionFill,
    VSSFOrderResult,
)
from environments.virtual.position.virtual_position_aggregate import (
    VirtualPositionAggregate,
)
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOptionType,
    CanonicalOrderCommand,
    CanonicalOrderSide,
)

_SCHEMA_VERSION = 1
_DATACLASS_TYPES = (
    BrokerOrderCommand, DataQuality, ExecutionFill, ExecutionLeg, ExecutionReport,
    MultiLegExecutionPlan, OptionInstrumentIdentity, FuturesInstrumentIdentity,
    PositionLotCloseEvent, PositionLotProvenance, Track9FeeRecord, PositionGroup,
    PositionGroupLeg, PositionGroupLegPnL, PositionGroupSnapshot, Track4State,
    CanonicalExecutionReport, VSSFExecutionFill, VSSFOrderResult, VirtualPositionAggregate, CanonicalOrderCommand,
)
_ENUM_TYPES = (
    FuturesProductType, PositionRole, LegStatus, CanonicalAssetType,
    CanonicalOptionType, CanonicalOrderSide,
)
_TYPE_BY_TAG = {f"{item.__module__}.{item.__qualname__}": item for item in _DATACLASS_TYPES}
_ENUM_BY_TAG = {f"{item.__module__}.{item.__qualname__}": item for item in _ENUM_TYPES}


class ValidationOnlyS4RuntimeSnapshotAdapter:
    """Allowlisted JSON snapshot/restore for synthetic S4 Virtual runtime objects."""

    RUNTIME_USE = "PROHIBITED_OUTSIDE_VALIDATION"

    def __init__(self, *, source_namespace: str, account_id: str, execution_source_id: str) -> None:
        if not isinstance(source_namespace, str) or not source_namespace.startswith(("SYNTHETIC:", "VALIDATION_ONLY:")):
            raise ValueError("S4_RUNTIME_SNAPSHOT_VALIDATION_NAMESPACE_REQUIRED")
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("S4_RUNTIME_SNAPSHOT_ACCOUNT_ID_REQUIRED")
        if not isinstance(execution_source_id, str) or not execution_source_id.startswith(("SYNTHETIC:", "VALIDATION_ONLY:")):
            raise ValueError("S4_RUNTIME_SNAPSHOT_EXECUTION_SOURCE_ID_REQUIRED")
        self.source_namespace = source_namespace
        self.account_id = account_id
        self.execution_source_id = execution_source_id

    def encode_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("S4_RUNTIME_SNAPSHOT_NONFINITE_NUMBER")
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("S4_RUNTIME_SNAPSHOT_NONFINITE_DECIMAL")
            return {"$type": "decimal", "value": str(value)}
        if isinstance(value, datetime):
            aware = value.tzinfo is not None and value.utcoffset() is not None
            return {"$type": "datetime", "value": value.isoformat(), "timezone_aware": aware}
        if isinstance(value, Enum):
            tag = f"{type(value).__module__}.{type(value).__qualname__}"
            if tag not in _ENUM_BY_TAG:
                raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")
            return {"$type": "enum", "class": tag, "value": value.value}
        if isinstance(value, tuple):
            return {"$type": "tuple", "items": [self.encode_value(item) for item in value]}
        if isinstance(value, list):
            return {"$type": "list", "items": [self.encode_value(item) for item in value]}
        if isinstance(value, set):
            encoded = [self.encode_value(item) for item in value]
            encoded.sort(key=lambda item: repr(item))
            return {"$type": "set", "items": encoded}
        if isinstance(value, dict):
            return {
                "$type": "dict",
                "items": [[self.encode_value(key), self.encode_value(item)] for key, item in value.items()],
            }
        if is_dataclass(value) and not isinstance(value, type):
            tag = f"{type(value).__module__}.{type(value).__qualname__}"
            if tag not in _TYPE_BY_TAG:
                raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")
            return {
                "$type": "dataclass", "class": tag,
                "fields": {field.name: self.encode_value(getattr(value, field.name)) for field in fields(value)},
            }
        raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")

    def decode_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("S4_RUNTIME_SNAPSHOT_NONFINITE_NUMBER")
            return value
        if not isinstance(value, dict) or not isinstance(value.get("$type"), str):
            raise TypeError("S4_RUNTIME_SNAPSHOT_ENVELOPE_INVALID")
        kind = value["$type"]
        if kind == "decimal":
            result = Decimal(value["value"])
            if not result.is_finite():
                raise ValueError("S4_RUNTIME_SNAPSHOT_NONFINITE_DECIMAL")
            return result
        if kind == "datetime":
            result = datetime.fromisoformat(value["value"])
            aware = result.tzinfo is not None and result.utcoffset() is not None
            if aware is not value.get("timezone_aware"):
                raise ValueError("S4_RUNTIME_SNAPSHOT_DATETIME_AWARENESS_MISMATCH")
            return result
        if kind == "enum":
            enum_type = _ENUM_BY_TAG.get(value.get("class"))
            if enum_type is None:
                raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")
            return enum_type(value["value"])
        if kind in {"tuple", "list", "set"}:
            items = [self.decode_value(item) for item in value.get("items", [])]
            return tuple(items) if kind == "tuple" else set(items) if kind == "set" else items
        if kind == "dict":
            pairs = value.get("items")
            if not isinstance(pairs, list):
                raise ValueError("S4_RUNTIME_SNAPSHOT_MAPPING_INVALID")
            result = {}
            for pair in pairs:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("S4_RUNTIME_SNAPSHOT_MAPPING_INVALID")
                key, item = self.decode_value(pair[0]), self.decode_value(pair[1])
                if key in result:
                    raise ValueError("S4_RUNTIME_SNAPSHOT_DUPLICATE_MAPPING_KEY")
                result[key] = item
            return result
        if kind == "dataclass":
            data_type = _TYPE_BY_TAG.get(value.get("class"))
            raw_fields = value.get("fields")
            if data_type is None:
                raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")
            if not isinstance(raw_fields, dict):
                raise ValueError("S4_RUNTIME_SNAPSHOT_DATACLASS_FIELDS_INVALID")
            allowed = {field.name for field in fields(data_type)}
            if set(raw_fields) != allowed:
                raise ValueError("S4_RUNTIME_SNAPSHOT_DATACLASS_FIELDS_MISMATCH")
            return data_type(**{name: self.decode_value(item) for name, item in raw_fields.items()})
        raise ValueError("S4_RUNTIME_SNAPSHOT_TYPE_NOT_ALLOWLISTED")

    @staticmethod
    def _require_attrs(owner: Any, names: tuple[str, ...], code: str) -> None:
        if any(not hasattr(owner, name) for name in names):
            raise ValueError(code)

    def snapshot(
        self, *, runtime: Any, bridge: Any, strategy: Any, run_id: str,
        strategy_id: str, group_id: str, callback_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(run_id, str) or not run_id.startswith(("SYNTHETIC:", "VALIDATION_ONLY:")):
            raise ValueError("S4_RUNTIME_SNAPSHOT_VALIDATION_RUN_REQUIRED")
        if getattr(runtime, "validation_run_id", None) != run_id:
            raise ValueError("S4_RUNTIME_SNAPSHOT_RUN_SCOPE_MISMATCH")
        if getattr(runtime, "validation_candidate_id", None) is None:
            raise ValueError("S4_RUNTIME_SNAPSHOT_CANDIDATE_SCOPE_REQUIRED")
        if getattr(bridge, "run_id", None) != run_id:
            raise ValueError("S4_RUNTIME_SNAPSHOT_BRIDGE_RUN_SCOPE_MISMATCH")
        if getattr(strategy, "strategy_id", None) != strategy_id:
            raise ValueError("S4_RUNTIME_SNAPSHOT_STRATEGY_SCOPE_MISMATCH")
        self._require_attrs(runtime, ("account", "execution_engine", "order_book", "_submitted_at", "_lifecycle_results", "metrics"), "S4_RUNTIME_SNAPSHOT_VSSF_STATE_INCOMPLETE")
        bridge_fields = (
            "groups", "position_groups", "_group_plans", "_track2_entry_progress_disabled_groups",
            "position_lot_store", "fee_ledger", "provenance", "execution_legs", "leg_positions",
            "pending_legs", "_applied_execution_fingerprints", "_s9_retry_schedule",
            "_s9_retry_attempts", "_pending_attempt_ids",
        )
        self._require_attrs(bridge, bridge_fields, "S4_RUNTIME_SNAPSHOT_BRIDGE_STATE_INCOMPLETE")
        group_ids = set(bridge.groups) | set(bridge._group_plans) | set(bridge.position_groups.all())
        if group_ids - {group_id}:
            raise ValueError("S4_RUNTIME_SNAPSHOT_GROUP_SCOPE_MISMATCH")
        if any(
            lot.run_id != run_id or lot.strategy_id != strategy_id or lot.group_id != group_id
            for lot in bridge.position_lot_store.history()
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_POSITION_LOT_SCOPE_MISMATCH")
        if any(
            fee.run_id != run_id or fee.strategy_id != strategy_id or fee.group_id != group_id
            for fee in bridge.fee_ledger._records.values()
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_FEE_SCOPE_MISMATCH")
        if any(
            pending_plan.group_id != group_id or pending_plan.strategy_id != strategy_id
            for pending_plan, _pending_leg, _pending_command in bridge.pending_legs.values()
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_PENDING_ORDER_SCOPE_MISMATCH")
        account = runtime.account
        self._require_attrs(account, ("balance", "realized_pnl", "unrealized_pnl", "positions", "free_margin", "used_margin", "pnl_engine", "margin_engine", "ledger_engine"), "S4_RUNTIME_SNAPSHOT_ACCOUNT_STATE_INCOMPLETE")
        account_state = {
            "validation_run_id": account.validation_run_id,
            "validation_candidate_id": account.validation_candidate_id,
            "balance": account.balance, "realized_pnl": account.realized_pnl,
            "unrealized_pnl": account.unrealized_pnl, "positions": account.positions,
            "free_margin": account.free_margin, "used_margin": account.used_margin,
            "pnl_realized": account.pnl_engine.realized_pnl,
            "pnl_unrealized": account.pnl_engine.unrealized_pnl,
            "margin_initial_capital": account.margin_engine.initial_capital,
            "ledger_transactions": account.ledger_engine.transactions,
        }
        vssf = {
            "execution_reports": runtime.execution_engine.reports,
            "execution_sequence": runtime.execution_engine._seq,
            "order_books": runtime.order_book.books,
            "pending_orders": runtime.order_book.orders,
            "submitted_at": runtime._submitted_at,
            "lifecycle_results": runtime._lifecycle_results,
            "market_time": runtime._market_time,
            "metrics": runtime.metrics,
        }
        position_groups = {
            "groups": bridge.position_groups._groups,
            "snapshots": bridge.position_groups._snapshots,
        }
        bridge_state = {
            "groups": bridge.groups, "position_groups": position_groups,
            "group_plans": bridge._group_plans,
            "track2_entry_progress_disabled_groups": bridge._track2_entry_progress_disabled_groups,
            "provenance": bridge.provenance, "execution_legs": bridge.execution_legs,
            "leg_positions": bridge.leg_positions,
            "applied_execution_fingerprints": bridge._applied_execution_fingerprints,
            "s9_retry_schedule": bridge._s9_retry_schedule,
            "s9_retry_attempts": bridge._s9_retry_attempts,
            "pending_attempt_ids": bridge._pending_attempt_ids,
        }
        pending_orders = {
            "vssf": runtime.order_book.orders,
            "bridge": bridge.pending_legs,
            "vssf_runtime": vssf,
        }
        position_lots = {
            "lots": bridge.position_lot_store._lots,
            "history": bridge.position_lot_store._history,
            "close_events": bridge.position_lot_store._close_events,
            "executions": bridge.position_lot_store._executions,
        }
        fee_ledger = {"records": bridge.fee_ledger._records}
        strategy_state = {
            "strategy_id": strategy_id, "version": getattr(strategy, "version", None),
            "equity_threshold": strategy.equity_threshold, "enabled": strategy.enabled,
            "capital_gate_min": strategy.capital_gate_min,
            "risk_limits_available": strategy.risk_limits_available,
            "state": strategy.state, "exit_pending": strategy._exit_pending,
        }
        execution_watermarks = {
            "vssf_sequence": runtime.execution_engine._seq,
            "vssf_execution_ids": tuple(report.exec_id for report in runtime.execution_engine.reports),
            "bridge_execution_ids": tuple(sorted(bridge._applied_execution_fingerprints)),
            "account_execution_ids": tuple(
                str(row.get("exec_id")) for row in account.ledger_engine.transactions
                if isinstance(row, dict) and row.get("exec_id") is not None
            ),
        }
        raw_sections = {
            "account_state": account_state, "bridge_state": bridge_state,
            "strategy_state": strategy_state, "pending_orders": pending_orders,
            "position_lots": position_lots, "fee_ledger": fee_ledger,
            "execution_watermarks": execution_watermarks,
            "callback_state": callback_state or {},
        }
        return {
            "schema_version": _SCHEMA_VERSION, "runtime_use": self.RUNTIME_USE,
            "source_namespace": self.source_namespace, "account_id": self.account_id,
            "execution_source_id": self.execution_source_id, "run_id": run_id, "strategy_id": strategy_id, "group_id": group_id,
            "candidate_id": runtime.validation_candidate_id,
            **{key: self.encode_value(value) for key, value in raw_sections.items()},
        }

    def checkpoint_envelope(
        self, snapshot: dict[str, Any], *, identity: Any, phase: str,
        checkpoint_id: str, revision: int, previous_checkpoint_id: str | None,
    ) -> dict[str, Any]:
        from application.composition.validation_only_s4_checkpoint import (
            S4ExecutionEventIdentity,
        )

        if not isinstance(identity, S4ExecutionEventIdentity):
            raise TypeError("S4_RUNTIME_SNAPSHOT_EVENT_IDENTITY_REQUIRED")
        if identity.source_namespace != self.source_namespace or identity.account_id != self.account_id or identity.execution_source_id != self.execution_source_id:
            raise ValueError("S4_RUNTIME_SNAPSHOT_CHECKPOINT_IDENTITY_MISMATCH")
        if not isinstance(snapshot, dict) or snapshot.get("runtime_use") != self.RUNTIME_USE:
            raise ValueError("S4_RUNTIME_SNAPSHOT_SCHEMA_INVALID")
        for key, expected in (
            ("source_namespace", self.source_namespace),
            ("account_id", self.account_id),
            ("execution_source_id", self.execution_source_id),
        ):
            if snapshot.get(key) != expected:
                raise ValueError("S4_RUNTIME_SNAPSHOT_CHECKPOINT_SCOPE_MISMATCH")
        if phase not in {"ACCOUNT_APPLIED", "BRIDGE_APPLIED", "CALLBACK_APPLIED", "ACKED"}:
            raise ValueError("S4_RUNTIME_SNAPSHOT_CHECKPOINT_PHASE_INVALID")
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip() or revision < 1:
            raise ValueError("S4_RUNTIME_SNAPSHOT_CHECKPOINT_REVISION_INVALID")
        watermarks = self.decode_value(snapshot["execution_watermarks"])
        if identity.execution_id not in watermarks["account_execution_ids"]:
            raise ValueError("S4_RUNTIME_SNAPSHOT_ACCOUNT_EXECUTION_WATERMARK_MISSING")
        if phase in {"BRIDGE_APPLIED", "CALLBACK_APPLIED", "ACKED"} and identity.execution_id not in watermarks["bridge_execution_ids"]:
            raise ValueError("S4_RUNTIME_SNAPSHOT_BRIDGE_EXECUTION_WATERMARK_MISSING")
        state_keys = (
            "account_state", "bridge_state", "strategy_state", "pending_orders",
            "position_lots", "fee_ledger", "execution_watermarks", "callback_state",
        )
        state = {key: snapshot[key] for key in state_keys}
        return {
            "schema_version": 1, "validation_only": True, "runtime_use": self.RUNTIME_USE,
            "phase": phase, "checkpoint_id": checkpoint_id,
            "source_namespace": self.source_namespace, "account_id": self.account_id,
            "execution_source_id": self.execution_source_id, "execution_id": identity.execution_id,
            "run_id": snapshot["run_id"], "strategy_id": snapshot["strategy_id"],
            "group_id": snapshot["group_id"], "candidate_id": snapshot["candidate_id"],
            "revision": revision, "previous_checkpoint_id": previous_checkpoint_id,
            "state": state,
        }

    def restore(
        self, snapshot: dict[str, Any], *, runtime: Any, bridge: Any, strategy: Any,
        run_id: str, strategy_id: str, group_id: str,
        callback_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(snapshot, dict) and isinstance(snapshot.get("state"), dict):
            envelope = snapshot
            snapshot = {
                "schema_version": _SCHEMA_VERSION, "runtime_use": envelope.get("runtime_use"),
                "source_namespace": envelope.get("source_namespace"), "account_id": envelope.get("account_id"),
                "execution_source_id": envelope.get("execution_source_id"),
                "run_id": envelope.get("run_id"), "strategy_id": envelope.get("strategy_id"),
                "group_id": envelope.get("group_id"), "candidate_id": envelope.get("candidate_id"),
                **envelope["state"],
            }
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != _SCHEMA_VERSION or snapshot.get("runtime_use") != self.RUNTIME_USE:
            raise ValueError("S4_RUNTIME_SNAPSHOT_SCHEMA_INVALID")
        for key, expected in (("source_namespace", self.source_namespace), ("account_id", self.account_id), ("execution_source_id", self.execution_source_id), ("run_id", run_id), ("strategy_id", strategy_id), ("group_id", group_id)):
            if snapshot.get(key) != expected:
                raise ValueError("S4_RUNTIME_SNAPSHOT_SCOPE_MISMATCH")
        if getattr(runtime, "validation_run_id", None) != run_id or getattr(runtime, "validation_candidate_id", None) != snapshot.get("candidate_id"):
            raise ValueError("S4_RUNTIME_SNAPSHOT_RUNTIME_SCOPE_MISMATCH")
        if getattr(bridge, "run_id", None) != run_id or getattr(strategy, "strategy_id", None) != strategy_id:
            raise ValueError("S4_RUNTIME_SNAPSHOT_TARGET_SCOPE_MISMATCH")
        sections = {key: self.decode_value(snapshot[key]) for key in (
            "account_state", "bridge_state", "strategy_state", "pending_orders",
            "position_lots", "fee_ledger", "execution_watermarks", "callback_state",
        )}
        state = sections["strategy_state"]
        expected_config = (state["version"], state["equity_threshold"], state["enabled"], state["capital_gate_min"], state["risk_limits_available"])
        target_config = (getattr(strategy, "version", None), strategy.equity_threshold, strategy.enabled, strategy.capital_gate_min, strategy.risk_limits_available)
        if expected_config != target_config:
            raise ValueError("S4_RUNTIME_SNAPSHOT_STRATEGY_CONFIG_MISMATCH")
        account_state = sections["account_state"]
        if account_state["validation_run_id"] != run_id or account_state["validation_candidate_id"] != snapshot["candidate_id"]:
            raise ValueError("S4_RUNTIME_SNAPSHOT_ACCOUNT_SCOPE_MISMATCH")
        bridge_state = sections["bridge_state"]
        lots = sections["position_lots"]
        fees = sections["fee_ledger"]
        pending = sections["pending_orders"]
        vssf_state = pending["vssf_runtime"]
        if vssf_state["pending_orders"] != pending["vssf"]:
            raise ValueError("S4_RUNTIME_SNAPSHOT_PENDING_ORDER_SECTION_MISMATCH")
        watermarks = sections["execution_watermarks"]
        vssf_execution_ids = tuple(report.exec_id for report in vssf_state["execution_reports"])
        bridge_execution_ids = tuple(sorted(bridge_state["applied_execution_fingerprints"]))
        account_execution_ids = tuple(
            str(row.get("exec_id")) for row in account_state["ledger_transactions"]
            if isinstance(row, dict) and row.get("exec_id") is not None
        )
        if (
            len(vssf_execution_ids) != len(set(vssf_execution_ids))
            or vssf_execution_ids != tuple(watermarks["vssf_execution_ids"])
            or bridge_execution_ids != tuple(watermarks["bridge_execution_ids"])
            or account_execution_ids != tuple(watermarks["account_execution_ids"])
            or len(account_execution_ids) != len(set(account_execution_ids))
            or vssf_state["execution_sequence"] != watermarks["vssf_sequence"]
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_EXECUTION_WATERMARK_MISMATCH")
        # Validate the decoded structures before publishing any target mutation.
        if not isinstance(account_state["positions"], dict) or not isinstance(bridge_state["groups"], dict):
            raise TypeError("S4_RUNTIME_SNAPSHOT_STATE_SHAPE_INVALID")
        if set(bridge_state["groups"]) - {group_id} or set(bridge_state["group_plans"]) - {group_id}:
            raise ValueError("S4_RUNTIME_SNAPSHOT_GROUP_SCOPE_MISMATCH")
        if any(
            lot.run_id != run_id or lot.strategy_id != strategy_id or lot.group_id != group_id
            for lot in lots["history"]
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_POSITION_LOT_SCOPE_MISMATCH")
        if any(
            fee.run_id != run_id or fee.strategy_id != strategy_id or fee.group_id != group_id
            for fee in fees["records"].values()
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_FEE_SCOPE_MISMATCH")
        if any(
            pending_plan.group_id != group_id or pending_plan.strategy_id != strategy_id
            for pending_plan, _pending_leg, _pending_command in pending["bridge"].values()
        ):
            raise ValueError("S4_RUNTIME_SNAPSHOT_PENDING_ORDER_SCOPE_MISMATCH")
        from contracts.track9_position_read_models import (
            Track9InsurancePositionReadModel,
            Track9OptionPositionAttributionReadModel,
        )
        from environments.virtual.authoritative_vssf.track9_fee_ledger import (
            VirtualTrack9FeeLedger,
        )
        from environments.virtual.position.virtual_position_lot_store import (
            VirtualPositionLotStore,
        )
        new_lot_store = VirtualPositionLotStore()
        new_lot_store._lots = lots["lots"]
        new_lot_store._history = lots["history"]
        new_lot_store._close_events = lots["close_events"]
        new_lot_store._executions = lots["executions"]
        new_fee_ledger = VirtualTrack9FeeLedger()
        new_fee_ledger._records = fees["records"]
        # All decoded objects and dependent stores are ready; apply as one in-memory publication.
        account = runtime.account
        account.balance = account_state["balance"]
        account.realized_pnl = account_state["realized_pnl"]
        account.unrealized_pnl = account_state["unrealized_pnl"]
        account.positions.clear(); account.positions.update(account_state["positions"])
        account.free_margin = account_state["free_margin"]
        account.used_margin = account_state["used_margin"]
        account.pnl_engine.realized_pnl = account_state["pnl_realized"]
        account.pnl_engine.unrealized_pnl = account_state["pnl_unrealized"]
        account.margin_engine.initial_capital = account_state["margin_initial_capital"]
        account.ledger_engine.transactions = account_state["ledger_transactions"]
        # VSSF-owned execution and order state is restored independently from Bridge projections.
        runtime.execution_engine.reports = vssf_state["execution_reports"]
        runtime.execution_engine._seq = vssf_state["execution_sequence"]
        runtime.order_book.books = vssf_state["order_books"]
        runtime.order_book.orders = vssf_state["pending_orders"]
        runtime._submitted_at = vssf_state["submitted_at"]
        runtime._lifecycle_results = vssf_state["lifecycle_results"]
        runtime._market_time = vssf_state["market_time"]
        runtime.metrics = vssf_state["metrics"]
        bridge.groups = bridge_state["groups"]
        bridge.position_groups._groups = bridge_state["position_groups"]["groups"]
        bridge.position_groups._snapshots = bridge_state["position_groups"]["snapshots"]
        bridge._group_plans = bridge_state["group_plans"]
        bridge._track2_entry_progress_disabled_groups = bridge_state["track2_entry_progress_disabled_groups"]
        bridge.provenance = bridge_state["provenance"]
        bridge.execution_legs = bridge_state["execution_legs"]
        bridge.leg_positions = bridge_state["leg_positions"]
        bridge.pending_legs = pending["bridge"]
        bridge._applied_execution_fingerprints = bridge_state["applied_execution_fingerprints"]
        bridge._s9_retry_schedule = bridge_state["s9_retry_schedule"]
        bridge._s9_retry_attempts = bridge_state["s9_retry_attempts"]
        bridge._pending_attempt_ids = bridge_state["pending_attempt_ids"]
        bridge.position_lot_store = new_lot_store
        bridge.fee_ledger = new_fee_ledger
        bridge.option_position_attribution = Track9OptionPositionAttributionReadModel(new_lot_store)
        bridge.insurance_position = Track9InsurancePositionReadModel(new_lot_store)
        strategy.state = state["state"]
        strategy._exit_pending = state["exit_pending"]
        restored_callback_state = sections["callback_state"]
        if callback_state is not None:
            callback_state.clear(); callback_state.update(restored_callback_state)
        return {
            "restored": True, "execution_watermarks": sections["execution_watermarks"],
            "callback_state": restored_callback_state,
        }
