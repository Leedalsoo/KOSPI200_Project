from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

import pytest

from core.risk.position_pnl_exposure import ExposureLine, project_position_pnl_exposure


D = Decimal
STRATEGY = "track4_gamma_scalping"
GROUP = "S4-SYNTH-GROUP-01"


@dataclass(frozen=True)
class SyntheticFill:
    execution_id: str
    strategy_id: str
    group_id: str
    asset_type: str
    instrument_id: str
    side: str
    quantity: int
    price: Decimal
    reference_price: Decimal
    multiplier: Decimal
    fee: Decimal


@dataclass(frozen=True)
class S4Attribution:
    realized_option_pnl: Decimal
    realized_futures_pnl: Decimal
    unrealized_option_pnl: Decimal
    unrealized_futures_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    gross_pnl: Decimal
    net_after_execution_costs: Decimal
    theta_decay_cost_diagnostic: Decimal


def attribute_s4_synthetic_group(
    fills: Iterable[SyntheticFill],
    *,
    mark_prices: Mapping[str, Decimal],
    theta_decay_cost_diagnostic: Decimal,
) -> S4Attribution:
    """Test-only FIFO attribution; no Production/runtime wiring or policy claim."""
    selected = [
        fill for fill in fills
        if fill.strategy_id == STRATEGY and fill.group_id == GROUP
    ]
    if not selected:
        raise ValueError("S4_SYNTHETIC_GROUP_FILLS_REQUIRED")
    if any(fill.asset_type not in {"OPTION", "FUTURES"} for fill in selected):
        raise ValueError("S4_SYNTHETIC_ASSET_TYPE_UNSUPPORTED")
    if len({fill.execution_id for fill in selected}) != len(selected):
        raise ValueError("S4_SYNTHETIC_EXECUTION_ID_DUPLICATE")
    if (not theta_decay_cost_diagnostic.is_finite() or theta_decay_cost_diagnostic < 0
            or any(fill.side not in {"BUY", "SELL"} or fill.quantity <= 0 or fill.multiplier <= 0
                   or fill.price <= 0 or fill.reference_price <= 0 or fill.fee < 0
                   or not all(value.is_finite() for value in
                              (fill.price, fill.reference_price, fill.multiplier, fill.fee))
                   for fill in selected)):
        raise ValueError("S4_SYNTHETIC_FILL_INVALID")

    # FIFO inventory is scoped to this exact strategy/group/instrument.
    queues: dict[str, list[dict[str, object]]] = defaultdict(list)
    realized = {"OPTION": D("0"), "FUTURES": D("0")}
    fees = D("0")
    slippage = D("0")
    for fill in selected:
        fees += fill.fee
        adverse = (fill.price - fill.reference_price) if fill.side == "BUY" else (fill.reference_price - fill.price)
        slippage += adverse * fill.quantity * fill.multiplier
        queue = queues[fill.instrument_id]
        remaining = fill.quantity
        for lot in list(queue):
            if remaining == 0 or lot["side"] == fill.side:
                continue
            if lot["asset_type"] != fill.asset_type or lot["multiplier"] != fill.multiplier:
                raise ValueError("S4_SYNTHETIC_LOT_IDENTITY_OR_MULTIPLIER_MISMATCH")
            matched = min(remaining, int(lot["quantity"]))
            entry = lot["price"]
            direction = D("1") if lot["side"] == "BUY" else D("-1")
            realized[fill.asset_type] += (fill.price - entry) * matched * fill.multiplier * direction
            lot["quantity"] = int(lot["quantity"]) - matched
            remaining -= matched
            if lot["quantity"] == 0:
                queue.remove(lot)
        if remaining:
            queue.append({"side": fill.side, "quantity": remaining, "price": fill.price,
                          "multiplier": fill.multiplier, "asset_type": fill.asset_type})

    open_lines: list[ExposureLine] = []
    for instrument_id, lots in queues.items():
        if not lots:
            continue
        if instrument_id not in mark_prices:
            raise ValueError(f"S4_SYNTHETIC_MARK_PRICE_REQUIRED:{instrument_id}")
        for index, lot in enumerate(lots):
            open_lines.append(ExposureLine(
                instrument_id=f"{instrument_id}#FIFO{index}",
                asset_type=str(lot["asset_type"]),
                side=str(lot["side"]),
                quantity=int(lot["quantity"]),
                average_price=D(str(lot["price"])),
                current_price=D(str(mark_prices[instrument_id])),
                contract_multiplier=D(str(lot["multiplier"])),
            ))

    # Reuse the existing generic position projection, then independently split
    # option/futures components with the same signed MTM arithmetic.
    projected = project_position_pnl_exposure(open_lines, as_of=datetime.now(timezone.utc))
    unrealized_by_asset = {"OPTION": D("0"), "FUTURES": D("0")}
    for line in open_lines:
        direction = D("1") if line.side == "BUY" else D("-1")
        unrealized_by_asset[line.asset_type] += (
            (line.current_price - line.average_price) * line.quantity
            * line.contract_multiplier * direction
        )
    if projected.unrealized_pnl != sum(unrealized_by_asset.values(), D("0")):
        raise AssertionError("S4_SYNTHETIC_UNREALIZED_PROJECTION_DIVERGENCE")

    gross = sum(realized.values(), D("0")) + sum(unrealized_by_asset.values(), D("0"))
    return S4Attribution(
        realized_option_pnl=realized["OPTION"],
        realized_futures_pnl=realized["FUTURES"],
        unrealized_option_pnl=unrealized_by_asset["OPTION"],
        unrealized_futures_pnl=unrealized_by_asset["FUTURES"],
        fees=fees,
        slippage=slippage,
        gross_pnl=gross,
        net_after_execution_costs=gross - fees - slippage,
        # Option mark-to-market already contains all price effects, including theta.
        # Keep this diagnostic separate to avoid subtracting theta twice.
        theta_decay_cost_diagnostic=theta_decay_cost_diagnostic,
    )


def _fill(eid, asset, instrument, side, qty, price, reference, fee, *, strategy=STRATEGY, group=GROUP):
    return SyntheticFill(eid, strategy, group, asset, instrument, side, qty,
                         D(price), D(reference), D("50000"), D(fee))


def test_s4_option_and_linked_futures_pnl_attribution_with_costs_isolated_by_group():
    fills = (
        _fill("opt-call-open", "OPTION", "SYNTHETIC_CONTRACT:S4-CALL", "BUY", 1, "100", "99", "100"),
        _fill("opt-call-close", "OPTION", "SYNTHETIC_CONTRACT:S4-CALL", "SELL", 1, "115", "116", "100"),
        _fill("opt-put-open", "OPTION", "SYNTHETIC_CONTRACT:S4-PUT", "BUY", 1, "90", "89", "100"),
        _fill("fut-hedge-open", "FUTURES", "SYNTHETIC_CONTRACT:S4-MINI", "SELL", 2, "350", "351", "50"),
        _fill("fut-hedge-close", "FUTURES", "SYNTHETIC_CONTRACT:S4-MINI", "BUY", 1, "345", "344", "50"),
        _fill("other-strategy", "FUTURES", "SYNTHETIC_CONTRACT:OTHER", "BUY", 3, "999", "998", "999",
              strategy="track3_statistical_arbitrage", group="OTHER-GROUP"),
    )
    result = attribute_s4_synthetic_group(
        fills,
        mark_prices={
            "SYNTHETIC_CONTRACT:S4-PUT": D("80"),
            "SYNTHETIC_CONTRACT:S4-MINI": D("345"),
        },
        theta_decay_cost_diagnostic=D("80000"),
    )
    assert result.realized_option_pnl == D("750000")
    assert result.realized_futures_pnl == D("250000")
    assert result.unrealized_option_pnl == D("-500000")
    assert result.unrealized_futures_pnl == D("250000")
    assert result.gross_pnl == D("750000")
    assert result.fees == D("400")
    assert result.slippage == D("300000")
    assert result.net_after_execution_costs == D("449600")
    assert result.theta_decay_cost_diagnostic == D("80000")


def test_s4_attribution_requires_marks_for_remaining_owned_lots():
    fills = (_fill("put-open", "OPTION", "SYNTHETIC_CONTRACT:S4-PUT", "BUY", 1, "90", "90", "0"),)
    with pytest.raises(ValueError, match="S4_SYNTHETIC_MARK_PRICE_REQUIRED"):
        attribute_s4_synthetic_group(fills, mark_prices={}, theta_decay_cost_diagnostic=D("0"))


def test_s4_attribution_rejects_multiplier_mismatch_on_fifo_close():
    fills = (
        _fill("open", "OPTION", "SYNTHETIC_CONTRACT:S4-CALL", "BUY", 1, "100", "100", "0"),
        SyntheticFill("close", STRATEGY, GROUP, "OPTION", "SYNTHETIC_CONTRACT:S4-CALL",
                      "SELL", 1, D("101"), D("101"), D("250000"), D("0")),
    )
    with pytest.raises(ValueError, match="S4_SYNTHETIC_LOT_IDENTITY_OR_MULTIPLIER_MISMATCH"):
        attribute_s4_synthetic_group(fills, mark_prices={}, theta_decay_cost_diagnostic=D("0"))
