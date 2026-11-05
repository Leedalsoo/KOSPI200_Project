from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from environments.high_speed.validation_only_track6_execution import Track6SyntheticExecutionGate


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data" / "derived_scenario" / "q25_a2_1_strategy6"
MANIFEST = ROOT / "reports" / "synth" / "Q25_A2_1_S6_SYN_EVT_MANIFEST_20261102.json"


@pytest.fixture(scope="module")
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


def plan():
    return SimpleNamespace(
        strategy_id="track6_daily_tail_insurance",
        purpose="DAILY_TAIL_INSURANCE_ENTRY",
    )


def test_synthetic_execution_gate_accepts_pair_within_frozen_budget(gate):
    gate.validate_group(plan(), [
        prepared_leg("put", price="0.4"),
        prepared_leg("call", price="0.4"),
    ])


def test_synthetic_execution_gate_rejects_pair_over_frozen_budget(gate):
    with pytest.raises(ValueError, match="PREMIUM_LIMIT_EXCEEDED"):
        gate.validate_group(plan(), [
            prepared_leg("put", price="0.7"),
            prepared_leg("call", price="0.6"),
        ])


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
