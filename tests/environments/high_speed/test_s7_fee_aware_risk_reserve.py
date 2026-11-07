from pathlib import Path
from decimal import Decimal

from environments.high_speed.validation_only_option_fee_model import calculate_option_fee
from environments.high_speed.validation_only_track7_execution import S7ValidationOnlyRuntimeAdapter
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"


def test_s7_entry_risk_reserves_standard_reference_fee_with_premium():
    adapter = S7ValidationOnlyRuntimeAdapter(dataset=DATASET, manifest_path=MANIFEST, risk_profile_path=PROFILE)
    adapter.bind_run_id("S7-FEE-RESERVE-TEST")
    plan = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY_PUT",
        group_id="group-fee",
    )
    strike = Decimal("487.5")
    identity = SimpleNamespace(
        instrument_id=f"SYNTHETIC_CONTRACT:strategy7_weekly:20261109:PUT:{strike}",
        option_type="PUT", strike=strike, expiry="20261109",
        contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
    )
    leg = SimpleNamespace(leg_id="put", side="BUY", quantity=1)
    prepared = [(leg, identity, "client-put", object(), object(), Decimal("1.14"), Decimal("1.26"))]

    adapter.validate_group(plan, prepared)

    expected_fee = calculate_option_fee("1.26", 250000, 1)["total_fee_krw"]
    audit = adapter.risk_audit_records[-1]
    assert adapter._reserved_entry_fees["group-fee"]["put"] == Decimal(str(expected_fee))
    assert Decimal(audit["computed_entry_fee_reserve_krw"]) == Decimal(str(expected_fee))
    assert Decimal(audit["computed_max_loss_krw"]) == Decimal("315000") + Decimal(str(expected_fee))
    assert Decimal(audit["computed_concurrent_exposure_including_entry_fees_krw"]) == Decimal("315000") + Decimal(str(expected_fee))

    adapter.release_group("group-fee")
    assert not adapter._reserved_entry_fees
