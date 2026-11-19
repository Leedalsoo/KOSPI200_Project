
from __future__ import annotations

import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_runtime_evidence_supervisor import (
    ValidationOnlyRuntimeEvidenceSupervisor,
)
from application.composition.validation_only_runtime_invariant_checker import (
    ValidationOnlyRuntimeInvariantChecker,
)
from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from application.composition.validation_only_s2_source_evidence_providers import (
    ValidationOnlyS2AcceptedOriginalPrimaryProvider,
    ValidationOnlyS2NotionSourceReconciliationProvider,
)
from application.composition.validation_only_vssf_runtime_evidence_adapter import (
    ValidationOnlyVSSFRuntimeEvidenceAdapter,
)
from core.oms.track2_u19_recovery import U19RecoveryStatus, evaluate_u19_recovery
from tests.application.composition.test_validation_only_s2_scenario_alternative_provider import (
    ROOT,
    _provider,
)

TICK = SimpleNamespace(
    timestamp="2026-10-12T09:26:00+09:00",
    underlying_price=1034.62,
)
DECISIONS = ("No.1534", "No.1535", "No.1538", "No.1554", "No.1555")
SCENARIO_DIR = (
    "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
)


def _source_fixture(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    accepted_root = project / "data" / "accepted_market_data" / "runtime_v2"
    scenario_source = ROOT / "data" / "derived_scenario" / SCENARIO_DIR
    scenario_target = project / "data" / "derived_scenario" / SCENARIO_DIR
    accepted_root.mkdir(parents=True)
    scenario_target.parent.mkdir(parents=True)
    shutil.copytree(scenario_source, scenario_target)

    raw_root = tmp_path / "original" / "20261012"
    raw_root.mkdir(parents=True)
    raw_file = raw_root / "kis_vts_websocket_raw.jsonl"
    raw_file.write_bytes(b"read-only source fixture\n")
    raw_digest = hashlib.sha256(raw_file.read_bytes()).hexdigest()
    (raw_root / "kis_vts_websocket_raw.jsonl.manifest.json").write_text(
        json.dumps({
            "trading_date": "20261012",
            "source": "KIS_VTS_WEBSOCKET_RAW",
            "record_count": 1,
            "file_sha256": raw_digest,
        }),
        encoding="utf-8",
    )
    (raw_root / "manifest.json").write_text(
        json.dumps({
            "trading_date": "20261012",
            "files": [{
                "path": "kis_vts_websocket_raw.jsonl",
                "sha256": raw_digest,
            }],
        }),
        encoding="utf-8",
    )

    source_partition = (
        ROOT / "data" / "accepted_market_data" / "runtime_v2" / "20261012.jsonl"
    )
    rows = [
        json.loads(line)
        for line in source_partition.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        row["scenario_metadata"]["source_raw_sha256"] = raw_digest
    partition = accepted_root / "20261012.jsonl"
    partition.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    partition_hash = hashlib.sha256(partition.read_bytes()).hexdigest()
    (accepted_root / "manifest.json").write_text(
        json.dumps({
            "acceptance": "ACCEPTED_FOR_PROJECT_VERIFICATION",
            "registry_id": "KOSPI200_ACCEPTED_MARKET_DATA_20261114",
            "days": [{"date": "20261012", "sha256": partition_hash}],
        }),
        encoding="utf-8",
    )
    return project, tmp_path / "original"


def test_t9_primary_checks_exact_original_four_leg_coverage_without_synthesizing():
    scope = _provider(TICK.timestamp)
    primary = ValidationOnlyS2AcceptedOriginalPrimaryProvider(
        project_root=ROOT,
        scope_provider=scope,
    )

    assert primary.is_applicable(TICK)
    assert primary(TICK) is None
    assert primary.last_diagnostic == "ACCEPTED_ORIGINAL_SYNCHRONOUS_LEG_COVERAGE_0_OF_4"


def test_t9_reconciliation_verifies_raw_hash_and_all_source_anchor_ids(tmp_path):
    project, original = _source_fixture(tmp_path)
    scope = _provider(TICK.timestamp)
    reconciliation = ValidationOnlyS2NotionSourceReconciliationProvider(
        project_root=project,
        original_source_root=original,
        scope_provider=scope,
        notion_decision_refs=DECISIONS,
    )

    assert reconciliation.is_applicable(TICK)
    assert reconciliation(TICK, ()) is None
    assert reconciliation.last_diagnostic.startswith(
        "NOTION_SOURCE_RECONCILIATION_VERIFIED:No.1534,No.1535,No.1538,No.1554,No.1555"
    )
    assert "RAW_WS_SHA256_MATCHED" in reconciliation.last_diagnostic
    assert "ANCHORS_12_OF_12" in reconciliation.last_diagnostic
    assert "ORIGINAL_LEG_COVERAGE_0_OF_4" in reconciliation.last_diagnostic


def test_t9_reconciliation_requires_mandatory_no_1534(tmp_path):
    project, original = _source_fixture(tmp_path)
    scope = _provider(TICK.timestamp)

    try:
        ValidationOnlyS2NotionSourceReconciliationProvider(
            project_root=project,
            original_source_root=original,
            scope_provider=scope,
            notion_decision_refs=("No.1535", "No.1538", "No.1554", "No.1555"),
        )
    except ValueError as exc:
        assert "No.1534" in str(exc)
    else:
        raise AssertionError("No.1534 must remain mandatory")



def _pre_entry_alternative():
    bridge = SimpleNamespace(
        run_id="SYNTHETIC:T9:PRE_ENTRY",
        groups={},
        provenance={},
        execution_legs={},
        pending_legs={},
        position_lot_store=SimpleNamespace(
            history=lambda: (),
            open_lots=lambda: (),
            close_events=lambda: (),
        ),
        fee_ledger=SimpleNamespace(snapshot=lambda *, run_id: ()),
    )
    runtime = SimpleNamespace(
        account=SimpleNamespace(
            positions={},
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
    )
    adapter = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge,
        vssf_runtime=runtime,
        run_id="SYNTHETIC:T9:PRE_ENTRY",
    )
    return ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=ROOT,
        run_id="SYNTHETIC:T9:PRE_ENTRY",
        vssf_adapter=adapter,
    )

def test_t9_supervisor_runs_primary_then_source_reconciliation_then_synthetic_fallback(tmp_path):
    project, original = _source_fixture(tmp_path)
    alternative = _pre_entry_alternative()
    primary = ValidationOnlyS2AcceptedOriginalPrimaryProvider(
        project_root=ROOT,
        scope_provider=alternative,
    )
    reconciliation = ValidationOnlyS2NotionSourceReconciliationProvider(
        project_root=project,
        original_source_root=original,
        scope_provider=alternative,
        notion_decision_refs=DECISIONS,
    )

    class _StopSwitch:
        def __init__(self):
            self.calls = []

        def snapshot(self):
            return SimpleNamespace(status="ARMED")

        def evaluate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status="ARMED")

    class _Recovery:
        def recover(self, *, group_id, broker_snapshot, ledger_snapshot):
            return evaluate_u19_recovery(
                group_id=group_id,
                broker_snapshot=broker_snapshot,
                ledger_snapshot=ledger_snapshot,
            )

    stop = _StopSwitch()
    supervisor = ValidationOnlyRuntimeEvidenceSupervisor(
        stop_switch=stop,
        invariant_checker=ValidationOnlyRuntimeInvariantChecker(),
        u19_recovery_coordinator=_Recovery(),
        risk_guard_status_source=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                admission_allowed=True,
                kill_switch_engaged=False,
                reason="HEALTHY",
            )
        ),
        primary_provider=primary,
        reconciliation_provider=reconciliation,
        alternative_provider=alternative,
    )

    result = supervisor.evaluate(TICK)

    assert result.candidate_source == "PROVENANCE_PRESERVING_ALTERNATIVE"
    assert result.attempts[0] == (
        "PRIMARY_ACCEPTED_ORIGINAL:ACCEPTED_ORIGINAL_SYNCHRONOUS_LEG_COVERAGE_0_OF_4"
    )
    assert result.attempts[1].startswith(
        "NOTION_AND_SOURCE_RECONCILIATION:NOTION_SOURCE_RECONCILIATION_VERIFIED:"
    )
    assert result.attempts[2] == "PROVENANCE_PRESERVING_ALTERNATIVE:VALIDATED"
    assert result.u19_decision.status is U19RecoveryStatus.FLAT_CONFIRMED
    assert result.invariant_report.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert result.stop_snapshot.status == "ARMED"
    assert len(stop.calls) == 1

Path(r'C:\Users\white\Desktop\MovingProject\Q25_A8_R10\tests\application\composition\test_validation_only_s2_source_evidence_providers.py').write_text(Path(__file__).read_text(encoding='utf-8'), encoding='utf-8')
