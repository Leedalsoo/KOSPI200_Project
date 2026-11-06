from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from environments.high_speed.validation_only_track6_execution import Track6SyntheticExecutionGate


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data" / "derived_scenario" / "q25_a2_1_strategy6"
MANIFEST = ROOT / "reports" / "synth" / "Q25_A2_1_S6_SYN_EVT_MANIFEST_20261102.json"


@pytest.fixture
def gate():
    return Track6SyntheticExecutionGate(dataset=DATASET, manifest_path=MANIFEST)


def prepared_leg(name: str, *, price: str, identity_id: str | None = None):
    option_type = name.upper()
    leg = SimpleNamespace(
        leg_id=name, side="BUY", quantity=1, requested_price=Decimal(price),
    )
    identity = SimpleNamespace(
        instrument_id=identity_id or f"SYNTHETIC_CONTRACT:{name}",
        identity_source="OPTION_MASTER", option_type=option_type,
        contract_multiplier=Decimal("250000"),
    )
    return (leg, identity, f"client-{name}", None, None, Decimal("0.4"), Decimal("0.5"))


def plan(group_id="S6-TEST-GROUP"):
    return SimpleNamespace(
        group_id=group_id,
        strategy_id="track6_daily_tail_insurance",
        purpose="DAILY_TAIL_INSURANCE_ENTRY",
    )


def test_synthetic_execution_gate_accepts_pair_within_frozen_budget(gate):
    gate.validate_group(plan(), [
        prepared_leg("put", price="0.4"),
        prepared_leg("call", price="0.4"),
    ])


def test_synthetic_execution_gate_rejects_pair_over_approved_validation_budget(gate):
    with pytest.raises(ValueError, match="PREMIUM_LIMIT_EXCEEDED"):
        gate.validate_group(plan(), [
            prepared_leg("put", price="1.3"),
            prepared_leg("call", price="1.2"),
        ])


def test_synthetic_execution_gate_accepts_original_602500_pair_and_audits_operational_overage(gate):
    gate.bind_run_id("Q25-S6-RISK-BUDGET-TEST")
    gate.validate_group(plan(), [
        prepared_leg("put", price="1.15"),
        prepared_leg("call", price="1.26"),
    ])

    assert gate.evidence.max_premium_krw == 622_500
    assert gate.evidence.max_loss_krw == 622_500
    assert gate.evidence.operational_reference_limit_krw == 250_000
    assert gate.risk_audit_records[-1] == {
        "group_id": "S6-TEST-GROUP",
        "group_leg_count": 2,
        "group_pair_complete": True,
        "group_leg_premiums_krw": {"put": "287500.00", "call": "315000.00"},
        "computed_gross_premium_krw": "602500.00",
        "computed_max_loss_krw": "602500.00",
        "computed_concurrent_exposure_krw": "602500.00",
        "operational_reference_overage_krw": "352500.00",
        "validation_budget_overage_krw": "0",
        "run_id": "Q25-S6-RISK-BUDGET-TEST",
        "scenario_id": gate.evidence.scenario_id,
        "manifest_sha256": gate.evidence.manifest_sha256,
        "dataset_sha256": gate.evidence.dataset_sha256,
    }


def test_synthetic_execution_gate_rejects_generated_non_dataset_identity(gate):
    with pytest.raises(ValueError, match="LEG_CONTRACT_INVALID"):
        gate.validate_group(plan(), [
            prepared_leg("put", price="0.2", identity_id="SYN-20261105-PUT-487.5"),
            prepared_leg("call", price="0.2"),
        ])



def test_synthetic_execution_gate_allows_identity_bound_per_leg_exit_without_entry_budget(gate):
    exit_plan = SimpleNamespace(
        strategy_id="track6_daily_tail_insurance",
        purpose="DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT",
    )
    leg = SimpleNamespace(leg_id="close-put-001", side="SELL", quantity=1)
    identity = SimpleNamespace(
        instrument_id="SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5",
        identity_source="OPTION_MASTER", option_type="PUT",
        contract_multiplier=Decimal("250000"),
    )
    gate.validate_group(exit_plan, [
        (leg, identity, "client-close-put", None, None, Decimal("0.5"), Decimal("0.6")),
    ])

def test_synthetic_execution_gate_admits_sequential_single_legs_with_cumulative_pair_budget(gate):
    group = plan("S6-SEQUENTIAL-GROUP")
    gate.validate_group(group, [prepared_leg("put", price="1.15")])
    assert gate.risk_audit_records[-1]["computed_gross_premium_krw"] == "287500.00"
    assert gate.risk_audit_records[-1]["group_pair_complete"] is False

    gate.validate_group(group, [prepared_leg("call", price="1.26")])
    audit = gate.risk_audit_records[-1]
    assert audit["computed_gross_premium_krw"] == "602500.00"
    assert audit["group_pair_complete"] is True
    assert audit["group_leg_count"] == 2


def test_synthetic_execution_gate_blocks_second_sequential_leg_if_cumulative_cap_exceeded(gate):
    group = plan("S6-SEQUENTIAL-OVER-BUDGET")
    gate.validate_group(group, [prepared_leg("put", price="1.30")])
    with pytest.raises(ValueError, match="PREMIUM_LIMIT_EXCEEDED"):
        gate.validate_group(group, [prepared_leg("call", price="1.20")])
    assert gate.risk_audit_records[-1]["computed_gross_premium_krw"] == "625000.00"
    assert gate._group_premium_by_leg[group.group_id].keys() == {"put"}


def test_synthetic_execution_gate_allows_idempotent_revalidation_of_same_sequential_leg(gate):
    group = plan("S6-SEQUENTIAL-IDEMPOTENT")
    leg = prepared_leg("put", price="1.15")
    gate.validate_group(group, [leg])
    gate.validate_group(group, [leg])
    assert gate.risk_audit_records[-1]["computed_gross_premium_krw"] == "287500.00"
    assert gate.risk_audit_records[-1]["group_leg_count"] == 1


def test_synthetic_execution_gate_releases_group_only_when_runtime_confirms_flat(gate):
    group = plan("S6-SEQUENTIAL-RELEASE")
    gate.validate_group(group, [prepared_leg("put", price="1.15")])
    assert group.group_id in gate._group_premium_by_leg
    gate.release_group(group.group_id)
    assert group.group_id not in gate._group_premium_by_leg
