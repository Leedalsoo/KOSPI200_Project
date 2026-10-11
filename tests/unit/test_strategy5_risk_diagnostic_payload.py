from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_strategy5_risk_diagnostic_virtual_runtime import _run_approved_fill_case


def test_approved_strategy5_group_preflight_persists_margin_inputs(tmp_path: Path) -> None:
    output_root = tmp_path / "payload-evidence"
    case = _run_approved_fill_case(fail_writer=False, output_root=output_root)

    assert case["diagnostic_status"] == "RECORDED"
    artifacts = list(output_root.glob("*.jsonl"))
    assert len(artifacts) == 1
    lines = artifacts[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert record["event_type"] == "GROUP_RISK_PREFLIGHT"
    assert record["provenance"]["run_id"] == "isolated-approved-fill-compare"
    assert record["aggregate"]["decision"] == "ALLOW"
    aggregate = record["aggregate"]
    for field in (
        "total_required_margin",
        "total_balance",
        "used_margin",
        "free_margin",
        "max_margin_utilization_ratio",
        "computed_group_margin_ratio",
    ):
        assert aggregate[field] is not None, field
        assert isinstance(aggregate[field], str), field

    assert aggregate["aggregate_rejection"] is None
    assert aggregate["leg_risk_rejected"] is False
    assert len(record["legs"]) == 1
    leg = record["legs"][0]
    assert leg["leg_id"] == "futures-approved-fill"
    assert leg["client_order_id"]
    assert leg["instrument_id"] == "TEST-MINI-2001"
    assert leg["risk_approved"] is True
    assert leg["required_margin"] is not None
    assert leg["estimated_margin_ratio"] is not None
