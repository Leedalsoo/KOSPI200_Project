import json
from decimal import Decimal

import pytest

from application.composition.strategy5_risk_diagnostic_jsonl import Strategy5RiskDiagnosticJsonl


def _append(writer, run_id="run-001"):
    return writer.append_preflight(
        run_id=run_id,
        strategy_id="track5_gap_divergence",
        group_id="group-001",
        evaluations=[{
            "leg_id": "futures-close",
            "client_order_id": "order-001",
            "instrument_id": "FUT-001",
            "side": "BUY",
            "quantity": 2,
            "admitted": True,
            "risk_decision": "ALLOW",
            "risk_approved": True,
            "rejection_reason": None,
            "required_margin": "125.50",
            "estimated_margin_ratio": "0.12",
        }],
        total_required_margin=Decimal("125.50"),
        total_balance=Decimal("1000"),
        used_margin=Decimal("100"),
        free_margin=Decimal("900"),
        max_margin_utilization_ratio=Decimal("0.8"),
        group_margin_ratio=Decimal("0.2255"),
        aggregate_rejection=None,
        leg_rejected=False,
    )


def test_strategy5_diagnostic_appends_separate_jsonl_events_and_preserves_decimal_strings(tmp_path):
    writer = Strategy5RiskDiagnosticJsonl(tmp_path)
    path = _append(writer)
    _append(writer)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["schema_version"] == "strategy5-risk-diagnostic.v1"
    assert first["provenance"] == {
        "run_id": "run-001",
        "strategy_id": "track5_gap_divergence",
        "group_id": "group-001",
    }
    assert first["legs"][0]["required_margin"] == "125.50"
    assert first["aggregate"]["total_required_margin"] == "125.50"
    assert first["aggregate"]["decision"] == "ALLOW"


def test_strategy5_diagnostic_uses_one_artifact_per_run(tmp_path):
    writer = Strategy5RiskDiagnosticJsonl(tmp_path)
    first = _append(writer, "run-A")
    second = _append(writer, "run-B")

    assert first != second
    assert first.exists() and second.exists()
    assert len(first.read_text(encoding="utf-8").splitlines()) == 1
    assert len(second.read_text(encoding="utf-8").splitlines()) == 1


def test_strategy5_diagnostic_rejects_path_traversal_run_id(tmp_path):
    writer = Strategy5RiskDiagnosticJsonl(tmp_path)
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        _append(writer, "..//..")



def test_diagnostic_write_failure_is_reported_without_raising_or_changing_caller_flow():
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge

    class FailingWriter:
        def append_preflight(self, **_payload):
            raise OSError("disk unavailable")

    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge._strategy5_risk_diagnostic = FailingWriter()
    bridge.risk_diagnostic_status = {"status": "NOT_ATTEMPTED", "error": None, "artifact_path": None}

    bridge._record_strategy5_risk_preflight_diagnostic(
        run_id="run-1", strategy_id="track5_gap_divergence", group_id="group-1",
        evaluations=[], total_required_margin=Decimal("0"), total_balance=Decimal("100"),
        used_margin=Decimal("0"), free_margin=Decimal("100"),
        max_margin_utilization_ratio=Decimal("0.8"), group_margin_ratio=Decimal("0"),
        aggregate_rejection=None, leg_rejected=False,
    )

    assert bridge.risk_diagnostic_status == {
        "status": "FAILED", "error": "OSError", "artifact_path": None,
    }
