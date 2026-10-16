"""FRESH-11 bridge provider wiring and fail-closed execute path; offline only."""
import ast
from decimal import Decimal
from pathlib import Path
from types import MethodType, SimpleNamespace

from application.composition import virtual_multi_leg_execution as bridge_module
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from contracts.risk import RiskEvaluationResult

ROOT = Path(__file__).resolve().parents[3]


class FakeBroker:
    def __init__(self):
        self.submissions = []
    def submit(self, command, **kwargs):
        self.submissions.append(command)
        raise AssertionError("missing freshness provider must block before broker submit")


class RiskGateStub:
    def __init__(self):
        self.last_evaluation_result = None
        self.engine = SimpleNamespace(config=SimpleNamespace(max_margin_utilization_ratio=Decimal("1")))
        self.calls = 0
    def admit_order(self, *args, **kwargs):
        self.calls += 1
        self.last_evaluation_result = RiskEvaluationResult(True, "ALLOW", 1, 1, None, Decimal("0"), Decimal("0"))
        return True, object(), None


class ReadModelSpy:
    def __init__(self):
        self.records = []
    def record(self, record):
        self.records.append(record)


def test_fresh11_factory_bridge_call_omits_authoritative_freshness_provider():
    source = (ROOT / "application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "VirtualMultiLegExecutionBridge"]
    assert len(calls) == 1
    supplied_keywords = {kw.arg for kw in calls[0].keywords}
    assert "freshness_verdict_provider" not in supplied_keywords


def test_fresh11_actual_bridge_execute_rejects_missing_provider_before_any_submit(monkeypatch):
    broker = FakeBroker()
    identities = {
        "call": OptionInstrumentIdentity("OPT-C", "OPT-C", "20261029", "CALL", Decimal("100"), Decimal("100"), "TEST_FIXTURE"),
        "put": OptionInstrumentIdentity("OPT-P", "OPT-P", "20261029", "PUT", Decimal("100"), Decimal("100"), "TEST_FIXTURE"),
    }
    quotes = {
        ("CALL", 100.0, "20261029"): {"bid": "1.0", "ask": "1.1", "contract_multiplier": "100"},
        ("PUT", 100.0, "20261029"): {"bid": "1.0", "ask": "1.1", "contract_multiplier": "100"},
    }
    order_book = SimpleNamespace(update_bid_ask=lambda *args, **kwargs: None)
    vssf = SimpleNamespace(account=SimpleNamespace(realized_pnl=Decimal("0")), order_book=order_book)
    owner = SimpleNamespace(vssf_runtime=vssf)
    bundle = SimpleNamespace(account=SimpleNamespace(snapshot=lambda: SimpleNamespace(total_balance=100000, used_margin=0, free_margin=100000)),
        position=object(), market=SimpleNamespace(option_quotes=quotes), broker=broker,
        execution=SimpleNamespace(_authoritative_execute=MethodType(lambda self: None, owner)))
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.bundle = bundle
    bridge.option_master = SimpleNamespace(get_contract_identity=lambda instrument_id: SimpleNamespace(contract_multiplier=Decimal("100")))
    bridge.groups = {}
    bridge.freshness_verdict_provider = None
    bridge.command_context = SimpleNamespace(build_command=lambda command: command)
    bridge.risk_gate = RiskGateStub()
    bridge.risk_approval_read_model = ReadModelSpy()
    bridge._strategy5_risk_diagnostic = SimpleNamespace(append_preflight=lambda **kwargs: None)
    bridge.risk_diagnostic_status = {"status": "NOT_ATTEMPTED", "error": None, "artifact_path": None}
    bridge.position_groups = __import__("core.oms.position_group", fromlist=["PositionGroupRegistry"]).PositionGroupRegistry()
    bridge.run_id = "offline-test"
    bridge.execution_result_callback = None
    bridge.futures_identity_source = None
    bridge.option_expiry_source = None
    bridge.fsm = SimpleNamespace()
    bridge.ack = SimpleNamespace(last_report=None)
    bridge.router = SimpleNamespace(register_and_route=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("router reached")))
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: ())
    bridge.fee_ledger = SimpleNamespace()
    bridge.option_position_attribution = SimpleNamespace()
    bridge.insurance_position = SimpleNamespace()
    bridge.provenance = {}
    bridge.execution_legs = {}
    bridge.leg_positions = {}
    bridge.pending_legs = {}
    bridge._applied_execution_fingerprints = {}
    bridge.identity_for_leg = MethodType(lambda self, plan, leg: identities[leg.leg_id], bridge)
    bridge._position_flat_for_plan = MethodType(lambda self, plan: True, bridge)
    monkeypatch.setattr(bridge_module, "account_snapshot_to_risk_input", lambda snapshot: SimpleNamespace(total_balance=Decimal("100000"), used_margin=Decimal("0"), free_margin=Decimal("100000")))
    monkeypatch.setattr(bridge_module, "position_manager_to_risk_input", lambda position: object())
    monkeypatch.setattr(bridge_module.CanonicalRiskCommandAdapter, "from_command", staticmethod(lambda command: command))

    plan = MultiLegExecutionPlan("fresh11-no-provider", "S1", (
        ExecutionLeg("call", "BUY", 1, instrument_identity=identities["call"]),
        ExecutionLeg("put", "BUY", 1, instrument_identity=identities["put"]),
    ))
    result = bridge.execute(plan)
    assert bridge.freshness_verdict_provider is None
    assert bridge.risk_gate.calls == 2
    assert broker.submissions == []
    assert len(result.reports) == 2
    assert all(report.status == "REJECTED" for report in result.reports)
    assert all(report.rejected_reason == "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED" for report in result.reports)
    assert result.routed_legs == 0
