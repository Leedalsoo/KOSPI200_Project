from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.market_calendar_hub import MarketCalendarHub
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources
from environments.high_speed.validation_only_track7_execution import S7ValidationOnlyRuntimeAdapter
from environments.high_speed.validation_only_trading_calendar import load_validation_only_trading_calendar

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"


def _adapter() -> S7ValidationOnlyRuntimeAdapter:
    return S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET, manifest_path=MANIFEST, risk_profile_path=PROFILE,
    )


def _prepared_leg(leg_id: str, expiry: str, ask: str):
    option_type = leg_id.upper()
    strike = Decimal("487.5") if option_type == "PUT" else Decimal("512.5")
    identity = SimpleNamespace(
        instrument_id=f"SYNTHETIC_CONTRACT:strategy7_weekly:{expiry}:{option_type}:{strike}",
        option_type=option_type, strike=strike, expiry=expiry,
        contract_multiplier=Decimal("250000"), identity_source="OPTION_MASTER",
    )
    leg = SimpleNamespace(leg_id=leg_id, side="BUY", quantity=1)
    return (leg, identity, f"client-{leg_id}", object(), object(), Decimal(ask)-Decimal("0.12"), Decimal(ask))


def test_s7_validation_gate_binds_manifest_and_keeps_operational_defaults_off():
    adapter = _adapter()
    strategy = Track7VolatilitySkewWeeklyInsurance()
    assert strategy.runtime_config_verified is False
    assert strategy.risk_limits_available is False

    adapter.bind_run_id("S7-UNIT-TEST")
    adapter.apply_to_strategy(strategy, synthetic_sources=SyntheticRuntimeSources())

    assert strategy.runtime_config_verified is True
    assert strategy.risk_limits_available is True
    assert Track7VolatilitySkewWeeklyInsurance().runtime_config_verified is False
    assert Track7VolatilitySkewWeeklyInsurance().risk_limits_available is False


def test_s7_validation_gate_tracks_two_expiry_groups_and_releases_only_requested_group():
    adapter = _adapter()
    adapter.bind_run_id("S7-RISK-UNIT-TEST")
    first = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY", group_id="group-mon",
    )
    second = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY", group_id="group-thu",
    )
    adapter.validate_group(first, [
        _prepared_leg("put", "20261109", "1.26"),
        _prepared_leg("call", "20261109", "1.16"),
    ])
    adapter.validate_group(second, [
        _prepared_leg("put", "20261112", "2.42"),
        _prepared_leg("call", "20261112", "2.20"),
    ])

    assert set(adapter._reserved) == {"group-mon", "group-thu"}
    assert adapter.risk_audit_records[0]["computed_gross_premium_krw"] == "605000.00"
    assert adapter.risk_audit_records[1]["computed_concurrent_exposure_krw"] == "1760000.00"
    assert all(item["status"] == "ALLOW" for item in adapter.risk_audit_records)

    adapter.release_group("group-mon")
    assert set(adapter._reserved) == {"group-thu"}
    adapter.release_group("group-thu")
    assert not adapter._reserved


def test_validation_calendar_entry_start_is_expiry_scoped():
    calendar = load_validation_only_trading_calendar(MANIFEST, DATASET / "20261103.jsonl")
    hub = MarketCalendarHub(calendar)

    assert hub.flags(date(2026, 11, 2), date(2026, 11, 9))[0] is True
    assert hub.flags(date(2026, 11, 5), date(2026, 11, 9))[0] is False
    assert hub.flags(date(2026, 11, 2), date(2026, 11, 12))[0] is False
    assert hub.flags(date(2026, 11, 5), date(2026, 11, 12))[0] is True


def test_prime_option_quote_does_not_advance_runtime_tick_or_history():
    sources = SyntheticRuntimeSources()
    timestamp = "2026-11-05T08:45:00+09:00"
    for option_type, strike in (("PUT", "487.5"), ("CALL", "512.5")):
        tick = SimpleNamespace(
            instrument_id=f"SYNTHETIC_CONTRACT:strategy7_weekly:20261112:{option_type}:{strike}",
            timestamp=timestamp, bid_price="1.00", ask_price="1.10", last_price="1.05",
            option_type=option_type, strike_price=strike, expiry="20261112", volume=10,
        )
        sources.prime_option_quote(tick)

    assert len(sources._option_quote_cache) == 2
    assert sources._tick is None
    assert len(sources._history) == 0
    assert all(value["timestamp"].isoformat() == timestamp for value in sources._option_quote_cache.values())
def test_s7_validation_gate_reserves_put_then_call_with_one_shared_group():
    adapter = _adapter()
    adapter.bind_run_id("S7-SEQUENTIAL-RISK-TEST")
    put_plan = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY_PUT", group_id="group-sequential",
    )
    call_plan = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY_CALL", group_id="group-sequential",
    )
    adapter.validate_group(put_plan, [_prepared_leg("put", "20261109", "1.26")])
    assert adapter._reserved["group-sequential"] == {"put": Decimal("315000.00")}
    adapter.validate_group(call_plan, [_prepared_leg("call", "20261109", "1.16")])

    assert adapter._reserved["group-sequential"] == {
        "put": Decimal("315000.00"), "call": Decimal("290000.00")
    }
    assert adapter.risk_audit_records[-1]["computed_gross_premium_krw"] == "605000.00"
