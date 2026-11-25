from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from hashlib import sha256
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import (
    attach_standard_automated_loop,
)
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.option.option_master import InMemoryOptionContractMaster
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources


def _loop(strategy_key: tuple[str, str], run_id: str):
    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=InMemoryOptionContractMaster(auto_load_kis_source=False),
        initial_capital=1_000_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    return attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(strategy_key,),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )


def test_track4_virtual_runtime_binds_synthetic_mini_futures_identity() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-FUTURES-IDENTITY-VALIDATION")
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )

    plan = loop.multi_leg_plan_resolver(evaluation, canonical)

    assert plan is not None
    assert plan.strategy_id == "track4_gamma_scalping"
    assert len(plan.legs) == 1
    leg = plan.legs[0]
    assert leg.side == "SELL"
    assert leg.quantity == 5
    assert leg.instrument_identity.product_type is FuturesProductType.MINI
    assert leg.instrument_identity.contract_multiplier == Decimal(50000)
    assert leg.instrument_identity.identity_source.startswith("SYNTHETIC:")


def test_other_synthetic_futures_routes_keep_standard_contract_spec() -> None:
    loop = _loop(("TRACK1_TAIL_DEFENSE", "1.2.0"), "SYNTHETIC-STANDARD-FUTURES-IDENTITY")
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="FUTURES",
        requested_price=None,
        side="BUY",
        track_id="TRACK1_TAIL_DEFENSE",
        tag_id="FUTURES_HEDGE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="TRACK1_TAIL_DEFENSE"),
        result=SimpleNamespace(execution_proposal=proposal),
    )

    identity = loop.identity_provider(evaluation, tick, asset_type="FUTURES")

    assert identity.product_type is FuturesProductType.STANDARD
    assert identity.contract_multiplier == Decimal(250000)


def test_track4_mini_futures_runtime_routes_fills_and_closes_flat(monkeypatch) -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-FUTURES-RUNTIME-E2E")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == Decimal(50000)

    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_DERIVED_SCENARIO",
            policy_version="S4-MINI-RUNTIME-FAULT-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|S4".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    entry = bridge.execute(plan)
    assert entry.approved_legs == entry.routed_legs == 1
    assert entry.filled_legs == 5
    assert entry.group_complete is True
    assert entry.reports[0].status == "FILLED"
    assert entry.reports[0].filled_quantity == 5
    assert entry.reports[0].execution_id
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].instrument_id == identity.instrument_id
    assert lots[0].contract_multiplier == Decimal(50000)
    assert lots[0].instrument_identity == identity
    assert vssf.account.positions[identity.instrument_id]["qty"] == 5

    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track4_gamma_scalping",
        purpose="S4_VALIDATION_CLOSE_PARTIAL",
        asset_type="FUTURES",
    )
    assert close_plan.legs[0].side == "BUY"
    assert close_plan.legs[0].quantity == 5
    original_execute = vssf._execute
    partial_close_state = {"done": False}

    def partial_close_first(command, price, now, *, quantity=None):
        if not partial_close_state["done"]:
            partial_close_state["done"] = True
            return original_execute(command, price, now, quantity=2)
        return original_execute(command, price, now, quantity=quantity)

    monkeypatch.setattr(vssf, "_execute", partial_close_first)
    partial_close = bridge.execute(close_plan)
    assert partial_close.routed_legs == 1
    assert partial_close.filled_legs == 2
    assert partial_close.reports[0].status == "PARTIALLY_FILLED"
    assert partial_close.reports[0].filled_quantity == 2
    assert partial_close.reports[0].remaining_quantity == 3

    cancelled_close = bridge.cancel_pending_order(
        partial_close.reports[0].client_order_id,
        reason="S4_VALIDATION_PARTIAL_CLOSE_CANCEL",
    )
    assert cancelled_close.reports[0].status == "CANCELLED"
    assert cancelled_close.reports[0].filled_quantity == 2
    remaining_lots = bridge.position_lot_store.open_lots()
    assert sum(lot.remaining_quantity for lot in remaining_lots) == 3

    remaining_close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track4_gamma_scalping",
        purpose="S4_VALIDATION_CLOSE_REMAINDER",
        asset_type="FUTURES",
    )
    assert len(remaining_close_plan.legs) == 1
    assert remaining_close_plan.legs[0].side == "BUY"
    assert remaining_close_plan.legs[0].quantity == 3
    close = bridge.execute(remaining_close_plan)
    assert close.approved_legs == close.routed_legs == 1
    assert close.filled_legs == 3
    assert close.group_complete is True
    assert close.reports[0].status == "FILLED"
    assert close.reports[0].filled_quantity == 3
    assert bridge.position_lot_store.open_lots() == ()
    remaining_position = vssf.account.positions.get(identity.instrument_id)
    assert remaining_position is None or int(remaining_position.get("qty", 0)) == 0
    assert close.position_flat is True


def test_track4_standard_futures_identity_is_rejected_before_vssf_submission() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-IDENTITY-FAULT-INJECTION")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    valid_identity = plan.legs[0].instrument_identity
    standard_identity = replace(
        valid_identity,
        product_type=FuturesProductType.STANDARD,
        contract_multiplier=Decimal(250000),
    )
    invalid_leg = replace(plan.legs[0], instrument_identity=standard_identity)
    invalid_plan = replace(plan, legs=(invalid_leg,))
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    before = vssf.metrics["order_commands"]

    with pytest.raises(ValueError, match="TRACK4_MINI_FUTURES_IDENTITY_REQUIRED"):
        bridge.execute(invalid_plan)

    assert vssf.metrics["order_commands"] == before == 0
    assert bridge.position_lot_store.open_lots() == ()


def test_track4_mini_partial_fill_cancel_late_fill_u19_restart_reconciles_exactly_once(monkeypatch, tmp_path) -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-LATE-FILL-FAULT")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    assert identity.product_type is FuturesProductType.MINI

    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_DERIVED_SCENARIO",
            policy_version="S4-MINI-LATE-FILL-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|LATE".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    original_execute = vssf._execute
    partial_state = {"done": False}

    def partial_first_fill(command, price, now, *, quantity=None):
        if not partial_state["done"]:
            partial_state["done"] = True
            return original_execute(command, price, now, quantity=2)
        return original_execute(command, price, now, quantity=quantity)

    monkeypatch.setattr(vssf, "_execute", partial_first_fill)
    initial = bridge.execute(plan)
    assert initial.routed_legs == 1
    assert initial.filled_legs == 2
    assert initial.reports[0].status == "PARTIALLY_FILLED"
    assert initial.reports[0].remaining_quantity == 3
    client_order_id = initial.reports[0].client_order_id
    pending_group_plan, pending_leg, broker_command = bridge.pending_legs[client_order_id]
    # Reconcile the active partial-fill position while the residual order is pending.
    from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot, U19ExecutionLedgerSnapshot, U19Position,
        U19RecoveryStatus,
    )
    from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore

    recovery = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "s4-mini-active-position-u19.sqlite3")
    )
    as_of = datetime.fromisoformat(tick.timestamp).replace(tzinfo=timezone(timedelta(hours=9)))
    account_position = vssf.account.positions[identity.instrument_id]
    account_signed = Decimal(str(account_position["qty"])) * (
        Decimal("1") if str(account_position["side"]).upper() == "BUY" else Decimal("-1")
    )
    open_lots = bridge.position_lot_store.open_lots()
    ledger_signed = sum((
        Decimal(lot.remaining_quantity) * (
            Decimal("1") if str(lot.side).upper() == "BUY" else Decimal("-1")
        ) for lot in open_lots if lot.instrument_id == identity.instrument_id
    ), Decimal("0"))
    assert account_signed == ledger_signed == Decimal("-2")

    def recovery_snapshots(*, broker_quantity, ledger_quantity, pending_ids, suffix):
        broker_positions = (U19Position(identity.instrument_id, broker_quantity),)
        ledger_positions = (U19Position(identity.instrument_id, ledger_quantity),)
        broker_payload = f"S4|{suffix}|BROKER|{broker_quantity}|{as_of.isoformat()}".encode()
        ledger_payload = f"S4|{suffix}|LEDGER|{ledger_quantity}|{pending_ids}|{as_of.isoformat()}".encode()
        return (
            U19BrokerPositionSnapshot(
                group_id=plan.group_id, snapshot_id=f"S4-{suffix}-BROKER", as_of=as_of,
                source="VALIDATION_ONLY:BROKER_EXCHANGE", positions=broker_positions,
                complete=True, capability_verified=True,
                payload_sha256=sha256(broker_payload).hexdigest(),
            ),
            U19ExecutionLedgerSnapshot(
                group_id=plan.group_id, snapshot_id=f"S4-{suffix}-LEDGER", as_of=as_of,
                source="VALIDATION_ONLY:EXECUTION_LEDGER", positions=ledger_positions,
                complete=True, payload_sha256=sha256(ledger_payload).hexdigest(),
                pending_order_ids=tuple(pending_ids),
            ),
        )

    pending_broker, pending_ledger = recovery_snapshots(
        broker_quantity=Decimal("-2"), ledger_quantity=Decimal("-2"),
        pending_ids=(client_order_id,), suffix="PENDING",
    )
    pending_decision = recovery.recover(
        group_id=plan.group_id, broker_snapshot=pending_broker, ledger_snapshot=pending_ledger,
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert pending_decision.restore_allowed is False
    assert pending_decision.new_entry_enabled is False
    assert pending_decision.order_submission_enabled is False

    cancelled = bridge.cancel_pending_order(client_order_id, reason="S4_VALIDATION_CANCEL")
    assert cancelled.reports[0].status == "CANCELLED"
    assert cancelled.reports[0].filled_quantity == 2
    assert cancelled.reports[0].remaining_quantity == 3
    assert bridge.position_lot_store.open_lots()
    assert sum(lot.remaining_quantity for lot in bridge.position_lot_store.open_lots()) == 2
    # Terminal cancel removes pending-order uncertainty; a broker/ledger
    # quantity conflict remains a distinct, non-restorable reconciliation result.
    conflict_broker, conflict_ledger = recovery_snapshots(
        broker_quantity=Decimal("-2"), ledger_quantity=Decimal("-1"),
        pending_ids=(), suffix="POSITION-CONFLICT",
    )
    conflict = recovery.recover(
        group_id=plan.group_id, broker_snapshot=conflict_broker, ledger_snapshot=conflict_ledger,
    )
    assert conflict.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert conflict.restore_allowed is False
    side_conflict_broker, side_conflict_ledger = recovery_snapshots(
        broker_quantity=Decimal("2"), ledger_quantity=Decimal("-2"),
        pending_ids=(), suffix="POSITION-SIDE-CONFLICT",
    )
    side_conflict = recovery.recover(
        group_id=plan.group_id, broker_snapshot=side_conflict_broker,
        ledger_snapshot=side_conflict_ledger,
    )
    assert side_conflict.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert side_conflict.restore_allowed is False

    matched_broker, matched_ledger = recovery_snapshots(
        broker_quantity=Decimal("-2"), ledger_quantity=Decimal("-2"),
        pending_ids=(), suffix="POSITION-MATCHED",
    )
    matched = recovery.recover(
        group_id=plan.group_id, broker_snapshot=matched_broker, ledger_snapshot=matched_ledger,
    )
    assert matched.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert matched.positions == matched_broker.positions
    assert matched.new_entry_enabled is False
    assert matched.order_submission_enabled is False

    canonical_command = bridge.command_context.build_command(broker_command)
    original_execute(canonical_command, Decimal("1000"), vssf._now(), quantity=3)
    latest = bridge.ack.broker.query(client_order_id)
    assert latest is not None
    assert latest.status == "FILLED"
    assert latest.filled_quantity == 5
    assert len(latest.execution_fills) == 2
    assert sorted(fill.filled_quantity for fill in latest.execution_fills) == [2, 3]
    assert len({fill.execution_id for fill in latest.execution_fills}) == 2

    reconciled = bridge.execute(
        plan,
        group_plan=pending_group_plan,
        reconciled_reports={client_order_id: latest},
        reconciled_commands={client_order_id: broker_command},
    )
    assert reconciled.filled_legs == 5
    assert reconciled.group_complete is True
    lots = bridge.position_lot_store.open_lots()
    assert sum(lot.remaining_quantity for lot in lots) == 5
    assert len({lot.execution_id for lot in lots}) == 2
    assert vssf.account.positions[identity.instrument_id]["qty"] == 5
    # Pre-close quantity disagreement is not reconciled by a position guess.
    close_conflict_broker, close_conflict_ledger = recovery_snapshots(
        broker_quantity=Decimal("-4"), ledger_quantity=Decimal("-5"),
        pending_ids=(), suffix="PRECLOSE-QUANTITY-CONFLICT",
    )
    close_conflict = recovery.recover(
        group_id=plan.group_id, broker_snapshot=close_conflict_broker,
        ledger_snapshot=close_conflict_ledger,
    )
    assert close_conflict.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert close_conflict.restore_allowed is False
    assert vssf.metrics["order_commands"] == 1

    import json
    from collections import defaultdict
    from application.composition.track2_u19_recovery import (
        ValidationOnlyTrack2U19RecoveryCoordinator,
    )
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot,
        U19ExecutionEvent,
        U19ExecutionLedgerSnapshot,
        U19Position,
    )
    from environments.virtual.position.track2_u19_recovery_store import (
        SqliteTrack2U19RecoveryStore,
    )

    account_position = vssf.account.positions[identity.instrument_id]
    account_quantity = Decimal(str(account_position["qty"]))
    account_signed = account_quantity if str(account_position["side"]).upper() == "BUY" else -account_quantity
    broker_positions = (U19Position(identity.instrument_id, account_signed),)
    signed_by_instrument = defaultdict(Decimal)
    for lot in lots:
        signed_by_instrument[lot.instrument_id] += (
            Decimal(lot.remaining_quantity)
            if str(lot.side).upper() == "BUY"
            else -Decimal(lot.remaining_quantity)
        )
    ledger_positions = tuple(
        U19Position(instrument_id, quantity)
        for instrument_id, quantity in sorted(signed_by_instrument.items())
    )
    assert broker_positions == ledger_positions
    execution_events = tuple(
        U19ExecutionEvent(
            fill.execution_id,
            sha256(
                f"{fill.execution_id}|{fill.filled_quantity}|{fill.execution_price}|{fill.execution_timestamp}".encode()
            ).hexdigest(),
        )
        for fill in latest.execution_fills
    )
    as_of = max(fill.execution_timestamp for fill in latest.execution_fills).replace(
        tzinfo=timezone(timedelta(hours=9))
    ) + timedelta(seconds=1)
    broker_payload = {
        "group_id": plan.group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in broker_positions],
    }
    ledger_payload = {
        "group_id": plan.group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in ledger_positions],
        "execution_events": [(event.execution_id, event.fingerprint) for event in execution_events],
    }
    digest = lambda value: sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    checkpoint = tmp_path / "s4-mini-u19.sqlite3"
    first_decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint)
    ).recover(
        group_id=plan.group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=plan.group_id, snapshot_id="S4-U19-BROKER-INITIAL", as_of=as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE", positions=broker_positions,
            complete=True, capability_verified=True, payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=plan.group_id, snapshot_id="S4-U19-LEDGER-INITIAL", as_of=as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER", positions=ledger_positions,
            complete=True, payload_sha256=digest(ledger_payload), execution_events=execution_events,
        ),
    )
    assert first_decision.restore_allowed is True, first_decision.__dict__
    assert first_decision.new_entry_enabled is False
    assert first_decision.order_submission_enabled is False
    persisted = SqliteTrack2U19RecoveryStore(checkpoint).load_latest(plan.group_id)
    assert persisted is not None
    assert len(persisted["execution_events"]) == 2

    before_lots = bridge.position_lot_store.history()
    before_fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    reopened_decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint)
    ).recover(
        group_id=plan.group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=plan.group_id, snapshot_id="S4-U19-BROKER-REOPEN", as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:BROKER_EXCHANGE", positions=broker_positions,
            complete=True, capability_verified=True, payload_sha256=digest(broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=plan.group_id, snapshot_id="S4-U19-LEDGER-REOPEN", as_of=as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:EXECUTION_LEDGER", positions=ledger_positions,
            complete=True, payload_sha256=digest(ledger_payload),
            execution_events=execution_events + execution_events,
        ),
    )
    assert reopened_decision.restore_allowed is True
    assert len(reopened_decision.execution_events) == 2
    assert bridge.position_lot_store.history() == before_lots
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == before_fees

    monkeypatch.setattr(vssf, "_execute", original_execute)
    assert len(lots) == 2
    expected_open_quantity = sum(lot.remaining_quantity for lot in lots)
    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track4_gamma_scalping",
        purpose="S4_VALIDATION_LATE_FILL_CLOSE",
        asset_type="FUTURES",
    )
    assert len(close_plan.legs) == 1
    assert close_plan.legs[0].quantity == expected_open_quantity == 5
    assert close_plan.legs[0].side == "BUY"
    closed = bridge.execute(close_plan)
    assert closed.filled_legs == 5
    assert closed.group_complete is True
    assert bridge.position_lot_store.open_lots() == ()
    assert identity.instrument_id not in vssf.account.positions
    assert closed.position_flat is True

@pytest.mark.parametrize(
    ("freshness_status", "symbol_mismatch"),
    [
        (FreshnessStatus.STALE, False),
        (FreshnessStatus.UNKNOWN, False),
        (FreshnessStatus.CAPABILITY_CONFLICT, False),
        (FreshnessStatus.FRESH, True),
    ],
)
def test_track4_mini_futures_rejects_stale_unknown_conflicting_or_mismatched_freshness_before_route(
    freshness_status, symbol_mismatch
) -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-FRESHNESS-FAULT")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)
    observed_at = datetime.fromisoformat(tick.timestamp)

    def fault_freshness(_plan, _leg, _identity, command):
        return FreshnessVerdict(
            status=freshness_status,
            reason=f"S4_SYNTHETIC_FRESHNESS_{freshness_status.value}",
            policy_version="S4-MINI-FRESHNESS-FAULT-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=(
                "SYNTHETIC_CONTRACT:INTENTIONALLY_MISMATCHED"
                if symbol_mismatch else command.broker_symbol
            ),
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{freshness_status.value}|{command.instrument_id}|{symbol_mismatch}".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = fault_freshness
    before_commands = vssf.metrics["order_commands"]
    result = bridge.execute(plan)

    assert result.routed_legs == 0
    assert result.filled_legs == 0
    assert result.reports[0].status == "REJECTED"
    assert "MARKET_DATA_FRESHNESS" in (result.reports[0].rejected_reason or "")
    assert vssf.metrics["order_commands"] == before_commands == 0
    assert bridge.position_lot_store.open_lots() == ()
    assert identity.instrument_id not in vssf.account.positions


def test_track4_mini_futures_rejects_missing_freshness_verdict_before_route() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-MISSING-FRESHNESS")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)
    bridge.freshness_verdict_provider = None
    result = bridge.execute(plan)
    assert result.routed_legs == 0
    assert result.filled_legs == 0
    assert result.reports[0].status == "REJECTED"
    assert result.reports[0].rejected_reason == "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED"
    assert vssf.metrics["order_commands"] == 0
    assert bridge.position_lot_store.open_lots() == ()
    assert identity.instrument_id not in vssf.account.positions

@pytest.mark.parametrize(
    ("free_margin", "used_margin", "max_position", "max_daily_loss", "realized_pnl", "unrealized_pnl", "expected_rejection"),
    [
        (Decimal("249999999"), Decimal("0"), 100, Decimal("10000000"), Decimal("0"), Decimal("0"), "INSUFFICIENT_FREE_MARGIN"),
        (Decimal("250000000"), Decimal("0"), 100, Decimal("10000000"), Decimal("0"), Decimal("0"), None),
        (Decimal("250000000"), Decimal("600000000"), 100, Decimal("10000000"), Decimal("0"), Decimal("0"), None),
        (Decimal("250000000"), Decimal("600000001"), 100, Decimal("10000000"), Decimal("0"), Decimal("0"), "MAX_MARGIN_UTILIZATION"),
        (Decimal("250000000"), Decimal("0"), 4, Decimal("10000000"), Decimal("0"), Decimal("0"), "EXCEEDED_INSTRUMENT_LIMIT"),
        (Decimal("250000000"), Decimal("0"), 5, Decimal("10000000"), Decimal("0"), Decimal("0"), None),
        (Decimal("250000000"), Decimal("0"), 100, Decimal("1000"), Decimal("-999"), Decimal("0"), None),
        (Decimal("250000000"), Decimal("0"), 100, Decimal("1000"), Decimal("-1000"), Decimal("0"), "MAX_DAILY_LOSS"),
        (Decimal("250000000"), Decimal("0"), 100, Decimal("1000"), Decimal("0"), Decimal("-1000"), None),
        (Decimal("250000000"), Decimal("0"), 100, Decimal("1000"), Decimal("0"), Decimal("-1001"), None),
    ],
    ids=(
        "one-krw-below-required-margin",
        "exact-required-margin-boundary",
        "exact-configured-utilization-boundary",
        "one-krw-over-configured-utilization-boundary",
        "one-contract-over-synthetic-position-limit",
        "exact-synthetic-position-limit-boundary",
        "one-krw-below-synthetic-daily-loss-cap",
        "exact-synthetic-daily-loss-cap-boundary",
        "unrealized-loss-at-synthetic-daily-loss-cap-not-in-realized-preflight",
        "unrealized-loss-over-synthetic-daily-loss-cap-not-in-realized-preflight",
    ),
)
def test_track4_mini_futures_risk_preflight_boundaries(
    free_margin: Decimal, used_margin: Decimal, max_position: int,
    max_daily_loss: Decimal, realized_pnl: Decimal, unrealized_pnl: Decimal,
    expected_rejection: str | None,
) -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-MARGIN-PREFLIGHT-FAULT")
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    identity = plan.legs[0].instrument_identity
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)
    vssf.account.free_margin = free_margin
    vssf.account.used_margin = used_margin
    vssf.account.realized_pnl = realized_pnl
    vssf.account.unrealized_pnl = unrealized_pnl
    risk_engine = bridge.risk_gate.engine
    risk_config = type(risk_engine.config)(
        max_position_per_instrument=max_position,
        max_daily_loss_krw=max_daily_loss,
    )
    bridge.risk_gate.engine = type(risk_engine)(risk_config, margin_engine=risk_engine.margin_engine)
    observed_at = datetime.fromisoformat(tick.timestamp)

    def fresh_synthetic_evidence(_plan, _leg, _identity, command):
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_FRESHNESS_PASS",
            policy_version="S4-MINI-MARGIN-FAULT-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{command.instrument_id}|MARGIN".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = fresh_synthetic_evidence
    result = bridge.execute(plan)

    if expected_rejection is not None:
        assert result.routed_legs == 0
        assert result.filled_legs == 0
        assert result.reports[0].status == "REJECTED"
        rejection_text = (result.reports[0].rejected_reason or "").upper()
        if expected_rejection == "EXCEEDED_INSTRUMENT_LIMIT":
            assert "EXCEEDED_INSTRUMENT_LIMIT" in rejection_text
        elif expected_rejection == "MAX_MARGIN_UTILIZATION":
            assert "MARGIN_UTILIZATION" in rejection_text
        elif expected_rejection == "MAX_DAILY_LOSS":
            assert "MAX_DAILY_LOSS" in rejection_text
        else:
            assert expected_rejection in rejection_text
        assert vssf.metrics["order_commands"] == 0
        assert bridge.position_lot_store.open_lots() == ()
        assert identity.instrument_id not in vssf.account.positions
    else:
        assert result.routed_legs == 1
        assert result.filled_legs == 5
        assert result.reports[0].status == "FILLED"
        assert result.reports[0].filled_quantity == 5
        assert vssf.metrics["order_commands"] == 1
        assert sum(lot.remaining_quantity for lot in bridge.position_lot_store.open_lots()) == 5
        assert int(vssf.account.positions[identity.instrument_id]["qty"]) == 5


def test_track4_close_plan_scopes_open_lots_to_one_group_and_aggregates_actual_quantity() -> None:
    identity = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S4-MINI-CLOSE",
        symbol="SYNTHETIC_KOSPI200",
        product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )

    def lot(*, run_id, strategy_id, group_id, quantity, side="SELL"):
        return SimpleNamespace(
            run_id=run_id, strategy_id=strategy_id, group_id=group_id,
            remaining_quantity=quantity, instrument_identity=identity,
            instrument_id=identity.instrument_id, position_role="NONE", side=side,
        )

    lots = [
        lot(run_id="S4-CLOSE-GROUP-SCOPE", strategy_id="track4_gamma_scalping",
            group_id="S4-GROUP-A", quantity=2),
        lot(run_id="S4-CLOSE-GROUP-SCOPE", strategy_id="track4_gamma_scalping",
            group_id="S4-GROUP-A", quantity=3),
        lot(run_id="OTHER-RUN", strategy_id="track4_gamma_scalping",
            group_id="OTHER-RUN-GROUP", quantity=100),
        lot(run_id="S4-CLOSE-GROUP-SCOPE", strategy_id="other_strategy",
            group_id="OTHER-STRATEGY-GROUP", quantity=100),
    ]
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "S4-CLOSE-GROUP-SCOPE"
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: tuple(lots))

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track4_gamma_scalping",
        purpose="S4_VALIDATION_CLOSE_GROUP_SCOPE",
        asset_type="FUTURES",
    )
    assert plan.group_id == "S4-GROUP-A"
    assert len(plan.legs) == 1
    assert plan.legs[0].side == "BUY"
    assert plan.legs[0].quantity == 5

    lots.append(lot(
        run_id="S4-CLOSE-GROUP-SCOPE", strategy_id="track4_gamma_scalping",
        group_id="S4-GROUP-B", quantity=1,
    ))
    with pytest.raises(ValueError, match="AMBIGUOUS_OPEN_POSITION_GROUPS"):
        bridge.build_close_plan_from_open_lots(
            strategy_id="track4_gamma_scalping",
            purpose="S4_VALIDATION_CLOSE_AMBIGUOUS_GROUPS",
            asset_type="FUTURES",
        )


def test_track4_option_proposal_has_no_runtime_plan_resolver_route():
    """Characterize the current S4 boundary: option-entry proposals are not routed."""
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-SYNTHETIC-OPTION-ROUTE-BOUNDARY")
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        requested_price=Decimal("100"),
        side="BUY",
        track_id="track4_gamma_scalping",
        tag_id="S4_SYNTHETIC_OPTION_ENTRY_PROBE",
        option_type="CALL",
        strike=Decimal("500"),
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="BUY"),
        qty=1,
        tag_id=proposal.tag_id,
        track_id="track4_gamma_scalping",
    )

    assert loop.multi_leg_plan_resolver(evaluation, canonical) is None
    assert loop.multi_leg_bridge.position_lot_store.open_lots() == ()


def test_track4_strategy_emits_futures_hedge_without_owned_option_lot_evidence() -> None:
    strategy = Track4GammaScalping(enabled=True, capital_gate_min=Decimal("1"), risk_limits_available=True)
    data = Track4MarketInput(
        observed_at=datetime(2026, 11, 23, 9, 0, tzinfo=timezone(timedelta(hours=9))),
        current_price=Decimal("350"),
        active_vol=Decimal("0.20"),
        base_vol=Decimal("0.20"),
        time_str="09:00",
        current_delta=Decimal("0.8"),
        current_gamma=Decimal("0.1"),
        current_pnl=Decimal("0"),
        current_equity=Decimal("1000000"),
        price_history=(Decimal("350"), Decimal("351")),
        max_hedge_qty=5,
    )

    basecamp = strategy.evaluate_basecamp(
        data, active_vol=Decimal("0.10"), base_vol=Decimal("0.20")
    )
    assert len(basecamp) == 1
    assert basecamp[0].kind == "NON_EXECUTION"
    assert basecamp[0].execution_proposal is None
    assert basecamp[0].non_execution_event is not None

    # Track4MarketInput carries aggregate Greek values but no owned option lots,
    # Option Master identity, or fill lineage. This helper still emits a Futures
    # proposal; this is a validation finding, not an approved operating contract.
    hedge = strategy.evaluate_delta_hedge(
        data,
        delta=Decimal("0.8"),
        deadband=Decimal("0.1"),
        equity=Decimal("1000000"),
        max_hedge_qty=5,
    )
    assert len(hedge) == 1
    assert hedge[0].execution_proposal is not None
    assert hedge[0].execution_proposal.asset_type == "FUTURES"
    assert hedge[0].execution_proposal.proposed_quantity > 0

def test_s4_repeated_same_hedge_intent_reuses_bridge_client_order_id_across_ticks() -> None:
    """Characterize the existing Bridge ID scope; do not infer retry/attempt policy."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "track4"
        / "synthetic_s4_repeated_hedge_intent_client_order_id_reuse_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["validation_only"] is True
    assert fixture["runtime_use"] == "PROHIBITED_OUTSIDE_VALIDATION"
    scenario = fixture["scenario"]

    loop = _loop(
        (scenario["strategy_id"], "1.0"),
        scenario["run_id"],
    )
    bridge = loop.multi_leg_bridge
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")

    def build_request(timestamp: str):
        tick = SimpleNamespace(
            underlying_symbol="SYNTHETIC_KOSPI200",
            symbol="SYNTHETIC_KOSPI200",
            instrument_id="SYNTHETIC_KOSPI200",
            timestamp=timestamp,
        )
        proposal = StrategyExecutionProposal(
            proposed_quantity=int(scenario["quantity"]),
            asset_type="FUTURES",
            requested_price=None,
            side=scenario["side"],
            track_id=scenario["strategy_id"],
            tag_id=scenario["tag_id"],
            option_type=None,
            strike=None,
        )
        evaluation = SimpleNamespace(
            context=SimpleNamespace(
                strategy_id=scenario["strategy_id"],
                market_state=SimpleNamespace(ticks={"synthetic": tick}),
            ),
            result=SimpleNamespace(execution_proposal=proposal),
        )
        canonical = SimpleNamespace(
            side=SimpleNamespace(value=scenario["side"]),
            qty=int(scenario["quantity"]),
            tag_id=scenario["tag_id"],
            track_id=scenario["strategy_id"],
        )
        return tick, loop.multi_leg_plan_resolver(evaluation, canonical)

    first_tick, first_plan = build_request(scenario["first_tick_timestamp"])
    second_tick, second_plan = build_request(scenario["second_tick_timestamp"])
    assert first_plan is not None and second_plan is not None
    assert first_plan.group_id == second_plan.group_id == (
        f'{scenario["run_id"]}-{scenario["strategy_id"]}-FUTURES-HEDGE'
    )
    assert first_plan.legs[0].leg_id == second_plan.legs[0].leg_id == "futures-gamma_rebalance"
    assert first_plan.attempt_id is None
    assert second_plan.attempt_id is None

    identity = first_plan.legs[0].instrument_identity
    assert identity is not None
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == Decimal(scenario["contract_multiplier"])
    assert identity.identity_source == scenario["identity_source"]
    assert second_plan.legs[0].instrument_identity == identity

    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(first_tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_REPEATED_HEDGE_INTENT",
            policy_version="S4-REPEATED-HEDGE-INTENT-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|S4-REPEAT".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    first = bridge.execute(first_plan)
    assert first.group_complete is True
    assert first.reports[0].status == "FILLED"
    first_report = first.reports[0]
    first_client_order_id = first_report.client_order_id
    assert first_report.group_id == first_plan.group_id
    assert first_report.leg_id == first_plan.legs[0].leg_id

    # The second tick differs, but the plan's stable fields and Bridge ID inputs do not.
    assert first_tick.timestamp != second_tick.timestamp
    before_second_submission = vssf.metrics["order_commands"]
    second = bridge.execute(second_plan)

    assert second.reports[0].client_order_id == first_client_order_id
    assert second.reports[0].execution_id == first_report.execution_id
    assert second.reports[0].status == "FILLED"
    assert vssf.metrics["order_commands"] == before_second_submission == 1
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert sum(lot.remaining_quantity for lot in bridge.position_lot_store.open_lots()) == int(scenario["quantity"])
    assert vssf.account.positions[identity.instrument_id]["qty"] == int(scenario["quantity"])
    assert fixture["expected_observations"]["same_intent_at_distinct_ticks_reuses_client_order_id"] is True
    assert fixture["expected_observations"]["no_attempt_identity_or_retry_policy_is_inferred"] is True

    # A caller-supplied non-empty attempt_id participates in the Bridge ID digest.
    # This pure probe does not execute another order or define who owns the ID.
    from dataclasses import replace

    first_explicit_attempt = replace(
        first_plan, attempt_id=scenario["first_explicit_attempt_id"]
    )
    same_explicit_attempt_next_tick = replace(
        second_plan, attempt_id=scenario["first_explicit_attempt_id"]
    )
    second_explicit_attempt = replace(
        second_plan, attempt_id=scenario["second_explicit_attempt_id"]
    )
    first_attempt_id = bridge._client_order_id(
        first_explicit_attempt, first_explicit_attempt.legs[0], identity
    )
    same_attempt_next_tick_id = bridge._client_order_id(
        same_explicit_attempt_next_tick,
        same_explicit_attempt_next_tick.legs[0],
        identity,
    )
    second_attempt_id = bridge._client_order_id(
        second_explicit_attempt, second_explicit_attempt.legs[0], identity
    )
    assert first_attempt_id == same_attempt_next_tick_id
    assert first_attempt_id != first_client_order_id
    assert second_attempt_id != first_attempt_id
    assert vssf.metrics["order_commands"] == 1
    assert fixture["expected_observations"][
        "same_attempt_id_preserves_bridge_client_order_id_across_ticks"
    ] is True
    assert fixture["expected_observations"][
        "distinct_nonempty_attempt_ids_change_bridge_client_order_id"
    ] is True
    assert fixture["expected_observations"][
        "attempt_id_probe_is_pure_and_does_not_submit_orders"
    ] is True



def test_track4_filled_report_bridge_projection_failure_ack_boundary(monkeypatch) -> None:
    import json
    from pathlib import Path

    from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter

    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures" / "track4"
        / "synthetic_s4_bridge_projection_failure_ack_boundary_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["validation_only"] is True
    assert fixture["runtime_use"] == "PROHIBITED_OUTSIDE_VALIDATION"
    scenario = fixture["scenario"]

    loop = _loop(("track4_gamma_scalping", "1.0"), scenario["run_id"])
    bridge = loop.multi_leg_bridge
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp=scenario["timestamp"],
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=int(scenario["quantity"]),
        asset_type="FUTURES",
        requested_price=None,
        side=scenario["side"],
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        signal_id="SIG-1-track4_gamma_scalping-1",
        side=SimpleNamespace(value=scenario["side"]),
        qty=int(scenario["quantity"]),
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    plan = loop.multi_leg_plan_resolver(evaluation, canonical)
    assert plan is not None
    assert plan.attempt_id is None
    assert plan.group_id == f"{bridge.run_id}-track4_gamma_scalping-FUTURES-HEDGE"

    # Runtime signal identity changes with tick sequence, but the current S4
    # resolver does not propagate it into attempt_id or the stable hedge group.
    next_tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:50+09:00",
    )
    next_evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": next_tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    next_canonical = SimpleNamespace(
        signal_id="SIG-2-track4_gamma_scalping-1",
        side=SimpleNamespace(value=scenario["side"]),
        qty=int(scenario["quantity"]),
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )
    next_plan = loop.multi_leg_plan_resolver(next_evaluation, next_canonical)
    assert next_plan is not None
    assert next_plan.attempt_id is None
    assert next_plan.group_id == plan.group_id
    identity = plan.legs[0].instrument_identity
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == Decimal(50000)

    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    price = Decimal(str(scenario["price"]))
    bridge.bundle.market._futures_price = price
    vssf.order_book.update_bid_ask(float(price), float(price), identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(scenario["timestamp"])
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_DERIVED_SCENARIO",
            policy_version="S4-BRIDGE-PROJECTION-ACK-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|ACK-BOUNDARY".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    callbacks = []
    bridge.execution_result_callback = lambda received_plan, result: callbacks.append(
        (received_plan, result)
    )

    def fail_bridge_aggregate_projection(_adapter, _command, _report):
        raise RuntimeError("S4_SYNTHETIC_BRIDGE_AGGREGATE_PROJECTION_FAILURE")

    monkeypatch.setattr(VirtualPositionFillAdapter, "apply", fail_bridge_aggregate_projection)
    with pytest.raises(RuntimeError, match="S4_SYNTHETIC_BRIDGE_AGGREGATE_PROJECTION_FAILURE"):
        bridge.execute(plan)

    client_order_id = bridge._client_order_id(plan, plan.legs[0], identity)
    broker_report = bridge.ack.broker.query(client_order_id)
    assert broker_report is not None
    assert broker_report.status == "FILLED"
    assert broker_report.execution_id

    # VSSF account, PositionLot and FeeLedger have already applied before the
    # Bridge aggregate/fingerprint/provenance publication failure.
    account_position = vssf.account.positions[identity.instrument_id]
    assert int(account_position["qty"]) == int(scenario["quantity"])
    assert str(account_position["side"]).upper() == scenario["side"]
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].execution_id == broker_report.execution_id
    assert lots[0].remaining_quantity == int(scenario["quantity"])
    fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    assert len(fees) == 1
    assert fees[0].execution_id == broker_report.execution_id

    # The FILLED report was removed from pending before projection. The normal
    # callback/group publication and Bridge identity indexes were not reached.
    assert client_order_id not in bridge.pending_legs
    assert client_order_id not in bridge._pending_attempt_ids
    assert bridge.groups.get(plan.group_id) is None
    assert broker_report.execution_id not in bridge._applied_execution_fingerprints
    assert broker_report.execution_id not in bridge.execution_legs
    assert broker_report.execution_id not in bridge.provenance
    assert callbacks == []

    # A deliberate same-process whole-bridge re-entry is different from an
    # automatic retry owner. The VSSF duplicate submit raises after observing
    # zero remaining quantity; _AckAdapter then queries the prior FILLED report.
    # Bridge replay dedupes the already-applied PositionLot/Fee records and
    # completes the previously interrupted in-memory projection.
    executions_before = vssf.metrics["executions_issued"]
    monkeypatch.undo()
    replay_result = bridge.execute(plan)

    assert replay_result.filled_legs == int(scenario["quantity"])
    assert replay_result.group_complete is True
    assert vssf.metrics["executions_issued"] == executions_before == 1
    assert int(vssf.account.positions[identity.instrument_id]["qty"]) == int(scenario["quantity"])
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 1
    assert broker_report.execution_id in bridge._applied_execution_fingerprints
    assert broker_report.execution_id in bridge.execution_legs
    assert broker_report.execution_id in bridge.provenance
    assert len(callbacks) == 1
