"""Validation-only S4 group/account risk reconciliation across Virtual projections."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from application.composition.validation_only_position_lot_risk_projection import (
    PositionLotRiskProjection,
    project_position_lot_risk_exposure,
)


@dataclass(frozen=True)
class ValidationOnlyS4GroupAccountRiskResult:
    status: str
    issues: tuple[str, ...]
    group_projection: PositionLotRiskProjection
    fixture_group_cap_breaches: tuple[tuple[str, str, str, str, int, int], ...]
    production_risk_gate_connected: bool = False
    read_only: bool = True


def _signed_position(
    value: Any, *, code: str, allow_flat: bool = False, require_identity_source: bool = False,
) -> tuple[int, Decimal | None, str | None]:
    if isinstance(value, Mapping):
        side = value.get("side")
        quantity = value.get("qty", value.get("quantity"))
        multiplier = value.get("contract_multiplier")
        identity_source = value.get("identity_source")
    else:
        side = getattr(value, "side", None)
        quantity = getattr(value, "qty", getattr(value, "quantity", None))
        multiplier = getattr(value, "contract_multiplier", None)
        identity_source = getattr(value, "identity_source", None)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise ValueError(f"{code}_QUANTITY_INVALID")
    if quantity == 0:
        if not allow_flat or side not in {None, ""}:
            raise ValueError(f"{code}_FLAT_STATE_INVALID")
        return 0, None, None
    if side not in {"BUY", "SELL"}:
        raise ValueError(f"{code}_SIDE_INVALID")
    if multiplier is None:
        raise ValueError(f"{code}_MULTIPLIER_REQUIRED")
    try:
        multiplier_value = Decimal(str(multiplier))
    except Exception as exc:
        raise ValueError(f"{code}_MULTIPLIER_INVALID") from exc
    if not multiplier_value.is_finite() or multiplier_value <= 0:
        raise ValueError(f"{code}_MULTIPLIER_INVALID")
    if require_identity_source and (not isinstance(identity_source, str) or not identity_source.strip()):
        raise ValueError(f"{code}_IDENTITY_SOURCE_REQUIRED")
    return (quantity if side == "BUY" else -quantity), multiplier_value, identity_source


def reconcile_s4_group_account_risk(
    *,
    bridge: Any,
    vssf_runtime: Any,
    run_id: str,
    candidate_id: str,
    fixture_group_caps: Mapping[tuple[str, str, str, str], int] | None = None,
) -> ValidationOnlyS4GroupAccountRiskResult:
    """Compare PositionLot-derived exposure with VSSF account and Bridge aggregates.

    This is a read-only validation adapter for one isolated synthetic candidate.
    It neither supplies RiskGate inputs nor establishes operating limits.
    """
    issues: list[str] = []
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("S4_F14_RUN_ID_REQUIRED")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("S4_F14_CANDIDATE_ID_REQUIRED")
    if getattr(bridge, "run_id", None) != run_id:
        issues.append("S4_F14_BRIDGE_RUN_SCOPE_MISMATCH")

    account = getattr(vssf_runtime, "account", None)
    if account is None:
        issues.append("S4_F14_VSSF_ACCOUNT_MISSING")
        account_positions: Mapping[str, Any] = {}
    else:
        if getattr(account, "validation_run_id", None) != run_id:
            issues.append("S4_F14_ACCOUNT_RUN_SCOPE_UNVERIFIED")
        if getattr(account, "validation_candidate_id", None) != candidate_id:
            issues.append("S4_F14_CANDIDATE_SCOPE_UNVERIFIED")
        raw_account_positions = getattr(account, "positions", None)
        if not isinstance(raw_account_positions, Mapping):
            issues.append("S4_F14_VSSF_POSITION_SNAPSHOT_MISSING")
            account_positions = {}
        else:
            account_positions = raw_account_positions

    lot_store = getattr(bridge, "position_lot_store", None)
    open_lots_method = getattr(lot_store, "open_lots", None)
    if not callable(open_lots_method):
        issues.append("S4_F14_POSITION_LOT_STORE_MISSING")
        lots: tuple[Any, ...] = ()
    else:
        lots = tuple(open_lots_method())

    bridge_positions = getattr(bridge, "leg_positions", None)
    if not isinstance(bridge_positions, Mapping):
        issues.append("S4_F14_BRIDGE_POSITION_SNAPSHOT_MISSING")
        bridge_positions = {}

    try:
        projection = project_position_lot_risk_exposure(lots)
    except (TypeError, ValueError) as exc:
        projection = PositionLotRiskProjection(group_positions={}, account_positions={})
        issues.append(f"S4_F14_POSITION_LOT_PROJECTION_INVALID:{exc}")

    for lot in lots:
        if getattr(lot, "run_id", None) != run_id:
            issues.append(f"S4_F14_POSITION_LOT_RUN_SCOPE_MISMATCH:{getattr(lot, 'execution_id', '')}")

    for label, positions in (("VSSF", account_positions), ("BRIDGE", bridge_positions)):
        if any(not isinstance(key, str) or not key.strip() for key in positions):
            issues.append(f"S4_F14_{label}_INSTRUMENT_KEY_INVALID")
    instruments = (
        set(projection.account_positions)
        | {key for key in account_positions if isinstance(key, str) and key.strip()}
        | {key for key in bridge_positions if isinstance(key, str) and key.strip()}
    )
    for instrument_id in sorted(instruments):
        expected = projection.account_positions.get(instrument_id)
        expected_net = expected.net_signed_qty if expected is not None else 0
        try:
            actual_vssf, vssf_multiplier, _ = _signed_position(
                account_positions[instrument_id], code="S4_F14_VSSF_POSITION", allow_flat=False,
            ) if instrument_id in account_positions else (0, None, None)
        except ValueError as exc:
            issues.append(f"{exc}:{instrument_id}")
            actual_vssf = 0
            vssf_multiplier = None
        try:
            actual_bridge, bridge_multiplier, bridge_source = _signed_position(
                bridge_positions[instrument_id], code="S4_F14_BRIDGE_POSITION", allow_flat=True,
                require_identity_source=True,
            ) if instrument_id in bridge_positions else (0, None, None)
        except ValueError as exc:
            issues.append(f"{exc}:{instrument_id}")
            actual_bridge = 0
            bridge_multiplier = None
            bridge_source = None
        if actual_vssf != expected_net:
            issues.append(f"S4_F14_VSSF_POSITION_MISMATCH:{instrument_id}")
        if actual_bridge != expected_net:
            issues.append(f"S4_F14_BRIDGE_POSITION_MISMATCH:{instrument_id}")
        if vssf_multiplier is not None and expected is not None and vssf_multiplier != expected.contract_multiplier:
            issues.append(f"S4_F14_VSSF_MULTIPLIER_MISMATCH:{instrument_id}")
        if bridge_multiplier is not None and expected is not None and bridge_multiplier != expected.contract_multiplier:
            issues.append(f"S4_F14_BRIDGE_MULTIPLIER_MISMATCH:{instrument_id}")
        if bridge_source is not None and expected is not None and bridge_source != expected.identity_source:
            issues.append(f"S4_F14_BRIDGE_IDENTITY_SOURCE_MISMATCH:{instrument_id}")

    cap_breaches: list[tuple[str, str, str, str, int, int]] = []
    for key, cap in (fixture_group_caps or {}).items():
        if (not isinstance(key, tuple) or len(key) != 4 or any(not isinstance(x, str) or not x.strip() for x in key)
            or isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0):
            raise ValueError("S4_F14_FIXTURE_GROUP_CAP_INVALID")
        exposure = projection.group_positions.get(key)
        if exposure is not None and abs(exposure.net_signed_qty) > cap:
            cap_breaches.append((*key, abs(exposure.net_signed_qty), cap))

    unique_issues = tuple(dict.fromkeys(issues))
    if any(issue in unique_issues for issue in ("S4_F14_ACCOUNT_RUN_SCOPE_UNVERIFIED", "S4_F14_CANDIDATE_SCOPE_UNVERIFIED")):
        status = "INSUFFICIENT_SCOPE_EVIDENCE"
    else:
        status = (
            "RECONCILIATION_REQUIRED" if unique_issues
            else "FIXTURE_GROUP_CAP_EXCEEDED" if cap_breaches
            else "VALIDATION_ONLY_S4_GROUP_ACCOUNT_RECONCILED"
        )
    return ValidationOnlyS4GroupAccountRiskResult(
        status=status, issues=unique_issues, group_projection=projection,
        fixture_group_cap_breaches=tuple(cap_breaches),
    )
