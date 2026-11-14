"""Validation-only S5 historical seed contract.

This module validates and projects supplied historical fill evidence. It never
submits orders, mutates operational configuration, or invents missing evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from contracts.types import DataQuality, ExecutionFill, ExecutionReport


class S5SeedInputBlocked(ValueError):
    """Raised when a validation seed lacks required, independently sourced evidence."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("S5_VALIDATION_SEED_BLOCKED:" + ",".join(reasons))


@dataclass(frozen=True)
class S5ValidatedSeed:
    manifest: dict[str, Any]
    event: dict[str, Any]
    manifest_sha256: str
    dataset_sha256: str

    def to_execution_report(self) -> ExecutionReport:
        """Project an already validated single-fill seed to the canonical read model."""
        event = self.event
        fill_data = event["execution_fills"][0]
        fill = ExecutionFill(
            execution_id=str(fill_data["execution_id"]),
            filled_quantity=int(fill_data["filled_quantity"]),
            execution_price=Decimal(str(fill_data["execution_price"])),
            execution_timestamp=datetime.fromisoformat(str(fill_data["execution_timestamp"])),
            fee=Decimal(str(fill_data["fee"])),
        )
        return ExecutionReport(
            client_order_id=str(event["client_order_id"]),
            broker_order_id=event.get("broker_order_id"),
            execution_id=fill.execution_id,
            status="FILLED",
            filled_quantity=fill.filled_quantity,
            remaining_quantity=int(event["remaining_quantity"]),
            execution_price=fill.execution_price,
            execution_timestamp=fill.execution_timestamp,
            fee=fill.fee,
            group_id=str(event["group_id"]),
            leg_id=str(event["leg_id"]),
            execution_fills=(fill,),
            source_freshness=DataQuality(
                is_fresh=False,
                is_complete=True,
                source_available=True,
                reason="validation_only_s5_historical_seed",
            ),
        )

    def to_position_lot(self, identity: Any):
        """Build immutable lot provenance only from a caller-supplied KIS identity."""
        from contracts.position_provenance import PositionLotProvenance, PositionRole

        event = self.event
        expected = {
            "instrument_id": str(event["instrument_id"]),
            "symbol": str(event["symbol"]),
            "expiry": str(event["expiry"]),
            "option_type": str(event["option_type"]).upper(),
            "strike": Decimal(str(event["strike"])),
            "contract_multiplier": Decimal(str(event["contract_multiplier"])),
            "identity_source": str(event["contract_identity_source"]),
        }
        if not str(expected["identity_source"]).startswith("KIS_OFFICIAL"):
            raise S5SeedInputBlocked(("KIS_CONTRACT_IDENTITY_REQUIRED",))
        for key, value in expected.items():
            if getattr(identity, key, None) != value:
                raise S5SeedInputBlocked((f"OPTION_IDENTITY_MISMATCH_{key.upper()}",))
        if event.get("expiry_source_type") != "KIS_OFFICIAL_CONTRACT_METADATA":
            raise S5SeedInputBlocked(("KIS_EXACT_EXPIRY_AUTHORITY_REQUIRED",))
        if event.get("multiplier_source_type") != "KIS_OFFICIAL_CONTRACT_METADATA":
            raise S5SeedInputBlocked(("KIS_MULTIPLIER_AUTHORITY_REQUIRED",))
        fill = event["execution_fills"][0]
        return PositionLotProvenance(
            run_id=str(event["run_id"]),
            instrument_id=str(event["instrument_id"]),
            strategy_id=str(event["strategy_id"]),
            group_id=str(event["group_id"]),
            leg_id=str(event["leg_id"]),
            client_order_id=str(event["client_order_id"]),
            execution_id=str(fill["execution_id"]),
            side=str(event["side"]).upper(),
            opened_quantity=int(fill["filled_quantity"]),
            remaining_quantity=int(event["remaining_quantity"]),
            execution_timestamp=datetime.fromisoformat(str(fill["execution_timestamp"])),
            instrument_identity=identity,
            contract_multiplier=expected["contract_multiplier"],
            identity_source=expected["identity_source"],
            position_role=PositionRole.NONE,
        )

    def to_track5_state(self):
        """Restore a complete, versioned legacy lifecycle snapshot without entry logic."""
        from core.strategy.track5_gap_divergence import Track5State

        snapshot = dict(self.event["track5_state_snapshot"])
        decimal_fields = (
            "entry_price", "target_price", "stop_loss_price", "peak_pnl",
            "expected_move_pts", "session_start_price", "gap_extreme_price",
            "selected_strike",
        )
        for key in decimal_fields:
            if snapshot.get(key) is not None:
                snapshot[key] = Decimal(str(snapshot[key]))
        if snapshot.get("session_start_at"):
            snapshot["session_start_at"] = datetime.fromisoformat(str(snapshot["session_start_at"]))
        state = Track5State(**snapshot)
        if (
            not state.is_active or state.entry_pending
            or state.direction not in {"LONG", "SHORT"}
            or state.entry_price <= 0 or state.target_price <= 0
            or state.stop_loss_price <= 0 or state.expected_move_pts <= 0
            or state.option_type not in {"CALL", "PUT"}
            or state.selected_strike is None or state.selected_strike <= 0
        ):
            raise S5SeedInputBlocked(("TRACK5_LIFECYCLE_STATE_INVALID",))
        if (
            state.option_type != str(self.event["option_type"]).upper()
            or state.selected_strike != Decimal(str(self.event["strike"]))
        ):
            raise S5SeedInputBlocked(("TRACK5_POSITION_IDENTITY_MISMATCH",))
        return state

    def restore_existing_position(self, *, strategy: Any, position_lot_store: Any, identity: Any) -> ExecutionReport:
        """Restore only a pre-existing lot and active state; no order/runtime call is made."""
        from core.strategy.track5_gap_divergence import Track5GapDivergence

        if not isinstance(strategy, Track5GapDivergence):
            raise S5SeedInputBlocked(("TRACK5_STRATEGY_REQUIRED",))
        if strategy.CURRENT_EXECUTION_POLICY_APPROVED is not False:
            raise S5SeedInputBlocked(("S5_ENTRY_POLICY_MUST_REMAIN_BLOCKED",))
        if strategy.runtime_config_verified is not False or strategy.risk_limits_available is not False:
            raise S5SeedInputBlocked(("S5_OPERATIONAL_GATES_MUST_REMAIN_FAIL_CLOSED",))
        report = self.to_execution_report()
        lot = self.to_position_lot(identity)
        state = self.to_track5_state()
        position_lot_store.apply_execution(lot)
        strategy.state = state
        return report


class S5ValidationOnlySeedAdapter:
    """Read-only, manifest-bound validator for one S5 pre-existing position fill."""

    MANIFEST_SCHEMA = "q25-a5-validation-only-position-seed-manifest-v1"
    EVENT_SCHEMA = "q25-a5-validation-only-position-seed-v2"
    REQUIRED_STATE_FIELDS = frozenset({
        "is_active", "entry_pending", "direction", "entry_price",
        "target_price", "stop_loss_price", "open_ticks", "peak_pnl",
        "trailing_active", "expected_move_pts", "session_start_price",
        "session_start_at", "gap_source", "gap_extreme_price",
        "option_type", "selected_strike", "futures_side",
        "futures_close_requested", "futures_closed", "futures_close_error",
        "option_close_requested",
    })

    def __init__(self, *, manifest_path: str | Path, dataset_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.dataset_path = Path(dataset_path).resolve()

    @staticmethod
    def _decimal(value: Any, field: str, reasons: list[str]) -> Decimal | None:
        try:
            result = Decimal(str(value))
            if not result.is_finite():
                raise InvalidOperation
            return result
        except (InvalidOperation, TypeError, ValueError):
            reasons.append(f"{field}_INVALID")
            return None

    def validate(self) -> S5ValidatedSeed:
        reasons: list[str] = []
        if not self.manifest_path.is_file():
            raise S5SeedInputBlocked(("MANIFEST_MISSING",))
        if not self.dataset_path.is_file():
            raise S5SeedInputBlocked(("DATASET_MISSING",))

        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            raw = self.dataset_path.read_bytes()
            lines = [line for line in raw.splitlines() if line.strip()]
            events = [json.loads(line) for line in lines]
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise S5SeedInputBlocked(("SEED_FILE_INVALID",)) from None

        manifest_hash = sha256(self.manifest_path.read_bytes()).hexdigest()
        dataset_hash = sha256(raw).hexdigest()
        if manifest.get("schema") != self.MANIFEST_SCHEMA:
            reasons.append("MANIFEST_SCHEMA_INVALID")
        if manifest.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO":
            reasons.append("PROVENANCE_INVALID")
        if manifest.get("validation_only") is not True:
            reasons.append("VALIDATION_ONLY_REQUIRED")
        for key in ("production_runtime_eligible", "execution_enabled", "orders_allowed",
                    "kis_api_allowed", "real_vts_api_allowed", "live_api_allowed",
                    "account_api_allowed"):
            if manifest.get(key) is not False:
                reasons.append(f"SAFETY_FLAG_INVALID_{key.upper()}")
        if manifest.get("events_sha256") != dataset_hash:
            reasons.append("DATASET_HASH_MISMATCH")
        if Path(str(manifest.get("events_file", ""))).name != self.dataset_path.name:
            reasons.append("DATASET_FILE_BINDING_MISMATCH")
        if manifest.get("event_count") != len(events) or len(events) != 1:
            reasons.append("SINGLE_EVENT_COUNT_REQUIRED")
        if len(events) != 1:
            raise S5SeedInputBlocked(tuple(sorted(set(reasons + ["SINGLE_EVENT_REQUIRED"]))))

        event = events[0]
        if event.get("schema") != self.EVENT_SCHEMA:
            reasons.append("EVENT_SCHEMA_INVALID")
        if event.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO":
            reasons.append("EVENT_PROVENANCE_INVALID")
        if event.get("validation_only") is not True or event.get("production_runtime_eligible") is not False:
            reasons.append("EVENT_SAFETY_FLAGS_INVALID")
        if event.get("run_id") != manifest.get("run_id"):
            reasons.append("RUN_ID_MISMATCH")
        for key in ("strategy_id", "group_id", "instrument_id"):
            if event.get(key) != manifest.get(key):
                reasons.append(f"{key.upper()}_MISMATCH")

        required_text = (
            "strategy_id", "run_id", "group_id", "leg_id", "client_order_id",
            "execution_id", "instrument_id", "symbol", "contract_identity_source",
            "expiry_source", "market_snapshot_id", "market_snapshot_sha256",
            "analytics_snapshot_id", "analytics_snapshot_sha256",
        )
        for key in required_text:
            if not isinstance(event.get(key), str) or not event[key].strip():
                reasons.append(f"{key.upper()}_REQUIRED")

        expiry = str(event.get("expiry", ""))
        if not re.fullmatch(r"20\d{6}", expiry):
            reasons.append("EXACT_EXPIRY_REQUIRED")
        if event.get("expiry_source_type") != "KIS_OFFICIAL_CONTRACT_METADATA":
            reasons.append("KIS_EXACT_EXPIRY_AUTHORITY_REQUIRED")
        if not str(event.get("contract_identity_source", "")).startswith("KIS_OFFICIAL"):
            reasons.append("KIS_CONTRACT_IDENTITY_REQUIRED")
        if event.get("multiplier_source_type") != "KIS_OFFICIAL_CONTRACT_METADATA":
            reasons.append("KIS_MULTIPLIER_AUTHORITY_REQUIRED")

        price = self._decimal(event.get("execution_price"), "EXECUTION_PRICE", reasons)
        fee = self._decimal(event.get("fee"), "FEE", reasons)
        if price is None or price <= 0:
            reasons.append("EXECUTION_PRICE_REQUIRED_OR_INVALID")
        if fee is None or fee < 0:
            reasons.append("FEE_REQUIRED_OR_INVALID")
        if not event.get("execution_timestamp"):
            reasons.append("EXECUTION_TIMESTAMP_REQUIRED")
        else:
            try:
                datetime.fromisoformat(str(event["execution_timestamp"]))
            except ValueError:
                reasons.append("EXECUTION_TIMESTAMP_INVALID")

        fills = event.get("execution_fills")
        if not isinstance(fills, list) or len(fills) != 1:
            reasons.append("SINGLE_CANONICAL_FILL_REQUIRED")
        else:
            fill = fills[0]
            for key in ("execution_id", "execution_timestamp", "execution_price", "fee"):
                if fill.get(key) in (None, ""):
                    reasons.append(f"FILL_{key.upper()}_REQUIRED")
            if fill.get("execution_id") != event.get("execution_id"):
                reasons.append("FILL_EXECUTION_ID_MISMATCH")
            try:
                if int(fill.get("filled_quantity", 0)) != int(event.get("opened_quantity", 0)):
                    reasons.append("FILL_OPENED_QUANTITY_MISMATCH")
            except (TypeError, ValueError):
                reasons.append("FILL_QUANTITY_INVALID")

        try:
            opened = int(event.get("opened_quantity", 0))
            remaining = int(event.get("remaining_quantity", 0))
            if opened <= 0 or remaining != opened:
                reasons.append("OPEN_REMAINING_QUANTITY_MISMATCH")
        except (TypeError, ValueError):
            reasons.append("POSITION_QUANTITY_INVALID")

        state = event.get("track5_state_snapshot")
        if not isinstance(state, dict) or not self.REQUIRED_STATE_FIELDS.issubset(state):
            reasons.append("TRACK5_STATE_SNAPSHOT_INCOMPLETE")
        elif state.get("is_active") is not True or state.get("entry_pending") is not False:
            reasons.append("TRACK5_ACTIVE_EXIT_ONLY_STATE_REQUIRED")
        elif state.get("option_type") != event.get("option_type"):
            reasons.append("TRACK5_OPTION_TYPE_MISMATCH")
        else:
            try:
                if Decimal(str(state.get("selected_strike"))) != Decimal(str(event.get("strike"))):
                    reasons.append("TRACK5_STRIKE_MISMATCH")
            except (InvalidOperation, TypeError, ValueError):
                reasons.append("TRACK5_STRIKE_INVALID")

        for key in ("market_snapshot_provenance", "analytics_snapshot_provenance"):
            if event.get(key) != "SYNTHETIC:DERIVED_SCENARIO":
                reasons.append(f"{key.upper()}_INVALID")
        for key in ("market_snapshot_as_of", "analytics_snapshot_as_of"):
            if not event.get(key):
                reasons.append(f"{key.upper()}_REQUIRED")
        for path_key, hash_key in (
            ("market_snapshot_path", "market_snapshot_sha256"),
            ("analytics_snapshot_path", "analytics_snapshot_sha256"),
        ):
            relative = event.get(path_key)
            if not isinstance(relative, str) or not relative.strip():
                reasons.append(f"{path_key.upper()}_REQUIRED")
                continue
            snapshot_path = (self.dataset_path.parent / relative).resolve()
            if self.dataset_path.parent not in snapshot_path.parents or not snapshot_path.is_file():
                reasons.append(f"{path_key.upper()}_UNAVAILABLE_OR_OUTSIDE_DATASET")
            elif sha256(snapshot_path.read_bytes()).hexdigest() != event.get(hash_key):
                reasons.append(f"{path_key.upper()}_HASH_MISMATCH")

        if reasons:
            raise S5SeedInputBlocked(tuple(sorted(set(reasons))))
        return S5ValidatedSeed(
            manifest=manifest,
            event=event,
            manifest_sha256=manifest_hash,
            dataset_sha256=dataset_hash,
        )
