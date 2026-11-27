"""Validation-only projection of owned PositionLots into group and account risk views.

This module does not define operating limits or feed Production RiskGate inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class PositionLotRiskExposure:
    net_signed_qty: int
    gross_long_qty: int
    gross_short_qty: int
    contract_multiplier: Decimal
    identity_source: str


@dataclass(frozen=True)
class PositionLotRiskProjection:
    group_positions: dict[tuple[str, str, str, str], PositionLotRiskExposure]
    account_positions: dict[str, PositionLotRiskExposure]


def project_position_lot_risk_exposure(
    open_lots: Iterable[object],
) -> PositionLotRiskProjection:
    """Keep exact lot ownership while separately aggregating account-wide gross/net.

    Group keys are (run_id, strategy_id, group_id, instrument_id). Account keys
    are instrument_id only. Gross long/short quantities are retained so offsetting
    strategies cannot make a non-flat account appear risk-free.
    """
    group_totals: dict[tuple[str, str, str, str], list[object]] = {}
    account_totals: dict[str, list[object]] = {}
    instrument_provenance: dict[str, tuple[Decimal, str]] = {}
    seen_execution_ids: set[str] = set()

    for lot in open_lots:
        run_id = getattr(lot, "run_id", None)
        strategy_id = getattr(lot, "strategy_id", None)
        group_id = getattr(lot, "group_id", None)
        instrument_id = getattr(lot, "instrument_id", None)
        execution_id = getattr(lot, "execution_id", None)
        identity_source = getattr(lot, "identity_source", None)
        multiplier = getattr(lot, "contract_multiplier", None)
        side = getattr(lot, "side", None)
        quantity = getattr(lot, "remaining_quantity", None)

        required = (run_id, strategy_id, group_id, instrument_id, execution_id, identity_source)
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ValueError("POSITION_LOT_RISK_PROJECTION_IDENTITY_REQUIRED")
        if execution_id in seen_execution_ids:
            raise ValueError("POSITION_LOT_RISK_PROJECTION_DUPLICATE_EXECUTION_ID")
        seen_execution_ids.add(execution_id)
        if side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_LOT_RISK_PROJECTION_SIDE_INVALID")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("POSITION_LOT_RISK_PROJECTION_QUANTITY_INVALID")
        if not isinstance(multiplier, Decimal) or not multiplier.is_finite() or multiplier <= 0:
            raise ValueError("POSITION_LOT_RISK_PROJECTION_MULTIPLIER_INVALID")

        provenance = (multiplier, identity_source)
        prior_provenance = instrument_provenance.get(instrument_id)
        if prior_provenance is not None and prior_provenance != provenance:
            raise ValueError("POSITION_LOT_RISK_PROJECTION_CONTRACT_PROVENANCE_MISMATCH")
        instrument_provenance[instrument_id] = provenance

        group_key = (run_id, strategy_id, group_id, instrument_id)
        for totals in (group_totals, account_totals):
            key = group_key if totals is group_totals else instrument_id
            if key not in totals:
                totals[key] = [0, 0, 0, multiplier, identity_source]
            bucket = totals[key]
            if side == "BUY":
                bucket[0] = int(bucket[0]) + quantity
                bucket[1] = int(bucket[1]) + quantity
            else:
                bucket[0] = int(bucket[0]) - quantity
                bucket[2] = int(bucket[2]) + quantity

    def freeze(values: dict) -> dict:
        return {
            key: PositionLotRiskExposure(
                net_signed_qty=int(bucket[0]),
                gross_long_qty=int(bucket[1]),
                gross_short_qty=int(bucket[2]),
                contract_multiplier=bucket[3],
                identity_source=str(bucket[4]),
            )
            for key, bucket in values.items()
        }

    return PositionLotRiskProjection(
        group_positions=freeze(group_totals),
        account_positions=freeze(account_totals),
    )
