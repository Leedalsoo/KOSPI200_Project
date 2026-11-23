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


def _owned_position_lot(
    *,
    execution_id: str,
    run_id: str,
    strategy_id: str,
    group_id: str,
    instrument_id: str,
    asset_type: str,
    side: str,
    quantity: int = 1,
):
    from datetime import datetime, timezone
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.position_provenance import PositionLotProvenance, PositionRole
    from contracts.types import OptionInstrumentIdentity

    source = "SYNTHETIC:DERIVED_SCENARIO"
    multiplier = D("10") if asset_type == "OPTION" else D("50000")
    if asset_type == "OPTION":
        identity = OptionInstrumentIdentity(
            instrument_id=instrument_id,
            symbol=instrument_id,
            expiry="20261210",
            option_type="CALL",
            strike=D("500"),
            contract_multiplier=multiplier,
            identity_source=source,
        )
    else:
        identity = FuturesInstrumentIdentity(
            instrument_id=instrument_id,
            symbol=instrument_id,
            product_type=FuturesProductType.MINI,
            contract_multiplier=multiplier,
            identity_source=source,
        )
    return PositionLotProvenance(
        run_id=run_id,
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        group_id=group_id,
        leg_id=f"{asset_type}-LEG",
        client_order_id=f"CO-{execution_id}",
        execution_id=execution_id,
        side=side,
        opened_quantity=quantity,
        remaining_quantity=quantity,
        execution_timestamp=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
        instrument_identity=identity,
        contract_multiplier=multiplier,
        identity_source=source,
        position_role=PositionRole.NONE,
    )


def test_position_lot_close_is_scoped_to_run_strategy_and_group_owner():
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

    store = VirtualPositionLotStore()
    store.apply_execution(_owned_position_lot(
        execution_id="S4-OWNER-A-OPEN",
        run_id="S4-RUN-A",
        strategy_id=STRATEGY,
        group_id="S4-GROUP-COLLISION",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="BUY",
    ))

    # Same instrument/group but a different run must not close the S4-owned lot.
    store.apply_execution(_owned_position_lot(
        execution_id="OTHER-RUN-CLOSE",
        run_id="OTHER-RUN",
        strategy_id=STRATEGY,
        group_id="S4-GROUP-COLLISION",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="SELL",
    ))
    assert {lot.execution_id: lot.remaining_quantity for lot in store.open_lots()} == {
        "S4-OWNER-A-OPEN": 1,
        "OTHER-RUN-CLOSE": 1,
    }
    assert store.close_events() == ()

    # Same run/group but a different strategy must also remain isolated.
    store.apply_execution(_owned_position_lot(
        execution_id="OTHER-STRATEGY-CLOSE",
        run_id="S4-RUN-A",
        strategy_id="track3_statistical_arbitrage",
        group_id="S4-GROUP-COLLISION",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="SELL",
    ))
    assert {lot.execution_id: lot.remaining_quantity for lot in store.open_lots()} == {
        "S4-OWNER-A-OPEN": 1,
        "OTHER-RUN-CLOSE": 1,
        "OTHER-STRATEGY-CLOSE": 1,
    }
    assert store.close_events() == ()


def test_s4_synthetic_option_and_mini_hedge_share_group_without_cross_asset_netting():
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

    store = VirtualPositionLotStore()
    option = _owned_position_lot(
        execution_id="S4-OPTION-OPEN",
        run_id="S4-RUN",
        strategy_id=STRATEGY,
        group_id="S4-LINKED-GROUP",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="BUY",
        quantity=2,
    )
    futures = _owned_position_lot(
        execution_id="S4-MINI-HEDGE-OPEN",
        run_id="S4-RUN",
        strategy_id=STRATEGY,
        group_id="S4-LINKED-GROUP",
        instrument_id="SYNTHETIC_CONTRACT:S4-MINI",
        asset_type="FUTURES",
        side="SELL",
        quantity=1,
    )
    store.apply_execution(option)
    store.apply_execution(futures)

    assert {(lot.instrument_id, lot.group_id, lot.strategy_id, lot.remaining_quantity)
            for lot in store.open_lots()} == {
        (option.instrument_id, "S4-LINKED-GROUP", STRATEGY, 2),
        (futures.instrument_id, "S4-LINKED-GROUP", STRATEGY, 1),
    }

    store.apply_execution(_owned_position_lot(
        execution_id="S4-OPTION-PARTIAL-CLOSE",
        run_id="S4-RUN",
        strategy_id=STRATEGY,
        group_id="S4-LINKED-GROUP",
        instrument_id=option.instrument_id,
        asset_type="OPTION",
        side="SELL",
        quantity=1,
    ))
    remaining = {lot.instrument_id: lot.remaining_quantity for lot in store.open_lots()}
    assert remaining == {option.instrument_id: 1, futures.instrument_id: 1}
    assert [(event.source_lot_execution_id, event.quantity)
            for event in store.close_events()] == [("S4-OPTION-OPEN", 1)]

def test_position_lot_execution_id_reuse_across_runs_is_a_provenance_conflict():
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

    store = VirtualPositionLotStore()
    original = _owned_position_lot(
        execution_id="REUSED-EXECUTION-ID",
        run_id="S4-RUN-A",
        strategy_id=STRATEGY,
        group_id="S4-GROUP-A",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="BUY",
    )
    conflicting = _owned_position_lot(
        execution_id="REUSED-EXECUTION-ID",
        run_id="S4-RUN-B",
        strategy_id=STRATEGY,
        group_id="S4-GROUP-A",
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        asset_type="OPTION",
        side="BUY",
    )
    store.apply_execution(original)
    with pytest.raises(ValueError, match="POSITION_PROVENANCE_DUPLICATE_CONFLICT"):
        store.apply_execution(conflicting)
    assert [(lot.run_id, lot.execution_id, lot.remaining_quantity) for lot in store.open_lots()] == [
        ("S4-RUN-A", "REUSED-EXECUTION-ID", 1),
    ]

def test_s4_synthetic_execution_fill_materializes_owned_option_and_linked_mini_lots():
    """Exercise the real Virtual multi-leg fill-to-lot materializer with synthetic inputs only."""
    from datetime import datetime, timezone

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import (
        BrokerOrderCommand, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan,
        OptionInstrumentIdentity,
    )
    from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

    source = "SYNTHETIC:DERIVED_SCENARIO"
    run_id = "S4-SYNTHETIC-RUN-1782"
    strategy_id = STRATEGY
    group_id = "S4-SYNTHETIC-LINKED-GROUP-1782"
    timestamp = datetime(2026, 11, 23, 9, 30, tzinfo=timezone.utc)
    option_identity = OptionInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S4-OPTION-CALL-1782",
        symbol="SYNTHETIC-S4-CALL", expiry="20261210", option_type="CALL",
        strike=D("500"), contract_multiplier=D("10"), identity_source=source,
    )
    mini_identity = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S4-MINI-1782", symbol="SYNTHETIC-S4-MINI",
        product_type=FuturesProductType.MINI, contract_multiplier=D("50000"),
        identity_source=source,
    )

    # Isolate the existing production materialization method; no broker, router,
    # Runtime strategy, KIS API, or live order path is invoked by this fixture.
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = run_id
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    bridge.leg_positions = {}
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge._applied_execution_fingerprints = {}

    def apply_fill(*, leg_id, side, identity, execution_id, quantity, price):
        leg = ExecutionLeg(leg_id=leg_id, side=side, quantity=quantity)
        plan = MultiLegExecutionPlan(group_id=group_id, strategy_id=strategy_id, legs=(leg,))
        client_order_id = f"SYNTHETIC-CO-{execution_id}"
        command = BrokerOrderCommand(
            client_order_id=client_order_id, instrument_id=identity.instrument_id,
            side=side, quantity=quantity, order_type="LIMIT", instrument_identity=identity,
            asset_type="OPTION" if isinstance(identity, OptionInstrumentIdentity) else "FUTURES",
            strategy_id=strategy_id, group_id=group_id, leg_id=leg_id,
        )
        report = ExecutionReport(
            client_order_id=client_order_id, broker_order_id=f"SYNTHETIC-BO-{execution_id}",
            execution_id=execution_id, status="FILLED", filled_quantity=quantity,
            remaining_quantity=0, execution_price=D(price), execution_timestamp=timestamp,
            fee=D("1"), group_id=group_id, leg_id=leg_id,
        )
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity, broker_command=command, report=report,
        )
        return plan, leg, command, report

    option_plan, option_leg, option_command, option_report = apply_fill(
        leg_id="S4-OPTION-LEG", side="BUY", identity=option_identity,
        execution_id="SYNTHETIC-OPTION-OPEN-1782", quantity=2, price="100",
    )
    apply_fill(
        leg_id="S4-MINI-HEDGE-LEG", side="SELL", identity=mini_identity,
        execution_id="SYNTHETIC-MINI-HEDGE-OPEN-1782", quantity=1, price="350",
    )

    # Replaying the same fill is idempotent; a distinct partial close affects
    # only the option instrument while preserving the linked MINI hedge lot.
    bridge._apply_reconciled_execution(
        plan=option_plan, leg=option_leg, identity=option_identity,
        broker_command=option_command, report=option_report,
    )
    apply_fill(
        leg_id="S4-OPTION-CLOSE-LEG", side="SELL", identity=option_identity,
        execution_id="SYNTHETIC-OPTION-PARTIAL-CLOSE-1782", quantity=1, price="105",
    )

    lots = {lot.instrument_id: lot for lot in bridge.position_lot_store.open_lots()}
    assert set(lots) == {option_identity.instrument_id, mini_identity.instrument_id}
    assert (lots[option_identity.instrument_id].remaining_quantity,
            lots[option_identity.instrument_id].run_id,
            lots[option_identity.instrument_id].strategy_id,
            lots[option_identity.instrument_id].group_id,
            lots[option_identity.instrument_id].identity_source) == (1, run_id, strategy_id, group_id, source)
    assert (lots[mini_identity.instrument_id].remaining_quantity,
            lots[mini_identity.instrument_id].side,
            lots[mini_identity.instrument_id].contract_multiplier) == (1, "SELL", D("50000"))
    assert bridge.leg_positions[option_identity.instrument_id].qty == 1
    assert bridge.leg_positions[mini_identity.instrument_id].qty == 1
    assert len(bridge.fee_ledger.query(run_id=run_id)) == 3
    assert [(event.source_lot_execution_id, event.quantity)
            for event in bridge.position_lot_store.close_events()] == [
                ("SYNTHETIC-OPTION-OPEN-1782", 1),
            ]
    assert bridge.provenance["SYNTHETIC-OPTION-OPEN-1782"]["group_id"] == group_id
    assert bridge.provenance["SYNTHETIC-MINI-HEDGE-OPEN-1782"]["instrument_id"] == mini_identity.instrument_id
