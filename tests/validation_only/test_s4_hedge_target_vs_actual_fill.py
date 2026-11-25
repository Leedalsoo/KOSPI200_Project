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

def test_s4_vssf_account_matches_position_lot_and_virtual_aggregate_across_partial_fill_close_and_replay(monkeypatch) -> None:
    """Compare all three synthetic Virtual projections without defining Production ownership policy."""
    from hashlib import sha256
    from application.bootstrap import create_virtual_runtime_bootstrap
    from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
    from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
    from core.option.option_master import InMemoryOptionContractMaster
    from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
    from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=InMemoryOptionContractMaster(auto_load_kis_source=False),
        initial_capital=1_000_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("track4_gamma_scalping", "1.0"),),
        run_id="S4-VSSF-THREE-PROJECTION-1826",
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-11-25T10:00:00+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=2, asset_type="FUTURES", requested_price=None,
        side="SELL", track_id="track4_gamma_scalping", tag_id="GAMMA_REBALANCE",
        option_type=None, strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"), qty=2,
        tag_id="GAMMA_REBALANCE", track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    assert identity.identity_source.startswith("SYNTHETIC:")
    assert identity.contract_multiplier == Decimal("50000")

    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_DERIVED_SCENARIO",
            policy_version="S4-VSSF-THREE-PROJECTION-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|S4-1826".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    original_execute = vssf._execute
    first_entry_fill = {"done": False}

    def partial_entry(command, price, now, *, quantity=None):
        if not first_entry_fill["done"]:
            first_entry_fill["done"] = True
            return original_execute(command, price, now, quantity=1)
        return original_execute(command, price, now, quantity=quantity)

    monkeypatch.setattr(vssf, "_execute", partial_entry)
    partial_entry_result = bridge.execute(plan)
    assert partial_entry_result.reports[0].status == "PARTIALLY_FILLED"
    assert partial_entry_result.reports[0].filled_quantity == 1
    client_order_id = partial_entry_result.reports[0].client_order_id
    pending_plan, pending_leg, broker_command = bridge.pending_legs[client_order_id]

    def signed_projections() -> tuple[int, int, int]:
        account_position = vssf.account.positions[identity.instrument_id]
        account_signed = int(account_position["qty"]) * (
            1 if str(account_position["side"]).upper() == "BUY" else -1
        )
        lots = [
            lot for lot in bridge.position_lot_store.open_lots()
            if lot.run_id == bridge.run_id
            and lot.strategy_id == plan.strategy_id
            and lot.group_id == plan.group_id
            and lot.instrument_id == identity.instrument_id
        ]
        lot_signed = sum(
            lot.remaining_quantity if lot.side == "BUY" else -lot.remaining_quantity
            for lot in lots
        )
        aggregate = bridge.leg_positions[identity.instrument_id]
        aggregate_signed = aggregate.qty if aggregate.side == "BUY" else -aggregate.qty
        return account_signed, lot_signed, aggregate_signed

    assert signed_projections() == (-1, -1, -1)

    # Exact bridge replay must not reapply PositionLot/aggregate; VSSF account is unchanged.
    bridge._apply_reconciled_execution(
        plan=pending_plan, leg=pending_leg, identity=identity,
        broker_command=broker_command, report=partial_entry_result.reports[0],
    )
    assert signed_projections() == (-1, -1, -1)

    # Complete the second contract in the same synthetic VSSF order and reconcile both fills.
    canonical_command = bridge.command_context.build_command(broker_command)
    original_execute(canonical_command, Decimal("1000"), vssf._now(), quantity=1)
    latest_entry = bridge.ack.broker.query(client_order_id)
    assert latest_entry is not None and latest_entry.status == "FILLED"
    assert sorted(fill.filled_quantity for fill in latest_entry.execution_fills) == [1, 1]
    bridge.execute(
        plan, group_plan=pending_plan,
        reconciled_reports={client_order_id: latest_entry},
        reconciled_commands={client_order_id: broker_command},
    )
    assert signed_projections() == (-2, -2, -2)

    # Replay the cumulative two-fill report: the already-applied fill IDs remain idempotent.
    bridge._apply_reconciled_execution(
        plan=pending_plan, leg=pending_leg, identity=identity,
        broker_command=broker_command, report=latest_entry,
    )
    assert signed_projections() == (-2, -2, -2)

    # A one-contract BUY partial close leaves one SELL contract in every projection.
    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id=plan.strategy_id, purpose="S4_SYNTHETIC_PARTIAL_CLOSE_1826",
        asset_type="FUTURES",
    )
    assert close_plan.legs[0].side == "BUY" and close_plan.legs[0].quantity == 2
    partial_close_state = {"done": False}

    def partial_close(command, price, now, *, quantity=None):
        if not partial_close_state["done"]:
            partial_close_state["done"] = True
            return original_execute(command, price, now, quantity=1)
        return original_execute(command, price, now, quantity=quantity)

    monkeypatch.setattr(vssf, "_execute", partial_close)
    partial_close_result = bridge.execute(close_plan)
    assert partial_close_result.reports[0].status == "PARTIALLY_FILLED"
    assert partial_close_result.reports[0].filled_quantity == 1
    close_client_order_id = partial_close_result.reports[0].client_order_id
    close_pending_plan, close_pending_leg, close_command = bridge.pending_legs[close_client_order_id]
    assert signed_projections() == (-1, -1, -1)

    bridge._apply_reconciled_execution(
        plan=close_pending_plan, leg=close_pending_leg, identity=identity,
        broker_command=close_command, report=partial_close_result.reports[0],
    )
    assert signed_projections() == (-1, -1, -1)

    # Close the remaining contract; the three projections converge to flat.
    final_close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id=plan.strategy_id, purpose="S4_SYNTHETIC_FINAL_CLOSE_1826",
        asset_type="FUTURES",
    )
    assert final_close_plan.legs[0].side == "BUY"
    assert final_close_plan.legs[0].quantity == 1
    final_close = bridge.execute(final_close_plan)
    assert final_close.group_complete is True
    assert bridge.position_lot_store.open_lots() == ()
    account_position = vssf.account.positions.get(identity.instrument_id)
    assert account_position is None or int(account_position.get("qty", 0)) == 0
    aggregate = bridge.leg_positions[identity.instrument_id]
    assert aggregate.qty == 0

def test_s4_vssf_restart_snapshot_restores_only_balance_and_positions_not_execution_state() -> None:
    """Characterize the current in-memory VSSF snapshot boundary; do not approve restart policy."""
    from datetime import timezone
    from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide

    stamp = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
    instrument_id = "SYNTHETIC:MINI-RESTART-1827"

    def command(client_order_id: str, side: object) -> SimpleNamespace:
        return SimpleNamespace(
            client_order_id=client_order_id,
            track_id="track4_gamma_scalping",
            asset_type=CanonicalAssetType.FUTURES,
            side=side,
            symbol=instrument_id,
            instrument_id=instrument_id,
            contract_multiplier=Decimal("50000"),
            strategy_id="track4_gamma_scalping",
            group_id="SYNTHETIC:GROUP:1827",
            leg_id="mini",
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
            option_type=None,
            strike=0,
            expiry="20261210",
        )

    first_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id="SYNTHETIC:RUN:1827",
        validation_candidate_id="SYNTHETIC:CANDIDATE:S4",
    )
    first_fill = first_runtime.execution_engine.execute_order(
        command("SYNTHETIC:ENTRY:1827", CanonicalOrderSide.BUY),
        Decimal("1000"), 2, timestamp=stamp,
    )
    first_runtime.account.apply_execution(first_fill)
    close_fill = first_runtime.execution_engine.execute_order(
        command("SYNTHETIC:PARTIAL-CLOSE:1827", CanonicalOrderSide.SELL),
        Decimal("1002"), 1, timestamp=stamp,
    )
    first_runtime.account.apply_execution(close_fill)
    first_runtime.account.update_tick_price(Decimal("1003"), instrument_id)

    pending_command = command("SYNTHETIC:PENDING:1827", CanonicalOrderSide.BUY)
    first_runtime.order_book.add_pending_order(pending_command)
    first_runtime._submitted_at[pending_command.client_order_id] = stamp
    snapshot = first_runtime.recovery_engine.create_snapshot(
        "SYNTHETIC:CHECKPOINT:1827", metrics=first_runtime.metrics,
    )

    restarted_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id="SYNTHETIC:RUN:1827",
        validation_candidate_id="SYNTHETIC:CANDIDATE:S4",
    )
    restored_metrics: dict[str, int] = {}
    assert restarted_runtime.recovery_engine.restore_from_snapshot(
        snapshot, target_metrics=restored_metrics,
    ) is True

    # The existing snapshot restores only balance and position dictionaries.
    assert restarted_runtime.account.balance == first_runtime.account.balance
    assert restarted_runtime.account.positions == first_runtime.account.positions
    assert restarted_runtime.account.realized_pnl == Decimal("0")
    assert restarted_runtime.account.realized_pnl != first_runtime.account.realized_pnl
    assert restarted_runtime.account.unrealized_pnl == Decimal("0")
    assert restarted_runtime.account.unrealized_pnl != first_runtime.account.unrealized_pnl
    assert restarted_runtime.account.used_margin == Decimal("0")
    assert restarted_runtime.account.used_margin != first_runtime.account.used_margin
    assert restarted_runtime.account.ledger_engine.transactions == []
    assert len(first_runtime.account.ledger_engine.transactions) == 2

    # Runtime-local execution IDs and pending-order state are not restored.
    assert len(first_runtime.execution_engine.reports) == 2
    assert restarted_runtime.execution_engine.reports == []
    assert restarted_runtime.execution_engine._seq == 0
    assert restarted_runtime.order_book.pending_orders() == ()
    assert pending_command.client_order_id not in restarted_runtime._submitted_at
    next_fill = restarted_runtime.execution_engine.execute_order(
        command("SYNTHETIC:AFTER-RESTART:1827", CanonicalOrderSide.BUY),
        Decimal("1000"), 1, timestamp=stamp,
    )
    assert next_fill.exec_id == first_fill.exec_id == "EXEC-000001"


def test_s4_vssf_restart_late_fill_reconciles_account_but_not_prior_lot_fee_history() -> None:
    """Characterize restart projections and late-fill replay using synthetic VSSF events only."""
    from datetime import timezone

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import BrokerOrderCommand, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan
    from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
    from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide

    stamp = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)
    source = "SYNTHETIC:DERIVED_SCENARIO"
    run_id = "SYNTHETIC:S4:RUN:1828"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:1828"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:1828"
    leg_id = "mini"
    instrument_id = "SYNTHETIC:MINI:RESTART:1828"
    identity = FuturesInstrumentIdentity(
        instrument_id=instrument_id,
        symbol=instrument_id,
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source=source,
    )

    def vssf_command(client_order_id: str, side: str) -> SimpleNamespace:
        return SimpleNamespace(
            client_order_id=client_order_id,
            track_id=strategy_id,
            asset_type=CanonicalAssetType.FUTURES,
            side=CanonicalOrderSide(side),
            symbol=instrument_id,
            instrument_id=instrument_id,
            contract_multiplier=Decimal("50000"),
            strategy_id=strategy_id,
            group_id=group_id,
            leg_id=leg_id,
            identity_source=source,
            option_type=None,
            strike=0,
            expiry="20261210",
        )

    def signed_account(runtime: VirtualSecuritiesFirmRuntime) -> int:
        position = runtime.account.positions.get(instrument_id)
        if not position:
            return 0
        quantity = int(position["qty"])
        return quantity if str(position["side"]).upper() == "BUY" else -quantity

    def make_bridge() -> VirtualMultiLegExecutionBridge:
        bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
        bridge.run_id = run_id
        bridge.position_lot_store = VirtualPositionLotStore()
        bridge.fee_ledger = VirtualTrack9FeeLedger()
        bridge.leg_positions = {}
        bridge.execution_legs = {}
        bridge.provenance = {}
        bridge._applied_execution_fingerprints = {}
        return bridge

    def apply_bridge_event(
        bridge: VirtualMultiLegExecutionBridge, fill, side: str,
    ) -> tuple[MultiLegExecutionPlan, ExecutionLeg, BrokerOrderCommand, ExecutionReport]:
        client_order_id = fill.client_order_id
        quantity = int(fill.executed_qty)
        leg = ExecutionLeg(
            leg_id=leg_id, side=side, quantity=quantity,
            instrument_identity=identity,
        )
        plan = MultiLegExecutionPlan(
            group_id=group_id, strategy_id=strategy_id,
            purpose="S4_SYNTHETIC_GAMMA_REBALANCE_1828", legs=(leg,),
        )
        broker_command = BrokerOrderCommand(
            client_order_id=client_order_id,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            order_type="MARKET",
            instrument_identity=identity,
            asset_type="FUTURES",
            strategy_id=strategy_id,
            track_id=strategy_id,
            group_id=group_id,
            leg_id=leg_id,
        )
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=f"SYNTHETIC-BROKER:{fill.exec_id}",
            execution_id=fill.exec_id,
            status="FILLED",
            filled_quantity=quantity,
            remaining_quantity=0,
            execution_price=Decimal(str(fill.executed_price)),
            execution_timestamp=datetime.fromisoformat(fill.timestamp),
            fee=Decimal(str(fill.fee)),
            group_id=group_id,
            leg_id=leg_id,
        )
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=broker_command, report=report,
        )
        return plan, leg, broker_command, report

    first_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    entry = first_runtime.execution_engine.execute_order(
        vssf_command("SYNTHETIC:S4:ENTRY:1828", "BUY"),
        Decimal("1000"), 2, timestamp=stamp,
    )
    first_runtime.account.apply_execution(entry)
    partial_close = first_runtime.execution_engine.execute_order(
        vssf_command("SYNTHETIC:S4:PARTIAL-CLOSE:1828", "SELL"),
        Decimal("1002"), 1, timestamp=stamp,
    )
    first_runtime.account.apply_execution(partial_close)

    pre_restart_bridge = make_bridge()
    apply_bridge_event(pre_restart_bridge, entry, "BUY")
    apply_bridge_event(pre_restart_bridge, partial_close, "SELL")
    assert signed_account(first_runtime) == 1
    assert len(first_runtime.account.ledger_engine.transactions) == 2
    assert len(pre_restart_bridge.position_lot_store.open_lots()) == 1
    assert pre_restart_bridge.position_lot_store.open_lots()[0].remaining_quantity == 1
    assert len(pre_restart_bridge.fee_ledger.snapshot(run_id=run_id)) == 2
    assert pre_restart_bridge.leg_positions[instrument_id].side == "BUY"
    assert pre_restart_bridge.leg_positions[instrument_id].qty == 1

    snapshot = first_runtime.recovery_engine.create_snapshot(
        "SYNTHETIC:S4:CHECKPOINT:1828", metrics=first_runtime.metrics,
    )

    # A late fill is generated after the checkpoint by the original synthetic runtime.
    late_close = first_runtime.execution_engine.execute_order(
        vssf_command("SYNTHETIC:S4:LATE-CLOSE:1828", "SELL"),
        Decimal("1003"), 1, timestamp=stamp,
    )
    first_runtime.account.apply_execution(late_close)
    assert late_close.exec_id == "EXEC-000003"
    assert signed_account(first_runtime) == 0

    restarted_runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    assert restarted_runtime.recovery_engine.restore_from_snapshot(snapshot) is True
    assert signed_account(restarted_runtime) == 1
    assert restarted_runtime.account.ledger_engine.transactions == []
    assert restarted_runtime.execution_engine.reports == []
    assert restarted_runtime.execution_engine._seq == 0

    # Deliver the late event to the restored account and a fresh bridge projection.
    restarted_runtime.account.apply_execution(late_close)
    post_restart_bridge = make_bridge()
    late_event = apply_bridge_event(post_restart_bridge, late_close, "SELL")
    assert signed_account(restarted_runtime) == 0
    assert len(restarted_runtime.account.ledger_engine.transactions) == 1
    assert restarted_runtime.execution_engine.reports == []

    # The account restores its pre-checkpoint net position, but the new bridge has
    # no pre-checkpoint PositionLot/Fee history: only the late SELL event is present.
    assert len(post_restart_bridge.position_lot_store.open_lots()) == 1
    late_lot = post_restart_bridge.position_lot_store.open_lots()[0]
    assert late_lot.execution_id == late_close.exec_id
    assert late_lot.side == "SELL" and late_lot.remaining_quantity == 1
    assert len(post_restart_bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert post_restart_bridge.leg_positions[instrument_id].side == "SELL"
    assert post_restart_bridge.leg_positions[instrument_id].qty == 1
    assert (signed_account(restarted_runtime), -1, -1) == (0, -1, -1)

    # Exact redelivery is deduplicated only inside this fresh bridge's in-memory state.
    plan, leg, broker_command, report = late_event
    post_restart_bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=broker_command, report=report,
    )
    assert len(post_restart_bridge.position_lot_store.open_lots()) == 1
    assert len(post_restart_bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert post_restart_bridge.leg_positions[instrument_id].qty == 1


def test_s4_vssf_restored_account_reapplies_duplicate_late_fill_without_execution_dedupe() -> None:
    """Characterize duplicate late-fill delivery to a restored synthetic VSSF account."""
    from datetime import timezone

    from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide

    stamp = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
    run_id = "SYNTHETIC:S4:RUN:1829"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:1829"
    instrument_id = "SYNTHETIC:MINI:DUPLICATE:1829"

    def command(client_order_id: str, side: CanonicalOrderSide) -> SimpleNamespace:
        return SimpleNamespace(
            client_order_id=client_order_id,
            track_id="track4_gamma_scalping",
            asset_type=CanonicalAssetType.FUTURES,
            side=side,
            symbol=instrument_id,
            instrument_id=instrument_id,
            contract_multiplier=Decimal("50000"),
            strategy_id="track4_gamma_scalping",
            group_id="SYNTHETIC:S4:GROUP:1829",
            leg_id="mini",
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
            option_type=None,
            strike=0,
            expiry="20261210",
        )

    def signed_position(runtime: VirtualSecuritiesFirmRuntime) -> int:
        position = runtime.account.positions.get(instrument_id)
        if not position:
            return 0
        qty = int(position["qty"])
        return qty if str(position["side"]).upper() == "BUY" else -qty

    original = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    entry = original.execution_engine.execute_order(
        command("SYNTHETIC:S4:ENTRY:1829", CanonicalOrderSide.BUY),
        Decimal("1000"), 1, timestamp=stamp,
    )
    original.account.apply_execution(entry)
    snapshot = original.recovery_engine.create_snapshot(
        "SYNTHETIC:S4:CHECKPOINT:1829", metrics=original.metrics,
    )
    late_fill = original.execution_engine.execute_order(
        command("SYNTHETIC:S4:LATE-EXIT:1829", CanonicalOrderSide.SELL),
        Decimal("1001"), 1, timestamp=stamp,
    )

    restored = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    assert restored.recovery_engine.restore_from_snapshot(snapshot) is True
    assert signed_position(restored) == 1
    assert restored.account.ledger_engine.transactions == []

    # First delivery closes the restored BUY position.
    restored.account.apply_execution(late_fill)
    assert signed_position(restored) == 0
    assert [row["exec_id"] for row in restored.account.ledger_engine.transactions] == [late_fill.exec_id]

    # Exact redelivery reaches PaperTradingAccount again; no execution-ID gate is present.
    restored.account.apply_execution(late_fill)
    position = restored.account.positions[instrument_id]
    assert signed_position(restored) == -1
    assert position["side"] == "SELL" and position["qty"] == 1
    assert position["avg_price"] == 1001.0
    assert [row["exec_id"] for row in restored.account.ledger_engine.transactions] == [
        late_fill.exec_id, late_fill.exec_id,
    ]
    assert restored.account.realized_pnl == Decimal("50000.0")
    assert restored.execution_engine.reports == []

def test_s4_vssf_same_execution_id_changed_payload_diverges_from_bridge_conflict_gate() -> None:
    """Characterize changed-payload reuse of one synthetic execution ID after restart."""
    from dataclasses import replace
    from datetime import datetime, timezone

    import pytest

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import BrokerOrderCommand, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan
    from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
    from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide

    stamp = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
    run_id = "SYNTHETIC:S4:RUN:1830"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:1830"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:1830"
    leg_id = "mini"
    instrument_id = "SYNTHETIC:MINI:EXECUTION-ID-REUSE:1830"
    source = "SYNTHETIC:DERIVED_SCENARIO"
    multiplier = Decimal("50000")
    identity = FuturesInstrumentIdentity(
        instrument_id=instrument_id, symbol=instrument_id,
        product_type=FuturesProductType.MINI,
        contract_multiplier=multiplier, identity_source=source,
    )

    def account_command(client_order_id: str, side: CanonicalOrderSide) -> SimpleNamespace:
        return SimpleNamespace(
            client_order_id=client_order_id, track_id=strategy_id,
            asset_type=CanonicalAssetType.FUTURES, side=side,
            symbol=instrument_id, instrument_id=instrument_id,
            contract_multiplier=multiplier, strategy_id=strategy_id,
            group_id=group_id, leg_id=leg_id, identity_source=source,
            option_type=None, strike=0, expiry="20261210",
        )

    def signed_position(runtime: VirtualSecuritiesFirmRuntime) -> int:
        position = runtime.account.positions.get(instrument_id)
        if not position:
            return 0
        quantity = int(position["qty"])
        return quantity if str(position["side"]).upper() == "BUY" else -quantity

    original = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    entry = original.execution_engine.execute_order(
        account_command("SYNTHETIC:S4:ENTRY:1830", CanonicalOrderSide.BUY),
        Decimal("1000"), 3, timestamp=stamp,
    )
    original.account.apply_execution(replace(entry, fee=0.05))
    snapshot = original.recovery_engine.create_snapshot(
        "SYNTHETIC:S4:CHECKPOINT:1830", metrics=original.metrics,
    )
    late_fill = original.execution_engine.execute_order(
        account_command("SYNTHETIC:S4:LATE-SELL:1830", CanonicalOrderSide.SELL),
        Decimal("1001"), 1, timestamp=stamp,
    )
    late_fill = replace(late_fill, fee=0.10)

    restored = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    assert restored.recovery_engine.restore_from_snapshot(snapshot) is True
    assert signed_position(restored) == 3

    # The first report partially reduces the restored long position.
    restored.account.apply_execution(late_fill)
    assert signed_position(restored) == 2
    first_balance = restored.account.balance
    first_realized = restored.account.realized_pnl
    assert [row["exec_id"] for row in restored.account.ledger_engine.transactions] == [late_fill.exec_id]

    # Same execution ID, but changed client order, quantity, price and fee.
    changed_payload = replace(
        late_fill,
        client_order_id="SYNTHETIC:S4:ALTERED-ORDER:1830",
        executed_qty=2,
        executed_price=1002.0,
        fee=0.25,
    )
    restored.account.apply_execution(changed_payload)
    assert signed_position(restored) == 0
    assert [row["exec_id"] for row in restored.account.ledger_engine.transactions] == [
        late_fill.exec_id, late_fill.exec_id,
    ]
    assert restored.account.balance == first_balance - Decimal("0.25")
    assert restored.account.realized_pnl > first_realized
    assert restored.account.used_margin == 0

    # The Bridge has a different in-memory fingerprint boundary: same ID with
    # changed payload raises before a second lot/fee/aggregate publication.
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = run_id
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    bridge.leg_positions = {}
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge._applied_execution_fingerprints = {}

    def bridge_apply(client_order_id: str, quantity: int, price: str, fee: str) -> None:
        leg = ExecutionLeg(
            leg_id=leg_id, side="SELL", quantity=quantity,
            instrument_identity=identity,
        )
        plan = MultiLegExecutionPlan(
            group_id=group_id, strategy_id=strategy_id,
            purpose="S4_SYNTHETIC_EXECUTION_ID_REUSE_1830", legs=(leg,),
        )
        command = BrokerOrderCommand(
            client_order_id=client_order_id, instrument_id=instrument_id,
            side="SELL", quantity=quantity, order_type="MARKET",
            instrument_identity=identity, asset_type="FUTURES",
            strategy_id=strategy_id, track_id=strategy_id,
            group_id=group_id, leg_id=leg_id,
        )
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id="SYNTHETIC-BROKER:1830",
            execution_id=late_fill.exec_id, status="FILLED",
            filled_quantity=quantity, remaining_quantity=0,
            execution_price=Decimal(price), execution_timestamp=stamp,
            fee=Decimal(fee), group_id=group_id, leg_id=leg_id,
        )
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    bridge_apply("SYNTHETIC:S4:LATE-SELL:1830", 1, "1001", "0.10")
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert bridge.leg_positions[instrument_id].qty == 1
    with pytest.raises(RuntimeError, match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED"):
        bridge_apply("SYNTHETIC:S4:ALTERED-ORDER:1830", 2, "1002", "0.25")
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=run_id)) == 1
    assert bridge.fee_ledger.total(run_id=run_id) == Decimal("0.10")
    assert bridge.leg_positions[instrument_id].qty == 1

def test_s4_vssf_account_bridge_fee_pnl_margin_and_restart_projection_divergence() -> None:
    """Compare synthetic account and Bridge projections before and after VSSF snapshot restore."""
    from dataclasses import replace
    from datetime import datetime, timezone

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity
    from contracts.types import BrokerOrderCommand, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan
    from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
    from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
    from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide

    stamp = datetime(2026, 11, 25, 5, 0, tzinfo=timezone.utc)
    run_id = "SYNTHETIC:S4:RUN:1831"
    candidate_id = "SYNTHETIC:S4:CANDIDATE:1831"
    strategy_id = "track4_gamma_scalping"
    group_id = "SYNTHETIC:S4:GROUP:1831"
    leg_id = "mini"
    instrument_id = "SYNTHETIC:MINI:ACCOUNT-BRIDGE-1831"
    source = "SYNTHETIC:DERIVED_SCENARIO"
    multiplier = Decimal("50000")
    identity = FuturesInstrumentIdentity(
        instrument_id=instrument_id, symbol=instrument_id,
        product_type=FuturesProductType.MINI,
        contract_multiplier=multiplier, identity_source=source,
    )

    def command(client_order_id: str, side: CanonicalOrderSide) -> SimpleNamespace:
        return SimpleNamespace(
            client_order_id=client_order_id, track_id=strategy_id,
            asset_type=CanonicalAssetType.FUTURES, side=side,
            symbol=instrument_id, instrument_id=instrument_id,
            contract_multiplier=multiplier, strategy_id=strategy_id,
            group_id=group_id, leg_id=leg_id, identity_source=source,
            option_type=None, strike=0, expiry="20261210",
        )

    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = run_id
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    bridge.leg_positions = {}
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge._applied_execution_fingerprints = {}

    def apply_bridge(fill, side: str) -> None:
        leg = ExecutionLeg(leg_id=leg_id, side=side, quantity=fill.executed_qty,
                           instrument_identity=identity)
        plan = MultiLegExecutionPlan(
            group_id=group_id, strategy_id=strategy_id,
            purpose="S4_SYNTHETIC_ACCOUNT_BRIDGE_RECON_1831", legs=(leg,),
        )
        broker_command = BrokerOrderCommand(
            client_order_id=fill.client_order_id, instrument_id=instrument_id,
            side=side, quantity=fill.executed_qty, order_type="MARKET",
            instrument_identity=identity, asset_type="FUTURES",
            strategy_id=strategy_id, track_id=strategy_id,
            group_id=group_id, leg_id=leg_id,
        )
        report = ExecutionReport(
            client_order_id=fill.client_order_id,
            broker_order_id=f"SYNTHETIC-BROKER:{fill.exec_id}",
            execution_id=fill.exec_id, status="FILLED",
            filled_quantity=fill.executed_qty, remaining_quantity=0,
            execution_price=Decimal(str(fill.executed_price)),
            execution_timestamp=datetime.fromisoformat(fill.timestamp),
            fee=Decimal(str(fill.fee)), group_id=group_id, leg_id=leg_id,
        )
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=broker_command, report=report,
        )

    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    entry = runtime.execution_engine.execute_order(
        command("SYNTHETIC:S4:ENTRY:1831", CanonicalOrderSide.BUY),
        Decimal("1000"), 2, timestamp=stamp,
    )
    entry = replace(entry, fee=Decimal("0.10"))
    runtime.account.apply_execution(entry)
    apply_bridge(entry, "BUY")

    partial_close = runtime.execution_engine.execute_order(
        command("SYNTHETIC:S4:PARTIAL-CLOSE:1831", CanonicalOrderSide.SELL),
        Decimal("1002"), 1, timestamp=stamp,
    )
    partial_close = replace(partial_close, fee=Decimal("0.20"))
    runtime.account.apply_execution(partial_close)
    apply_bridge(partial_close, "SELL")
    runtime.account.update_tick_price(Decimal("1003"), instrument_id)

    account = runtime.account
    assert account.balance == Decimal("999999999.70")
    assert account.realized_pnl == Decimal("100000.0")
    assert account.unrealized_pnl == Decimal("150000.0")
    assert account.used_margin == Decimal("50000000.0")
    assert account.free_margin == Decimal("950249999.70")
    assert account.positions[instrument_id]["qty"] == 1
    assert account.positions[instrument_id]["side"] == "BUY"
    assert [row["exec_id"] for row in account.ledger_engine.transactions] == [
        entry.exec_id, partial_close.exec_id,
    ]

    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].side == "BUY" and lots[0].remaining_quantity == 1
    assert bridge.fee_ledger.total(run_id=run_id) == Decimal("0.30")
    assert len(bridge.fee_ledger.snapshot(run_id=run_id)) == 2
    assert bridge.leg_positions[instrument_id].side == "BUY"
    assert bridge.leg_positions[instrument_id].qty == 1

    snapshot = runtime.recovery_engine.create_snapshot(
        "SYNTHETIC:S4:CHECKPOINT:1831", metrics=runtime.metrics,
    )
    restored = VirtualSecuritiesFirmRuntime(
        initial_capital=1_000_000_000,
        validation_run_id=run_id,
        validation_candidate_id=candidate_id,
    )
    assert restored.recovery_engine.restore_from_snapshot(snapshot) is True
    assert restored.account.balance == account.balance
    assert restored.account.positions == account.positions
    assert restored.account.realized_pnl == Decimal("0")
    assert restored.account.unrealized_pnl == Decimal("0")
    assert restored.account.used_margin == Decimal("0")
    assert restored.account.free_margin == Decimal("1000000000")
    assert restored.account.ledger_engine.transactions == []
    assert restored.execution_engine.reports == []
    assert restored.execution_engine._seq == 0
    # The Bridge's pre-checkpoint lot and fee records are a separate in-memory
    # projection and are not part of the VSSF account snapshot.
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert bridge.fee_ledger.total(run_id=run_id) == Decimal("0.30")
