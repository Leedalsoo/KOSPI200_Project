from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput


def _market_input() -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=datetime(2026, 11, 25, 10, 0),
        current_price=Decimal("880"),
        active_vol=Decimal("20"),
        base_vol=Decimal("15"),
        time_str="10:00:00",
        current_delta=Decimal("1000000"),
        current_gamma=Decimal("1"),
        current_pnl=Decimal("0"),
        current_equity=Decimal("1000000"),
        price_history=(Decimal("879"), Decimal("880")),
    )


def test_track4_strategy_state_records_hedge_target_before_any_fill() -> None:
    """Characterize target-vs-actual state; this is not a Production approval."""
    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=Decimal("1"),
        risk_limits_available=True,
    )

    signals = strategy.evaluate_delta_hedge(
        _market_input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=2,
    )

    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal is not None
    assert proposal.tag_id == "GAMMA_REBALANCE"
    assert proposal.side == "SELL"
    assert proposal.proposed_quantity == 2

    # The strategy records the target as active before an execution result exists.
    assert strategy.state.active_hedge_qty == -2

    # A synthetic partial/pending result is not consumed by the entry callback.
    strategy.on_execution_result(
        "GAMMA_REBALANCE",
        SimpleNamespace(
            group_complete=False,
            position_flat=False,
            filled_quantity=1,
            remaining_quantity=1,
            pending_legs=1,
        ),
    )
    assert strategy.state.active_hedge_qty == -2

    # A synthetic rejected/no-fill result also leaves the target recorded as active.
    strategy.on_execution_result(
        "GAMMA_REBALANCE",
        SimpleNamespace(
            group_complete=False,
            position_flat=True,
            filled_quantity=0,
            remaining_quantity=2,
            pending_legs=0,
        ),
    )
    assert strategy.state.active_hedge_qty == -2

def test_s4_group_callback_exposes_fill_events_but_not_order_side_or_instrument() -> None:
    """Characterize the group callback payload without inventing S4 fill ownership policy."""
    from application.composition.virtual_multi_leg_execution import (
        MultiLegExecutionResult,
        VirtualMultiLegExecutionBridge,
    )
    from contracts.types import ExecutionFill, ExecutionReport

    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=Decimal("1"),
        risk_limits_available=True,
    )
    strategy.evaluate_delta_hedge(
        _market_input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=2,
    )
    assert strategy.state.active_hedge_qty == -2

    observed_at = datetime(2026, 11, 25, 10, 1)
    fills = (
        ExecutionFill("SYNTH-FILL-001", 1, Decimal("1000"), observed_at, Decimal("0.1")),
        ExecutionFill("SYNTH-FILL-002", 1, Decimal("1001"), observed_at, Decimal("0.1")),
    )
    report = ExecutionReport(
        client_order_id="SYNTH-S4-ORDER-001",
        broker_order_id="SYNTH-BROKER-001",
        execution_id=None,
        status="PARTIALLY_FILLED",
        filled_quantity=2,
        remaining_quantity=1,
        execution_price=Decimal("1000.5"),
        execution_timestamp=observed_at,
        fee=Decimal("0.2"),
        group_id="SYNTH-S4-GROUP-001",
        leg_id="SYNTH-S4-HEDGE-LEG",
        execution_fills=fills,
    )
    result = MultiLegExecutionResult(
        group_id="SYNTH-S4-GROUP-001",
        strategy_id=strategy.strategy_id,
        planned_legs=1,
        approved_legs=1,
        routed_legs=1,
        # Current implementation accumulates contract quantity in this field.
        filled_legs=2,
        reports=(report,),
        group_complete=False,
        pending_legs=1,
        position_flat=False,
    )

    # The bridge expands one report into the individual fill rows for ledger work.
    expanded = VirtualMultiLegExecutionBridge._execution_fill_reports(report)
    assert [item.execution_id for item in expanded] == [
        "SYNTH-FILL-001",
        "SYNTH-FILL-002",
    ]
    assert [item.filled_quantity for item in expanded] == [1, 1]

    # The strategy callback receives one group result containing one order report.
    assert len(result.reports) == 1
    assert result.reports[0].filled_quantity == 2
    assert len(result.reports[0].execution_fills) == 2
    assert result.filled_legs == 2
    assert result.pending_legs == 1
    assert not hasattr(result.reports[0], "side")
    assert not hasattr(result.reports[0], "instrument_id")
    assert not hasattr(result, "plan")

    # GAMMA_REBALANCE is currently ignored by Track4; this is characterization only.
    strategy.on_execution_result("GAMMA_REBALANCE", result)
    assert strategy.state.active_hedge_qty == -2

def test_s4_hedge_target_is_distinct_from_owned_lot_and_virtual_position_quantity() -> None:
    """Trace synthetic hedge fills through the existing lot and position materializer."""
    from datetime import timezone

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import BrokerOrderCommand, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan
    from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

    source = "SYNTHETIC:DERIVED_SCENARIO"
    run_id = "S4-SYNTHETIC-POSITION-LINEAGE-1825"
    group_id = "S4-SYNTHETIC-HEDGE-GROUP-1825"
    instrument = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S4-MINI-HEDGE-1825",
        symbol="SYNTHETIC-S4-MINI-1825",
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source=source,
    )
    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=Decimal("1"),
        risk_limits_available=True,
    )
    signals = strategy.evaluate_delta_hedge(
        _market_input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=2,
    )
    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal is not None and proposal.proposed_quantity == 2
    assert strategy.state.active_hedge_qty == -2  # target, before any fill

    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = run_id
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    bridge.leg_positions = {}
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge._applied_execution_fingerprints = {}

    def apply_fill(*, execution_id: str, side: str, quantity: int, minute: int) -> None:
        timestamp = datetime(2026, 11, 25, 10, minute, tzinfo=timezone.utc)
        leg = ExecutionLeg(
            leg_id="S4-MINI-HEDGE-LEG",
            side=side,
            quantity=quantity,
        )
        plan = MultiLegExecutionPlan(
            group_id=group_id,
            strategy_id=strategy.strategy_id,
            purpose="GAMMA_REBALANCE",
            legs=(leg,),
        )
        client_order_id = f"SYNTHETIC-ORDER-{execution_id}"
        command = BrokerOrderCommand(
            client_order_id=client_order_id,
            instrument_id=instrument.instrument_id,
            side=side,
            quantity=quantity,
            order_type="LIMIT",
            instrument_identity=instrument,
            asset_type="FUTURES",
            strategy_id=strategy.strategy_id,
            group_id=group_id,
            leg_id=leg.leg_id,
        )
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=f"SYNTHETIC-BROKER-{execution_id}",
            execution_id=execution_id,
            status="FILLED",
            filled_quantity=quantity,
            remaining_quantity=0,
            execution_price=Decimal("350"),
            execution_timestamp=timestamp,
            fee=Decimal("0.1"),
            group_id=group_id,
            leg_id=leg.leg_id,
        )
        bridge._apply_reconciled_execution(
            plan=plan,
            leg=leg,
            identity=instrument,
            broker_command=command,
            report=report,
        )
        return plan, leg, command, report

    def signed_from_lots() -> int:
        lots = [
            lot for lot in bridge.position_lot_store.open_lots()
            if lot.run_id == run_id
            and lot.strategy_id == strategy.strategy_id
            and lot.group_id == group_id
            and lot.instrument_id == instrument.instrument_id
        ]
        return sum(lot.remaining_quantity if lot.side == "BUY" else -lot.remaining_quantity for lot in lots)

    def signed_from_aggregate() -> int:
        position = bridge.leg_positions[instrument.instrument_id]
        return position.qty if position.side == "BUY" else -position.qty

    # One of two proposed contracts fills: target and actual projection diverge.
    apply_fill(execution_id="SYNTH-S4-SELL-001", side="SELL", quantity=1, minute=1)
    assert strategy.state.active_hedge_qty == -2
    assert signed_from_lots() == -1
    assert signed_from_aggregate() == -1
    assert bridge.leg_positions[instrument.instrument_id].side == "SELL"
    assert bridge.leg_positions[instrument.instrument_id].qty == 1

    # Second independent fill brings both existing projections to -2.
    first = apply_fill(execution_id="SYNTH-S4-SELL-002", side="SELL", quantity=1, minute=2)
    assert signed_from_lots() == -2
    assert signed_from_aggregate() == -2

    # Exact replay does not double-count either projection.
    plan, leg, command, report = first
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=instrument, broker_command=command, report=report,
    )
    assert signed_from_lots() == -2
    assert signed_from_aggregate() == -2

    # One synthetic BUY close reduces the same owned run/strategy/group by one.
    apply_fill(execution_id="SYNTH-S4-BUY-CLOSE-001", side="BUY", quantity=1, minute=3)
    assert signed_from_lots() == -1
    assert signed_from_aggregate() == -1
    assert strategy.state.active_hedge_qty == -2  # target state is not auto-reconciled
