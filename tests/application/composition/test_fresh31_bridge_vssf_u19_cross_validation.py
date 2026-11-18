from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from application.composition.validation_only_runtime_ledger_comparator import ValidationOnlyRuntimeLedgerComparator
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19Position,
    U19RecoveryStatus,
)
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import (
    SyntheticRuntimeSources,
    build_synthetic_option_master,
)
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


ACCEPTED_DATASET = Path("data/accepted_market_data/runtime_v2")


def _build_fixture_dataset(tmp_path):
    source_manifest_path = ACCEPTED_DATASET / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_row = next(
        json.loads(line)
        for line in (ACCEPTED_DATASET / "20261012.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    source_tick = source_row["tick"]
    source_ref = str(source_row.get("scenario_metadata", {}).get("source_observation_id") or "accepted-runtime-v2")
    synthetic_id = "SYNTHETIC_CONTRACT:FRESH31:" + sha256(source_ref.encode("utf-8")).hexdigest()[:24]
    tick = {
        "timestamp": source_tick["timestamp"],
        "underlying_price": source_tick.get("underlying_price"),
        "underlying_symbol": source_tick.get("underlying_symbol", "KOSPI200"),
        "underlying_observed_hour": source_tick.get("underlying_observed_hour", ""),
        "underlying_source": source_tick.get("underlying_source", "ACCEPTED_SOURCE_ANCHOR"),
        "strike_price": source_tick["strike_price"],
        "option_type": source_tick["option_type"],
        "contract_multiplier": 1.0,
        "bid_price": source_tick["bid_price"],
        "ask_price": source_tick["ask_price"],
        "last_price": source_tick["last_price"],
        "volume": source_tick.get("volume", 1),
        "bid_quantity": 1,
        "ask_quantity": 1,
        "seq_id": 1,
        "expiry": source_tick["expiry"],
        "symbol": synthetic_id,
        "option_observed_hour": source_tick.get("option_observed_hour", ""),
        "option_source": "SYNTHETIC:DERIVED_SCENARIO",
        "instrument_id": None,
        "synthetic_contract_id": synthetic_id,
        "source_instrument_code": str(source_tick.get("source_instrument_code") or source_tick.get("instrument_id") or ""),
        "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "contract_class": source_tick.get("contract_class", "monthly"),
        "contract_month": source_tick.get("contract_month", "202611"),
    }
    record = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "tick": tick,
        "scenario_metadata": {
            "validation_only": True,
            "scenario_id": "FRESH31_BRIDGE_VSSF_U19",
            "regime": "NORMAL",
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "source_anchor_ref": source_ref,
            "source_anchor_timestamp": source_tick["timestamp"],
            "scenario_timestamp": source_tick["timestamp"],
            "generated_fields": ["synthetic_contract_id", "contract_multiplier", "bid_quantity", "ask_quantity"],
            "field_provenance": {
                "bid_price": "ACCEPTED_RUNTIME_V2_SOURCE_ANCHOR",
                "ask_price": "ACCEPTED_RUNTIME_V2_SOURCE_ANCHOR",
                "last_price": "ACCEPTED_RUNTIME_V2_SOURCE_ANCHOR",
                "contract_multiplier": "DETERMINISTIC_SYNTHETIC_FIXTURE_ASSUMPTION_1",
                "depth": "DETERMINISTIC_SYNTHETIC_FIXTURE_QUANTITY_1",
            },
        },
    }
    root = tmp_path / "fresh31_market_fixture"
    root.mkdir()
    data_path = root / "20261012.jsonl"
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    data_path.write_bytes(payload)
    manifest = {
        "schema": "reference-canonical-market-tick-v1",
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "identity_policy": {
            "mode": "SYNTHETIC_ONLY",
            "synthetic_contract_id_namespace": "SYNTHETIC_CONTRACT:",
            "production_standard_instrument_id_assigned": False,
        },
        "scenario_id": "FRESH31_BRIDGE_VSSF_U19",
        "scenario_regimes": {"FRESH31_BRIDGE_VSSF_U19": "NORMAL"},
        "trading_calendar": {
            "source_type": "SYNTHETIC", "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": [
                day.isoformat()
                for day in (
                    datetime.strptime(source_tick["timestamp"][:10], "%Y-%m-%d").date()
                    + timedelta(days=offset)
                    for offset in range(40)
                )
                if day.weekday() < 5
                and day <= datetime.strptime(source_tick["expiry"], "%Y%m%d").date()
            ],
        },
        "source_registry_id": source_manifest["registry_id"],
        "source_manifest_sha256": sha256(source_manifest_path.read_bytes()).hexdigest(),
        "source_anchor_ref": source_ref,
        "source_anchor_timestamp": source_tick["timestamp"],
        "scenario_timestamp": source_tick["timestamp"],
        "deterministic_rule_id": "FRESH31-ACCEPTED-ANCHOR-SYNTHETIC-IDENTITY-v1",
        "generated_fields": record["scenario_metadata"]["generated_fields"],
        "output_sha256": sha256(payload).hexdigest(),
        "output_bytes": len(payload),
        "rows": 1,
        "execution_enabled": False,
        "order_submission_enabled": False,
        "live_api_enabled": False,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    return root, manifest, source_ref

def _identity(tick, master):
    item = master.get_contract_identity(tick.instrument_id)
    assert item is not None
    return OptionInstrumentIdentity(
        item.shrn_iscd, item.shrn_iscd, item.expiry, item.option_type,
        Decimal(str(item.strike)), Decimal(str(item.contract_multiplier)),
        "DERIVED_SCENARIO_TEST_FIXTURE",
    )


def _digest(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(body.encode("utf-8")).hexdigest()


def test_actual_bridge_partial_fills_partial_and_full_close_reconcile_with_vssf_and_u19(tmp_path):
    assert ACCEPTED_DATASET.exists(), "accepted runtime-v2 source must be present"
    dataset, _fixture_manifest, source_ref = _build_fixture_dataset(tmp_path)
    adapter = SyntheticReplayAdapter(dataset)
    master = build_synthetic_option_master(dataset, validation_only_adapter=adapter)
    tick = next(HighSpeedReplayRunner(dataset, synthetic_adapter=adapter).events())
    assert str(tick.option_type).upper() == "CALL"
    assert Decimal(str(tick.bid_price)) > Decimal("1")
    assert Decimal(str(tick.ask_price)) > Decimal(str(tick.bid_price))
    identity = _identity(tick, master)
    limit_price = Decimal(str(tick.bid_price)) - Decimal("1.00")
    assert limit_price > 0

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="Q25-A8-FRESH31-BRIDGE-VSSF-U19",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="FRESH31_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-A8-FRESH31-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=_digest({
                "timestamp": observed.isoformat(),
                "instrument_id": command.instrument_id,
                "rule": "FRESH31",
            }),
        )

    bridge.freshness_verdict_provider = freshness
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    group_id = "FRESH31-BRIDGE-GROUP"
    strategy_id = "track8_macro_regime_monthly_strangle"
    entry_plan = MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose="MONTHLY_STRANGLE_ENTRY_CALL",
        legs=(ExecutionLeg(
            "entry-call", "BUY", 4, option_type="CALL",
            strike=identity.strike, requested_price=limit_price,
            instrument_identity=identity,
        ),),
    )
    initial = bridge.execute(entry_plan)
    assert initial.routed_legs == 1
    assert initial.pending_legs == 1
    assert initial.reports[0].status == "NEW"

    client_order_id = initial.reports[0].client_order_id
    broker_command = bridge.pending_legs[client_order_id][2]
    fill_command = type("FillCommand", (), {
        **broker_command.__dict__,
        "option_type": identity.option_type,
        "strike": float(identity.strike),
        "expiry": identity.expiry,
        "contract_multiplier": identity.contract_multiplier,
        "identity_source": identity.identity_source,
        "symbol": identity.instrument_id,
    })()
    fill_base = vssf._now()
    for quantity, price, offset in (
        (1, float(limit_price), 1),
        (2, float(limit_price + Decimal("0.01")), 2),
    ):
        execution = vssf.execution_engine.execute_order(
            fill_command, price, quantity,
            timestamp=fill_base + timedelta(seconds=offset),
        )
        vssf.account.apply_execution(execution)

    partial = bridge.process_pending_quotes()
    assert len(partial) == 1
    assert partial[0].reports[0].status == "PARTIALLY_FILLED"
    assert partial[0].reports[0].filled_quantity == 3
    assert len(bridge.position_lot_store.open_lots()) == 2
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 2

    vssf.order_book.update_bid_ask(
        float(limit_price - Decimal("0.01")), float(limit_price), identity.instrument_id
    )
    vssf.clock.sleep_policy(3)
    vssf.process_pending_orders()
    terminal_entry = bridge.process_pending_quotes()
    assert len(terminal_entry) == 1
    assert terminal_entry[0].reports[0].status == "FILLED"
    assert terminal_entry[0].reports[0].filled_quantity == 4
    assert len(bridge.position_lot_store.history()) == 3
    assert bridge.leg_positions[identity.instrument_id].qty == 4
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 3

    partial_close_base = bridge.build_close_plan_from_open_lots(
        strategy_id=strategy_id, purpose="FRESH31_PARTIAL_CLOSE",
        asset_type="OPTION", leg_id_prefix="FRESH31-PARTIAL",
    )
    partial_close_leg = replace(partial_close_base.legs[0], quantity=1)
    partial_close_plan = replace(partial_close_base, legs=(partial_close_leg,))
    partial_close = bridge.execute(partial_close_plan, group_plan=entry_plan)
    assert partial_close.filled_legs == 1
    assert partial_close.reports[0].filled_quantity == 1
    assert sum(lot.remaining_quantity for lot in bridge.position_lot_store.open_lots()) == 3
    assert sum(event.quantity for event in bridge.position_lot_store.close_events()) == 1

    final_close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id=strategy_id, purpose="FRESH31_TERMINAL_CLOSE",
        asset_type="OPTION", leg_id_prefix="FRESH31-REST",
    )
    final_close = bridge.execute(final_close_plan, group_plan=entry_plan)
    assert final_close.filled_legs == 3
    assert bridge.position_lot_store.open_lots() == ()
    assert sum(event.quantity for event in bridge.position_lot_store.close_events()) == 4
    assert bridge.pending_legs == {}
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0")

    # Read the actual VSSF aggregate after the bridge's execution path has closed all lots.
    vssf.account.unrealized_pnl = vssf.account.pnl_engine.calculate_unrealized(
        vssf.account.positions, Decimal("1")
    )
    assert vssf.account.positions == {}

    # Build independent fill evidence from the Bridge's canonical execution reports.
    fills_by_id = {}
    for report in bridge.group_reports(group_id):
        fill_rows = tuple(getattr(report, "execution_fills", ()) or ())
        if not fill_rows and report.execution_id and report.filled_quantity > 0:
            fill_rows = (report,)
        for fill in fill_rows:
            execution_id = str(getattr(fill, "execution_id", None) or getattr(fill, "exec_id", ""))
            if not execution_id:
                continue
            meta = bridge.execution_legs[execution_id]
            provenance = bridge.provenance[execution_id]
            fills_by_id[execution_id] = {
                "execution_id": execution_id,
                "instrument_id": provenance["instrument_id"],
                "side": meta["side"],
                "quantity": int(getattr(fill, "filled_quantity", getattr(fill, "executed_qty", 0))),
                "price": str(getattr(fill, "execution_price", getattr(fill, "executed_price", 0))),
                "contract_multiplier": str(meta["contract_multiplier"]),
                "executed_at": getattr(fill, "execution_timestamp", None)
                    or datetime.fromisoformat(fill.timestamp),
                "fee": str(getattr(fill, "fee", 0) or 0),
                "client_order_id": report.client_order_id,
                "strategy_id": provenance["strategy_id"],
                "group_id": provenance["group_id"],
                "leg_id": provenance["leg_id"],
            }

    executions = sorted(
        fills_by_id.values(), key=lambda row: (row["executed_at"], row["execution_id"])
    )
    assert len(executions) == 5  # three entry partials plus two close executions
    fee_records = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    expected_fees = [{
        "execution_id": row["execution_id"],
        "fee_amount": row["fee"],
        "quantity": row["quantity"],
        "price": row["price"],
        "run_id": bridge.run_id,
        "client_order_id": row["client_order_id"],
        "instrument_id": row["instrument_id"],
        "strategy_id": row["strategy_id"],
        "group_id": row["group_id"],
        "leg_id": row["leg_id"],
        "executed_at": row["executed_at"],
        "source": "VSSF:CanonicalExecutionReport.fee",
    } for row in executions]

    comparison = ValidationOnlyRuntimeLedgerComparator().compare(
        opening_lots=(),
        executions=executions,
        expected_fee_records=expected_fees,
        actual_position_lot_history=bridge.position_lot_store.history(),
        actual_open_position_lots=bridge.position_lot_store.open_lots(),
        actual_close_events=bridge.position_lot_store.close_events(),
        actual_fee_records=fee_records,
        vssf_positions=vssf.account.positions,
        vssf_realized_pnl_delta=vssf.account.realized_pnl,
        vssf_unrealized_pnl=vssf.account.unrealized_pnl,
        mark_prices={},
        source_namespace="SYNTHETIC:FRESH31",
        deterministic_rule_id="BRIDGE-VSSF-U19-CROSSCHECK-v1",
        source_manifest_sha256=sha256((dataset / "manifest.json").read_bytes()).hexdigest(),
        source_anchor_refs=(f"ACCEPTED_RUNTIME_V2:{source_ref}",),
        source_anchor_as_of=datetime.fromisoformat(tick.timestamp),
        scenario_timestamp=max(row["executed_at"] for row in executions) + timedelta(seconds=1),
        evidence_refs=("TEST:VIRTUALMULTILEG_BRIDGE", "TEST:VSSF_ACCOUNT", "TEST:U19"),
    )
    assert comparison.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED", comparison.issues
    assert comparison.manifest["expected_close_events"] == 3
    assert Decimal(comparison.manifest["expected_fee_total"]) == Decimal(comparison.manifest["actual_fee_total"])

    # U19 receives independent broker-proxy and execution-ledger snapshots from this same synthetic run.
    signed = {}
    events = []
    for row in executions:
        signed[row["instrument_id"]] = signed.get(row["instrument_id"], 0) + (
            row["quantity"] if row["side"] == "BUY" else -row["quantity"]
        )
        fingerprint = _digest({
            key: row[key] for key in (
                "execution_id", "client_order_id", "instrument_id", "side",
                "quantity", "price", "contract_multiplier", "executed_at",
                "group_id", "leg_id", "fee",
            )
        })
        events.append(U19ExecutionEvent(row["execution_id"], fingerprint))
    ledger_positions = tuple(
        U19Position(instrument, Decimal(quantity))
        for instrument, quantity in sorted(signed.items()) if quantity
    )
    broker_positions = tuple(
        U19Position(instrument, Decimal(str(position["qty"])))
        for instrument, position in sorted(vssf.account.positions.items())
        if Decimal(str(position["qty"])) != 0
    )
    as_of = max(row["executed_at"] for row in executions) + timedelta(seconds=2)
    broker_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in broker_positions],
    }
    ledger_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in ledger_positions],
        "execution_events": [(item.execution_id, item.fingerprint) for item in events],
        "pending_order_ids": [],
    }
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=group_id, snapshot_id="FRESH31-BROKER-PROXY",
        as_of=as_of, source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=broker_positions, complete=True, capability_verified=True,
        payload_sha256=_digest(broker_payload),
    )
    from core.oms.track2_u19_recovery import U19ExecutionLedgerSnapshot
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        group_id=group_id, snapshot_id="FRESH31-EXECUTION-LEDGER",
        as_of=as_of, source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=ledger_positions, complete=True,
        payload_sha256=_digest(ledger_payload),
        execution_events=tuple(events), pending_order_ids=(),
    )
    checkpoint_path = tmp_path / "fresh31-u19.sqlite3"
    decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=group_id, broker_snapshot=broker_snapshot,
        ledger_snapshot=ledger_snapshot,
    )
    assert decision.status is U19RecoveryStatus.FLAT_CONFIRMED
    assert decision.positions == ()
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    persisted = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)
    assert persisted["status"] == U19RecoveryStatus.FLAT_CONFIRMED.value
    assert persisted["execution_events"] and len(persisted["execution_events"]) == 5

def test_cancel_race_late_fill_replay_and_conflict_reconcile_bridge_vssf_u19(tmp_path):
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot,
        U19ExecutionLedgerSnapshot,
    )
    import pytest

    assert ACCEPTED_DATASET.exists(), "accepted runtime-v2 source must be present"
    dataset, _fixture_manifest, source_ref = _build_fixture_dataset(tmp_path)
    adapter = SyntheticReplayAdapter(dataset)
    master = build_synthetic_option_master(dataset, validation_only_adapter=adapter)
    tick = next(HighSpeedReplayRunner(dataset, synthetic_adapter=adapter).events())
    identity = _identity(tick, master)
    limit_price = Decimal(str(tick.bid_price)) - Decimal("1.00")
    assert limit_price > 0

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(("TRACK1_TAIL_DEFENSE", "1.2.0"),),
        run_id="Q25-A8-FRESH32-CANCEL-LATE-FILL",
        synthetic_runtime_sources=sources, track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="FRESH32_SYNTHETIC_FIXTURE_ONLY",
            policy_version="Q25-A8-FRESH32-v1",
            source="DERIVED_SCENARIO_TEST_FIXTURE",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed,
            received_at=observed,
            evidence_sha256=_digest({
                "timestamp": observed.isoformat(),
                "instrument_id": command.instrument_id,
                "rule": "FRESH32",
            }),
        )

    bridge.freshness_verdict_provider = freshness
    _publish_contract_scoped_replay_quote(
        tick, option_master=master, market=bootstrap.bundle.market,
        order_book=vssf.order_book,
    )
    sources.set_tick(tick)
    bootstrap.bundle.market.publish_replay_tick(tick)

    group_id = "FRESH32-CANCEL-LATE-FILL-GROUP"
    strategy_id = "track8_macro_regime_monthly_strangle"
    plan = MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose="FRESH32_CANCEL_LATE_FILL_RECONCILIATION",
        legs=(ExecutionLeg(
            "late-fill-call", "BUY", 2, option_type="CALL",
            strike=identity.strike, requested_price=limit_price,
            instrument_identity=identity,
        ),),
    )
    submitted = bridge.execute(plan)
    assert submitted.pending_legs == 1
    assert submitted.reports[0].status == "NEW"
    client_order_id = submitted.reports[0].client_order_id
    broker_command = bridge.pending_legs[client_order_id][2]
    assert vssf.order_book.get_pending_order(client_order_id) is not None

    anchor = datetime.fromisoformat(tick.timestamp)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    recovery_store = SqliteTrack2U19RecoveryStore(tmp_path / "fresh32-u19.sqlite3")
    recovery = ValidationOnlyTrack2U19RecoveryCoordinator(recovery_store)

    pending_broker = U19BrokerPositionSnapshot(
        group_id=group_id, snapshot_id="FRESH32-BROKER-BEFORE-LATE-FILL",
        as_of=anchor, source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=(), complete=True, capability_verified=True,
        payload_sha256=_digest({"group": group_id, "positions": []}),
    )
    pending_ledger = U19ExecutionLedgerSnapshot(
        group_id=group_id, snapshot_id="FRESH32-LEDGER-CANCEL-PENDING",
        as_of=anchor, source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=(), complete=True,
        payload_sha256=_digest({
            "group": group_id, "positions": [], "pending": [client_order_id],
        }),
        pending_order_ids=(client_order_id,),
    )
    waiting = recovery.recover(
        group_id=group_id, broker_snapshot=pending_broker,
        ledger_snapshot=pending_ledger,
    )
    assert waiting.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert waiting.restore_allowed is False
    assert waiting.new_entry_enabled is False
    assert waiting.order_submission_enabled is False

    # Inject the late partial fill after the cancel request begins but before
    # VSSF returns its terminal cancel acknowledgement.
    original_cancel = vssf.cancel_order
    race_fill_ids = []

    def cancel_with_late_fill(order_id, *, lifecycle_reason="MANUAL"):
        assert order_id == client_order_id
        pending_command = vssf.order_book.get_pending_order(order_id)
        assert pending_command is not None
        vssf.order_book.update_bid_ask(
            float(limit_price - Decimal("0.01")),
            float(limit_price), identity.instrument_id,
        )
        late_execution = vssf._execute(
            pending_command, float(limit_price), vssf._now(), quantity=1,
        )
        race_fill_ids.append(late_execution.exec_id)
        return original_cancel(order_id, lifecycle_reason=lifecycle_reason)

    vssf.cancel_order = cancel_with_late_fill
    cancelled = bridge.cancel_pending_order(client_order_id, reason="FRESH32_CANCEL_RACE")
    assert len(race_fill_ids) == 1
    assert cancelled.pending_legs == 0
    assert cancelled.reports[0].status == "CANCELLED"
    assert cancelled.reports[0].filled_quantity == 1
    assert cancelled.reports[0].remaining_quantity == 1
    assert cancelled.reports[0].execution_id == race_fill_ids[0]
    assert client_order_id not in bridge.pending_legs
    assert vssf.order_book.get_pending_order(client_order_id) is None

    fill_report = cancelled.reports[0]
    assert len(fill_report.execution_fills) == 1
    fill = fill_report.execution_fills[0]
    assert fill.execution_id == race_fill_ids[0]
    assert len(bridge.position_lot_store.history()) == 1
    assert len(bridge.position_lot_store.open_lots()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 1
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id)[0].execution_id == fill.execution_id
    assert Decimal(str(vssf.account.positions[identity.instrument_id]["qty"])) == Decimal("1")
    assert vssf.metrics["order_commands"] == 1

    # Re-deliver the same canonical execution through the Bridge's reconciliation
    # boundary: PositionLot, Fee Ledger and VSSF aggregates must remain unchanged.
    before_history = bridge.position_lot_store.history()
    before_fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    before_position = dict(vssf.account.positions[identity.instrument_id])
    bridge._apply_reconciled_execution(
        plan=plan, leg=plan.legs[0], identity=identity,
        broker_command=broker_command, report=fill_report,
    )
    assert bridge.position_lot_store.history() == before_history
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == before_fees
    assert vssf.account.positions[identity.instrument_id] == before_position
    assert vssf.metrics["order_commands"] == 1

    # Independently derive the ledger-side signed position from PositionLots.
    lot = bridge.position_lot_store.open_lots()[0]
    signed_quantity = Decimal(lot.remaining_quantity) * (
        Decimal("1") if lot.side == "BUY" else Decimal("-1")
    )
    ledger_positions = (U19Position(identity.instrument_id, signed_quantity),)
    vssf_position = vssf.account.positions[identity.instrument_id]
    broker_signed_quantity = Decimal(str(vssf_position["qty"])) * (
        Decimal("1") if str(vssf_position["side"]).upper() == "BUY" else Decimal("-1")
    )
    broker_positions = (U19Position(identity.instrument_id, broker_signed_quantity),)
    event_fingerprint = _digest({
        "execution_id": fill.execution_id,
        "client_order_id": fill_report.client_order_id,
        "instrument_id": identity.instrument_id,
        "side": lot.side,
        "quantity": fill.filled_quantity,
        "price": str(fill.execution_price),
        "fee": str(fill.fee),
        "executed_at": fill.execution_timestamp.isoformat(),
        "source_anchor_ref": source_ref,
        "manifest_sha256": sha256((dataset / "manifest.json").read_bytes()).hexdigest(),
    })
    event = U19ExecutionEvent(fill.execution_id, event_fingerprint)
    final_as_of = max(anchor, fill.execution_timestamp) + timedelta(seconds=1)
    final_broker_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in broker_positions],
    }
    final_ledger_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in ledger_positions],
        "execution_events": [(event.execution_id, event.fingerprint), (event.execution_id, event.fingerprint)],
        "pending_order_ids": [],
    }
    reconciled = recovery.recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id, snapshot_id="FRESH32-BROKER-AFTER-LATE-FILL",
            as_of=final_as_of, source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions, complete=True, capability_verified=True,
            payload_sha256=_digest(final_broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id, snapshot_id="FRESH32-LEDGER-AFTER-LATE-FILL",
            as_of=final_as_of, source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions, complete=True,
            payload_sha256=_digest(final_ledger_payload),
            execution_events=(event, event), pending_order_ids=(),
        ),
    )
    assert reconciled.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert reconciled.positions == broker_positions
    assert reconciled.execution_events == (event,)
    assert reconciled.pending_order_ids == ()
    assert reconciled.new_entry_enabled is False
    assert reconciled.order_submission_enabled is False
    persisted = SqliteTrack2U19RecoveryStore(tmp_path / "fresh32-u19.sqlite3").load_latest(group_id)
    assert persisted["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert len(persisted["execution_events"]) == 1
    assert persisted["new_entry_enabled"] is False
    assert persisted["order_submission_enabled"] is False

    # Same execution ID with a different payload is a conflict, never a second fill.
    conflict_event = U19ExecutionEvent(fill.execution_id, _digest({
        "execution_id": fill.execution_id, "different_payload": True,
    }))
    conflict_payload = {
        **final_ledger_payload,
        "execution_events": [
            (event.execution_id, event.fingerprint),
            (conflict_event.execution_id, conflict_event.fingerprint),
        ],
    }
    conflict = recovery.recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id, snapshot_id="FRESH32-BROKER-CONFLICT-CHECK",
            as_of=final_as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=broker_positions, complete=True, capability_verified=True,
            payload_sha256=_digest(final_broker_payload),
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            group_id=group_id, snapshot_id="FRESH32-LEDGER-CONFLICT-CHECK",
            as_of=final_as_of + timedelta(seconds=1),
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions, complete=True,
            payload_sha256=_digest(conflict_payload),
            execution_events=(event, conflict_event), pending_order_ids=(),
        ),
    )
    assert conflict.status is U19RecoveryStatus.EXECUTION_ID_CONFLICT
    assert conflict.restore_allowed is False
    assert conflict.new_entry_enabled is False
    assert conflict.order_submission_enabled is False
    assert len(bridge.position_lot_store.history()) == 1
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 1
    assert Decimal(str(vssf.account.positions[identity.instrument_id]["qty"])) == Decimal("1")
    assert vssf.metrics["order_commands"] == 1

    # The Bridge itself also rejects a changed payload for an already-seen execution.
    conflicting_fill = replace(
        fill, execution_price=Decimal(str(fill.execution_price)) + Decimal("0.01"),
    )
    conflicting_report = replace(fill_report, execution_fills=(conflicting_fill,))
    with pytest.raises(RuntimeError, match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED"):
        bridge._apply_reconciled_execution(
            plan=plan, leg=plan.legs[0], identity=identity,
            broker_command=broker_command, report=conflicting_report,
        )
    assert bridge.position_lot_store.history() == before_history
    assert bridge.fee_ledger.snapshot(run_id=bridge.run_id) == before_fees
    assert vssf.account.positions[identity.instrument_id] == before_position
    assert vssf.metrics["order_commands"] == 1
