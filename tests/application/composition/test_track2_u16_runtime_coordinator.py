from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track2_u16_runtime_coordinator import ValidationOnlyU16RuntimeCoordinator
from core.strategy.track2_u16_repair_lifecycle import U16Fill, U16QuotePolicy, U16RepairInput, U16RepairState

T0 = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
POLICY = U16QuotePolicy(validated=True, side_to_book_rule="VALIDATION_ONLY", max_quote_age_seconds=5,
    max_spread="0.1", spread_unit="PRICE", fallback_formula="VALIDATION_ONLY",
    fallback_priority="VALIDATION_ONLY", tick_rounding_rule="VALIDATION_ONLY",
    retry_interval_seconds=30)


def data(**overrides):
    values = dict(group_id="g1", leg_id="inner_put", target_quantity=3,
        original_order_terminal=True, original_order_cancelled_or_closed=True,
        original_order_status="CANCELLED", fills=(U16Fill("f1", 1),),
        position_quantity=1, now=T0, quote_policy=POLICY, quote_present=True,
        quote_fresh=True, quote_spread_within_policy=True)
    values.update(overrides)
    return U16RepairInput(**values)


def test_runtime_submits_only_missing_quantity_and_persists_restart_state():
    repairs=[]
    c=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda g,leg,q,cid,now: repairs.append((g,q,cid)) or SimpleNamespace(terminal=False,reconciled=False),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"))
    result=c.process(data())
    assert result.action == "REPAIR_SUBMITTED" and result.submitted_quantity == 2
    assert repairs[0][1] == 2
    restored=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda *args: pytest.fail("must not blindly retry"),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"))
    restored.restore(c.snapshot())
    waiting=restored.process(data(now=T0+timedelta(seconds=30)))
    assert waiting.action == "NO_SUBMISSION"
    assert waiting.evaluation.state == U16RepairState.REPAIR_WAITING


def test_runtime_retry_requires_prior_attempt_terminal_and_reconciled():
    calls=[]
    c=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda g,leg,q,cid,now: calls.append(q) or SimpleNamespace(terminal=True,reconciled=True),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"))
    c.process(data())
    # Inject explicit reconciliation evidence for the previous attempt.
    snap=c.snapshot(); key="g1|inner_put"
    snap[key]["previous_repair_terminal"]=True
    snap[key]["previous_repair_reconciled"]=True
    c.restore(snap)
    result=c.process(data(now=T0+timedelta(seconds=30), fills=(U16Fill("f1",1),), position_quantity=1))
    assert result.action == "REPAIR_SUBMITTED"
    assert calls == [2,2]


def test_runtime_deadline_flattens_only_confirmed_position():
    flattened=[]
    c=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda *args: SimpleNamespace(terminal=True,reconciled=True),
        submit_flatten=lambda g,leg,q,cid: flattened.append((g,q,cid)) or SimpleNamespace(terminal=True,reconciled=True))
    c.restore({"g1|inner_put":{"first_repair_submitted_at":T0,
        "additional_retry_count":3,"previous_repair_terminal":True,
        "previous_repair_reconciled":True}})
    result=c.process(data(now=T0+timedelta(seconds=120)))
    assert result.action == "FLATTEN_SUBMITTED"
    assert flattened[0][1] == 1
    blocked=c.process(data(now=T0+timedelta(seconds=120),position_quantity=None))
    assert blocked.action == "NO_SUBMISSION"
    assert blocked.evaluation.state == U16RepairState.RECONCILIATION_REQUIRED


def test_live_construction_is_rejected():
    with pytest.raises(ValueError, match="VALIDATION_ONLY"):
        ValidationOnlyU16RuntimeCoordinator(validation_only=False,
            submit_repair=lambda *args: None, submit_flatten=lambda *args: None)





def test_runtime_exposes_reconciliation_api_for_retry_gate():
    calls=[]
    c=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda g,leg,q,cid,now: calls.append(cid) or SimpleNamespace(terminal=False,reconciled=False),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"))
    c.process(data())
    c.record_repair_reconciliation("g1", "inner_put", terminal=True, reconciled=True)
    result=c.process(data(now=T0+timedelta(seconds=30)))
    assert result.action == "REPAIR_SUBMITTED"
    assert len(calls) == 2


def test_runtime_flatten_submission_is_idempotent_until_reconciled():
    flattened=[]
    c=ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda *args: pytest.fail("unexpected repair"),
        submit_flatten=lambda g,leg,q,cid: flattened.append((g,q,cid)) or SimpleNamespace(terminal=False,reconciled=False))
    c.restore({"g1|inner_put":{"first_repair_submitted_at":T0,
        "additional_retry_count":3,"previous_repair_terminal":True,
        "previous_repair_reconciled":True}})
    first=c.process(data(now=T0+timedelta(seconds=120)))
    second=c.process(data(now=T0+timedelta(seconds=121)))
    assert first.action == "FLATTEN_SUBMITTED"
    assert second.action == "FLATTEN_ALREADY_SUBMITTED"
    assert len(flattened) == 1
    assert first.client_order_id == second.client_order_id


def test_runtime_state_is_persisted_and_restored_only_after_u19_authorization(tmp_path):
    from application.composition.track2_u16_runtime_coordinator import ValidationOnlyU16RuntimeCoordinator
    from environments.virtual.position.track2_u16_runtime_store import SqliteTrack2U16RuntimeStore

    store = SqliteTrack2U16RuntimeStore(tmp_path / "u16.sqlite")
    first = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: SimpleNamespace(terminal=False, reconciled=False),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"),
        state_store=store,
    )
    first.process(data())

    restarted = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: pytest.fail("must not blindly retry"),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"),
        state_store=store,
    )
    denied = SimpleNamespace(status="POSITION_LEDGER_MISMATCH", restore_allowed=False,
                             strategy_resume_allowed=False)
    with pytest.raises(ValueError, match="U19_RECOVERY_NOT_AUTHORIZED"):
        restarted.restore_after_u19_recovery("g1", denied)

    allowed = SimpleNamespace(status="RESTORE_ALLOWED", restore_allowed=True,
                              strategy_resume_allowed=True)
    assert restarted.restore_after_u19_recovery("g1", allowed)
    waiting = restarted.process(data(now=T0 + timedelta(seconds=30)))
    assert waiting.action == "NO_SUBMISSION"
    assert waiting.evaluation.state == U16RepairState.REPAIR_WAITING


def test_u16_runtime_store_is_append_only_and_group_scoped(tmp_path):
    import sqlite3
    from environments.virtual.position.track2_u16_runtime_store import SqliteTrack2U16RuntimeStore

    store = SqliteTrack2U16RuntimeStore(tmp_path / "u16.sqlite")
    snapshot = {"g1|inner_put": {"first_repair_submitted_at": T0,
                                "additional_retry_count": 0}}
    first_id = store.save("g1", snapshot)
    assert store.save("g1", snapshot) == first_id
    assert store.load_latest("g1")["g1|inner_put"]["first_repair_submitted_at"] == T0
    with pytest.raises(ValueError, match="GROUP_SCOPE_MISMATCH"):
        store.save("g1", {"g2|inner_put": {}})
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY"):
            connection.execute("DELETE FROM track2_u16_runtime_snapshot")

def test_flatten_reconciliation_state_persists_and_does_not_resubmit(tmp_path):
    from application.composition.track2_u16_runtime_coordinator import ValidationOnlyU16RuntimeCoordinator
    from environments.virtual.position.track2_u16_runtime_store import SqliteTrack2U16RuntimeStore

    store = SqliteTrack2U16RuntimeStore(tmp_path / "u16.sqlite")
    flattened = []
    c = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: pytest.fail("unexpected repair"),
        submit_flatten=lambda g, leg, q, cid: flattened.append(cid) or SimpleNamespace(terminal=False, reconciled=False),
        state_store=store,
    )
    c.restore({"g1|inner_put": {"first_repair_submitted_at": T0,
        "additional_retry_count": 3, "previous_repair_terminal": True,
        "previous_repair_reconciled": True}})
    c.process(data(now=T0 + timedelta(seconds=120)))
    c.record_flatten_reconciliation("g1", "inner_put", terminal=True, reconciled=True)

    restarted = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: pytest.fail("unexpected repair"),
        submit_flatten=lambda *args: pytest.fail("must not resubmit flatten"),
        state_store=store,
    )
    decision = SimpleNamespace(status="RESTORE_ALLOWED", restore_allowed=True,
                               strategy_resume_allowed=True)
    assert restarted.restore_after_u19_recovery("g1", decision)
    result = restarted.process(data(now=T0 + timedelta(seconds=121)))
    assert result.action == "FLATTEN_ALREADY_SUBMITTED"
    assert result.terminal and result.reconciled
    assert flattened and len(flattened) == 1
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from application.composition.track2_u16_virtual_bridge_ports import ValidationOnlyU16VirtualBridgePorts


@dataclass(frozen=True)
class FakeIdentity:
    instrument_id: str
    option_type: str = "PUT"
    strike: Decimal = Decimal("300")
    expiry: str = "20261210"


@dataclass
class FakeLot:
    run_id: str
    strategy_id: str
    group_id: str
    instrument_id: str
    remaining_quantity: int
    side: str = "BUY"


class FakeLots:
    def __init__(self, values): self.values = list(values)
    def open_lots(self): return tuple(self.values)


class FakeBridge:
    def __init__(self, lots):
        self.validation_order_gate = None
        self.freshness_verdict_provider = object()
        self.validation_only_track2_identity_validator = object()
        self.run_id = "validation-run"
        self.position_lot_store = FakeLots(lots)
        self.pending_legs = {}
        self.groups = {}
        self.executions = []
        self.quote = None
        self.bundle = SimpleNamespace(execution=SimpleNamespace(
            _authoritative_execute=SimpleNamespace(__self__=SimpleNamespace(
                vssf_runtime=SimpleNamespace(account=SimpleNamespace(positions={}))
            ))
        ))

    def identity_for_leg(self, plan, leg): return leg.instrument_identity
    def _option_quote_for_instrument_id(self, instrument_id): return self.quote

    def cancel_pending_order(self, client_order_id, *, reason="MANUAL"):
        group_plan, leg, command = self.pending_legs.pop(client_order_id)
        previous = next(item for item in self.groups[group_plan.group_id]
                        if item.client_order_id == client_order_id)
        cancelled = SimpleNamespace(client_order_id=client_order_id, leg_id=leg.leg_id,
            status="CANCELLED", filled_quantity=previous.filled_quantity,
            remaining_quantity=0, execution_id=getattr(previous, "execution_id", None))
        self.groups[group_plan.group_id] = [cancelled if item.client_order_id == client_order_id else item
                                            for item in self.groups[group_plan.group_id]]
        return SimpleNamespace(reports=(cancelled,))

    @staticmethod
    def _client_order_id(plan, leg, identity):
        return f"{plan.group_id}-{leg.leg_id}-{plan.attempt_id}"

    def execute(self, plan, *, group_plan):
        self.executions.append((plan, group_plan))
        reports = []
        for leg in plan.legs:
            identity = leg.instrument_identity
            cid = self._client_order_id(plan, leg, identity)
            report = SimpleNamespace(client_order_id=cid, leg_id=leg.leg_id,
                status="FILLED", filled_quantity=leg.quantity, remaining_quantity=0)
            reports.append(report)
            self.groups.setdefault(group_plan.group_id, []).append(report)
            if str(plan.purpose).upper() == "TRAP_CLOSE":
                self.position_lot_store.values = [lot for lot in self.position_lot_store.values
                    if not (lot.group_id == group_plan.group_id and lot.instrument_id == identity.instrument_id)]
                self.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 0}
            else:
                prior_qty = sum(l.remaining_quantity for l in self.position_lot_store.values
                                if l.group_id == group_plan.group_id and l.instrument_id == identity.instrument_id)
                total_qty = prior_qty + leg.quantity
                self.position_lot_store.values = [l for l in self.position_lot_store.values
                    if not (l.group_id == group_plan.group_id and l.instrument_id == identity.instrument_id)]
                self.position_lot_store.values.append(FakeLot(self.run_id, plan.strategy_id,
                    plan.group_id, identity.instrument_id, total_qty))
                self.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": total_qty}
        return SimpleNamespace(reports=tuple(reports))

    def build_close_plan_from_open_lots(self, *, strategy_id, purpose, asset_type,
                                        option_type=None, strike=None, expiry=None):
        legs = []
        for index, lot in enumerate(self.position_lot_store.values):
            is_call = "CALL" in lot.instrument_id
            identity = FakeIdentity(lot.instrument_id,
                "CALL" if is_call else "PUT", Decimal("310") if is_call else Decimal("300"))
            legs.append(ExecutionLeg(f"close-{index}", "SELL" if lot.side == "BUY" else "BUY",
                lot.remaining_quantity, option_type=identity.option_type,
                strike=identity.strike, position_role="LONG", instrument_identity=identity))
        return MultiLegExecutionPlan(group_id=self.position_lot_store.values[0].group_id,
            strategy_id=strategy_id, purpose=purpose, legs=tuple(legs))



def test_virtual_bridge_repair_uses_authoritative_leg_side_identity_and_missing_quantity():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
        ExecutionLeg("inner_call", "BUY", 2, option_type="CALL", strike=Decimal("310"),
                    position_role="LONG", instrument_identity=FakeIdentity("SYNTHETIC_CONTRACT:CALL310", "CALL", Decimal("310"))),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 2)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put",
        status="CANCELLED", filled_quantity=2, remaining_quantity=1, execution_id="fill-original")]
    bridge.quote = {"bid": "1.0", "ask": "1.1", "timestamp": T0.isoformat()}
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan if group == "g1" else None,
        quote_policy=POLICY,
        repair_price_resolver=lambda plan, leg, identity, quote, policy, now: Decimal(str(quote["ask"])))
    evidence = ports.submit_repair("g1", "inner_put", 1, "u16-repair-1", T0)
    routed_plan, original_group = bridge.executions[0]
    assert routed_plan.legs[0].leg_id == "inner_put"
    assert routed_plan.legs[0].quantity == 1
    assert routed_plan.legs[0].side == "BUY"
    assert routed_plan.legs[0].instrument_identity == identity
    assert routed_plan.attempt_id == "u16-repair-1"
    assert original_group is plan
    assert evidence.terminal and evidence.reconciled


def test_virtual_bridge_flatten_requires_exactly_one_authoritative_target_leg():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 2, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 2)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    evidence = ports.submit_flatten("g1", "inner_put", 2, "u16-flatten-1")
    routed_plan, original_group = bridge.executions[0]
    assert routed_plan.purpose == "TRAP_CLOSE"
    assert routed_plan.legs[0].quantity == 2
    assert routed_plan.legs[0].side == "SELL"
    assert evidence.terminal and evidence.reconciled


def test_virtual_bridge_flatten_refuses_ambiguous_multi_leg_close():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 2, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 2)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    bridge.build_close_plan_from_open_lots = lambda **kwargs: MultiLegExecutionPlan(
        "g1", plan.strategy_id, (ExecutionLeg("a", "SELL", 1), ExecutionLeg("b", "SELL", 1)),
        purpose="TRAP_CLOSE")
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    with pytest.raises(ValueError, match="FLATTEN_GROUP_SCOPE_NOT_UNIQUE"):
        ports.submit_flatten("g1", "inner_put", 2, "u16-flatten-1")


def test_virtual_bridge_builds_u16_input_from_terminal_fill_position_and_quote_evidence():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 1)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 1}
    bridge.quote = {"bid": "1.0", "ask": "1.1", "timestamp": (T0 + timedelta(seconds=10)).isoformat()}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put", status="CANCELLED",
        filled_quantity=1, execution_id="fill-1", remaining_quantity=2)]
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    built = ports.build_repair_input(group_id="g1", leg_id="inner_put",
        now=T0 + timedelta(seconds=12), quote_policy=POLICY)
    assert built.original_order_terminal and built.original_order_cancelled_or_closed
    assert built.original_order_status == "CANCELLED"
    assert built.target_quantity == 3 and built.position_quantity == 1
    assert built.fills[0].execution_id == "fill-1" and built.fills[0].quantity == 1
    assert built.quote_present and built.quote_fresh and built.quote_spread_within_policy


def test_virtual_bridge_builds_blocking_u16_evidence_for_expired_quote_or_position_mismatch():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 1)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    bridge.quote = {"bid": "1.0", "ask": "1.1", "timestamp": (T0 - timedelta(seconds=20)).isoformat()}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put", status="CANCELLED",
        filled_quantity=1, execution_id="fill-1", remaining_quantity=2)]
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    built = ports.build_repair_input(group_id="g1", leg_id="inner_put",
        now=T0, quote_policy=POLICY)
    assert built.position_quantity is None
    assert not built.quote_fresh
    assert built.quote_spread_within_policy

def test_coordinator_persists_actual_bridge_client_order_id():
    c = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda g, leg, q, cid, now: SimpleNamespace(
            client_order_id="bridge-actual-order-77", terminal=True, reconciled=True),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"),
    )
    result = c.process(data())
    assert result.client_order_id == "bridge-actual-order-77"
    assert c.snapshot()["g1|inner_put"]["last_client_order_id"] == "bridge-actual-order-77"


def test_virtual_bridge_ports_require_validation_freshness_and_identity_gates():
    from application.composition.track2_u16_virtual_bridge_ports import ValidationOnlyU16VirtualBridgePorts
    bridge = SimpleNamespace(execute=lambda *args, **kwargs: None,
        freshness_verdict_provider=None, validation_only_track2_identity_validator=object())
    with pytest.raises(ValueError, match="FRESHNESS_PROVIDER_REQUIRED"):
        ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
            entry_plan_provider=lambda group: None, quote_policy=POLICY)


def test_virtual_bridge_repair_refuses_nonterminal_original_order():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 1)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 1}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=2, execution_id="fill-1")]
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    with pytest.raises(ValueError, match="ORIGINAL_ORDER_NOT_TERMINAL"):
        ports.submit_repair("g1", "inner_put", 2, "u16-repair-1", T0)


def test_virtual_bridge_repair_refuses_missing_quantity_that_disagrees_with_fills():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 1)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 1}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put",
        status="CANCELLED", filled_quantity=1, remaining_quantity=2, execution_id="fill-1")]
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    with pytest.raises(ValueError, match="MISSING_QUANTITY_MISMATCH"):
        ports.submit_repair("g1", "inner_put", 1, "u16-repair-1", T0)


def test_virtual_bridge_flatten_liquidates_all_filled_legs_in_group():
    put = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    call = FakeIdentity("SYNTHETIC_CONTRACT:CALL310", "CALL", Decimal("310"))
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 2, option_type="PUT", strike=put.strike,
                    position_role="LONG", instrument_identity=put),
        ExecutionLeg("inner_call", "BUY", 1, option_type="CALL", strike=call.strike,
                    position_role="LONG", instrument_identity=call),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([
        FakeLot("validation-run", plan.strategy_id, "g1", put.instrument_id, 2),
        FakeLot("validation-run", plan.strategy_id, "g1", call.instrument_id, 1),
    ])
    positions = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions
    positions[put.instrument_id] = {"qty": 2}
    positions[call.instrument_id] = {"qty": 1}
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    evidence = ports.submit_flatten("g1", "inner_put", 3, "u16-group-flatten-1")
    close_plan, original_group = bridge.executions[0]
    assert close_plan.purpose == "TRAP_CLOSE"
    assert len(close_plan.legs) == 2
    assert {leg.side for leg in close_plan.legs} == {"SELL"}
    assert evidence.terminal and evidence.reconciled
    assert len(evidence.client_order_ids) == 2
    reconciled = ports.reconcile_group_flatten("g1", evidence.client_order_id,
                                               evidence.client_order_ids)
    assert reconciled.terminal and reconciled.reconciled
    assert reconciled.client_order_id == evidence.client_order_id
    assert not bridge.position_lot_store.open_lots()
    assert positions[put.instrument_id]["qty"] == 0
    assert positions[call.instrument_id]["qty"] == 0


def test_u16_deadline_does_not_flatten_while_repair_attempt_is_unreconciled():
    flattened = []
    c = ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda *args: pytest.fail("unexpected repair"),
        submit_flatten=lambda *args: flattened.append(args))
    c.restore({"g1|inner_put": {"first_repair_submitted_at": T0,
        "additional_retry_count": 1, "previous_repair_terminal": False,
        "previous_repair_reconciled": False, "last_client_order_id": "pending-repair"}})
    result = c.process(data(now=T0 + timedelta(seconds=120)))
    assert result.action == "FLATTEN_BLOCKED_REPAIR_UNRECONCILED"
    assert not flattened



def test_virtual_bridge_cancel_race_reconciles_repair_fills_before_retry():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 2)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put",
        status="CANCELLED", filled_quantity=1, remaining_quantity=2, execution_id="fill-original")]
    repair_leg = plan.legs[0]
    repair_plan = MultiLegExecutionPlan("g1", plan.strategy_id, (repair_leg,),
        purpose="TRAP_ENTRY", attempt_id="repair-attempt")
    repair_id = bridge._client_order_id(repair_plan, repair_leg, identity)
    bridge.groups["g1"].append(SimpleNamespace(client_order_id=repair_id, leg_id="inner_put",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=2, execution_id="fill-repair"))
    bridge.pending_legs[repair_id] = (plan, repair_leg,
        SimpleNamespace(instrument_id=identity.instrument_id))
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    evidence = ports.cancel_repair_and_reconcile("g1", "inner_put", repair_id,
        reason="U16_QUOTE_EXPIRED")
    assert evidence.terminal and evidence.reconciled
    assert evidence.status == "CANCELLED" and evidence.filled_quantity == 1
    assert repair_id not in bridge.pending_legs


def test_u16_group_flatten_can_trigger_from_zero_fill_leg_when_other_legs_are_open():
    flattened = []
    c = ValidationOnlyU16RuntimeCoordinator(validation_only=True,
        submit_repair=lambda *args: pytest.fail("unexpected repair"),
        submit_flatten=lambda group, leg, qty, cid: flattened.append((group, leg, qty, cid))
            or SimpleNamespace(client_order_id="group-flat-id", client_order_ids=("close1", "close2"),
                               terminal=True, reconciled=True))
    c.restore({"g1|outer_call": {"first_repair_submitted_at": T0,
        "additional_retry_count": 3, "previous_repair_terminal": True,
        "previous_repair_reconciled": True}})
    result = c.process(data(leg_id="outer_call", fills=(), position_quantity=0,
        now=T0 + timedelta(seconds=120), group_position_quantity=3,
        group_position_confirmed=True))
    assert result.action == "FLATTEN_SUBMITTED"
    assert flattened[0][2] == 3
    assert c.snapshot()["g1|outer_call"]["flatten_client_order_ids"] == ("close1", "close2")


def test_virtual_bridge_repair_refuses_to_submit_without_explicit_limit_price_resolver():
    identity = FakeIdentity("SYNTHETIC_CONTRACT:PUT300")
    plan = MultiLegExecutionPlan("g1", "track2_asymmetric_trap", (
        ExecutionLeg("inner_put", "BUY", 3, option_type="PUT", strike=identity.strike,
                    position_role="LONG", instrument_identity=identity),
    ), purpose="TRAP_ENTRY")
    bridge = FakeBridge([FakeLot("validation-run", plan.strategy_id, "g1", identity.instrument_id, 2)])
    bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions[identity.instrument_id] = {"qty": 2}
    original_id = bridge._client_order_id(plan, plan.legs[0], identity)
    bridge.groups["g1"] = [SimpleNamespace(client_order_id=original_id, leg_id="inner_put",
        status="CANCELLED", filled_quantity=2, remaining_quantity=1, execution_id="fill-original")]
    bridge.quote = {"bid": "1.0", "ask": "1.1", "timestamp": T0.isoformat()}
    ports = ValidationOnlyU16VirtualBridgePorts(validation_only=True, bridge=bridge,
        entry_plan_provider=lambda group: plan, quote_policy=POLICY)
    with pytest.raises(ValueError, match="PRICE_RESOLVER_REQUIRED"):
        ports.submit_repair("g1", "inner_put", 1, "u16-repair-1", T0)



def test_u16_runtime_rehydrates_after_real_u19_decision_without_blind_retry(tmp_path):
    from environments.virtual.position.track2_u16_runtime_store import SqliteTrack2U16RuntimeStore
    from core.oms.track2_u19_recovery import (
        U19BrokerPositionSnapshot,
        U19ExecutionEvent,
        U19ExecutionLedgerSnapshot,
        U19Position,
        U19RecoveryStatus,
        evaluate_u19_recovery,
    )

    store = SqliteTrack2U16RuntimeStore(tmp_path / "u16-rehydrate.sqlite")
    submitted = []
    first = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda g, leg, qty, cid, now: submitted.append((g, leg, qty, cid))
            or SimpleNamespace(client_order_id="repair-attempt-1", terminal=False, reconciled=False),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"),
        state_store=store,
    )
    initial = first.process(data())
    assert initial.action == "REPAIR_SUBMITTED"
    assert initial.submitted_quantity == 2
    assert len(submitted) == 1

    position = (U19Position("SYNTHETIC_CONTRACT:PUT300", Decimal("1")),)
    broker = U19BrokerPositionSnapshot(
        group_id="g1", snapshot_id="broker-restart-1", as_of=T0,
        source="VALIDATION_ONLY:BROKER_EXCHANGE", positions=position,
        complete=True, capability_verified=True, payload_sha256="a" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id="g1", snapshot_id="ledger-restart-1", as_of=T0,
        source="VALIDATION_ONLY:EXECUTION_LEDGER", positions=position,
        complete=True, payload_sha256="b" * 64,
        execution_events=(U19ExecutionEvent("fill-original-1", "fingerprint-1"),),
        pending_order_ids=(),
    )
    decision = evaluate_u19_recovery(
        group_id="g1", broker_snapshot=broker, ledger_snapshot=ledger,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.restore_allowed and decision.strategy_resume_allowed
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False

    restarted_submissions = []
    restarted = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda g, leg, qty, cid, now: restarted_submissions.append((g, leg, qty, cid))
            or SimpleNamespace(client_order_id=cid, terminal=True, reconciled=True),
        submit_flatten=lambda *args: pytest.fail("unexpected flatten"),
        state_store=store,
    )
    assert restarted.restore_after_u19_recovery("g1", decision)

    waiting = restarted.process(data(now=T0 + timedelta(seconds=30)))
    assert waiting.action == "NO_SUBMISSION"
    assert waiting.evaluation.state is U16RepairState.REPAIR_WAITING
    assert not restarted_submissions

    restarted.record_repair_reconciliation(
        "g1", "inner_put", terminal=True, reconciled=True,
    )
    retry = restarted.process(data(now=T0 + timedelta(seconds=30)))
    assert retry.action == "REPAIR_SUBMITTED"
    assert retry.submitted_quantity == 2
    assert len(restarted_submissions) == 1
    assert restarted_submissions[0][3] == retry.client_order_id