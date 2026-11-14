from __future__ import annotations

from hashlib import sha256
import json

import pytest

from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources
from environments.high_speed.validation_only_track2_runtime_adapter import (
    SYNTHETIC_ID_PREFIX,
    Track2ValidationOnlyRuntimeAdapter,
)


def _dataset(tmp_path):
    dataset = tmp_path / "runtime_v2"
    dataset.mkdir()
    row = {
        "schema": "reference-canonical-market-tick-v1",
        "source": "KIS_VTS_WEBSOCKET_CANONICAL_V2+ACCEPTED_ENRICHMENT",
        "dataset": "KOSPI200_ACCEPTED_MARKET_DATA_20261114",
        "provenance": "DERIVED_SCENARIO",
        "provider": "KIS_WS_KRX_REFERENCE_ACCEPTED_ENRICHMENT",
        "tick": {
            "timestamp": "2026-10-12T09:00:45+09:00",
            "underlying_price": 1035.93,
            "underlying_symbol": "KOSPI200",
            "strike_price": 1040.0,
            "option_type": "CALL",
            "contract_multiplier": 250000.0,
            "bid_price": 33.6,
            "ask_price": 43.9,
            "last_price": 43.85,
            "volume": 1,
            "seq_id": 1,
            "expiry": "20261112",
            "symbol": "B01611A14",
            "instrument_id": "B01611A14",
            "source_instrument_code": "B01611A14",
            "contract_class": "monthly",
        },
        "scenario_metadata": {
            "accepted_for_project_verification": True,
            "trading_date": "20261012",
            "source_observation_id": "obs-1",
            "synthetic_order_book_top": {"bid_quantity": 209, "ask_quantity": 97, "depth_levels": 1},
        },
    }
    payload = (json.dumps(row, separators=(",", ":")) + "\n").encode()
    (dataset / "20261012.jsonl").write_bytes(payload)
    manifest = {
        "schema_version": "accepted-market-data-runtime-v2",
        "registry_id": "KOSPI200_ACCEPTED_MARKET_DATA_20261114",
        "acceptance": "ACCEPTED_FOR_PROJECT_VERIFICATION",
        "rows_total": 1,
        "days": [{"date": "20261012", "rows": 1, "sha256": sha256(payload).hexdigest()}],
    }
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return dataset, manifest_path


def test_adapts_original_code_to_stable_synthetic_namespace_without_standard_id(tmp_path):
    dataset, manifest = _dataset(tmp_path)
    adapter = Track2ValidationOnlyRuntimeAdapter(
        dataset=dataset,
        manifest_path=manifest,
        profile_path="config/validation_only/track2/synthetic_scenario_profile.v1.json",
    )
    row = json.loads((dataset / "20261012.jsonl").read_text(encoding="utf-8"))

    adapted = adapter.adapt_record(row)
    tick = adapted["tick"]

    assert tick["instrument_id"].startswith(SYNTHETIC_ID_PREFIX)
    assert tick["synthetic_contract_id"] == tick["instrument_id"]
    assert tick["source_instrument_code"] == "B01611A14"
    assert tick["instrument_identity_status"] == "SYNTHETIC_IDENTITY_ONLY"
    assert adapted["scenario_metadata"]["contract_identity_authority"] == "SYNTHETIC_ONLY"
    assert row["tick"]["instrument_id"] == "B01611A14"


def test_applies_fixture_only_to_one_strategy_instance_and_keeps_class_defaults_blocked(tmp_path):
    dataset, manifest = _dataset(tmp_path)
    adapter = Track2ValidationOnlyRuntimeAdapter(
        dataset=dataset,
        manifest_path=manifest,
        profile_path="config/validation_only/track2/synthetic_scenario_profile.v1.json",
    )
    strategy = Track2AsymmetricTrap()
    sources = SyntheticRuntimeSources()

    adapter.apply_to_strategy(strategy, synthetic_sources=sources)

    assert strategy.runtime_config_verified is True
    assert strategy.risk_limits_available is True
    assert str(strategy.STOP_LOSS_RATIO) == "-0.50"
    assert Track2AsymmetricTrap().runtime_config_verified is False
    assert Track2AsymmetricTrap().risk_limits_available is False


def test_rejects_dataset_partition_hash_mismatch(tmp_path):
    dataset, manifest = _dataset(tmp_path)
    row_path = dataset / "20261012.jsonl"
    row_path.write_text(row_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="PARTITION_HASH_MISMATCH"):
        Track2ValidationOnlyRuntimeAdapter(
            dataset=dataset,
            manifest_path=manifest,
            profile_path="config/validation_only/track2/synthetic_scenario_profile.v1.json",
        )



def test_entry_identity_validator_rejects_sidecar_role_mismatch():
    from decimal import Decimal
    from types import SimpleNamespace

    from verification.track2_synthetic_quote_scenario import KIS_OPTION_PRODUCT_SPEC_URL
    from contracts.kis_option_product_spec import KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER

    instrument_id = SYNTHETIC_ID_PREFIX + "role-test"
    row = {
        "instrument_id": instrument_id,
        "contract_multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
        "contract_multiplier_source": KIS_OPTION_PRODUCT_SPEC_URL,
    }
    adapter = object.__new__(Track2ValidationOnlyRuntimeAdapter)
    adapter.quote_scenario_rows = (row,)
    adapter.quote_scenario_identity_ids = frozenset({instrument_id})
    adapter._active_candidate_role_by_instrument_id = {instrument_id: "inner_put"}
    stored = SimpleNamespace(
        instrument_id=instrument_id, identity_source="SYNTHETIC:DERIVED_SCENARIO",
        expiry="20261112", option_type="PUT", strike=Decimal("100"),
        contract_multiplier=KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
    )
    master = SimpleNamespace(
        shrn_iscd=instrument_id, stnd_iscd=None, instrument_family="STANDARD",
        product_series="MONTHLY", expiry="20261112", option_type="PUT",
        strike=Decimal("100"), contract_multiplier=KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
    )
    matching_plan = SimpleNamespace(
        strategy_id="track2_asymmetric_trap", purpose="ASYMMETRIC_TRAP_NARROW",
        legs=(SimpleNamespace(leg_id="inner_put", option_type="PUT", strike=Decimal("100")),),
    )
    mismatching_plan = SimpleNamespace(
        strategy_id="track2_asymmetric_trap", purpose="ASYMMETRIC_TRAP_NARROW",
        legs=(SimpleNamespace(leg_id="outer_put", option_type="PUT", strike=Decimal("100")),),
    )
    assert adapter.validate_execution_identity(matching_plan, stored, master) is True
    assert adapter.validate_execution_identity(mismatching_plan, stored, master) is False



def test_preflight_candidate_role_mapping_matches_execution_plan_contract():
    from decimal import Decimal
    from environments.high_speed.validation_only_track2_runtime_adapter import _track2_preflight_legs_from_long_short

    actual = _track2_preflight_legs_from_long_short(
        {"put": "1032.5", "call": "1037.5"},
        {"put": "1027.5", "call": "1042.5"},
    )
    assert actual == (
        ("PUT", Decimal("1032.5")),
        ("CALL", Decimal("1037.5")),
        ("PUT", Decimal("1027.5")),
        ("CALL", Decimal("1042.5")),
    )
from datetime import datetime
from types import SimpleNamespace
from decimal import Decimal


def test_validation_only_pnl_evidence_uses_profile_costs_and_verifies_all_four_synthetic_mid_quotes(tmp_path):
    dataset, manifest = _dataset(tmp_path)
    adapter = Track2ValidationOnlyRuntimeAdapter(
        dataset=dataset, manifest_path=manifest,
        profile_path="config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json",
    )
    observed = datetime.fromisoformat("2026-10-12T09:26:00+09:00")
    ids = tuple(f"{SYNTHETIC_ID_PREFIX}pnl-{i}" for i in range(4))
    adapter.quote_scenario_identity_ids = frozenset(ids)
    legs = tuple(SimpleNamespace(
        leg_id=f"leg-{i}", instrument_id=ids[i], quantity=1,
        contract_multiplier=250000, mark_source="BID_ASK_MID",
        quote_bid=40.0, quote_ask=41.0, quote_observed_at=observed,
    ) for i in range(4))
    snapshot = SimpleNamespace(
        complete=True, legs=legs, fees=0.0, slippage=None,
        realized_pnl=0.0, unrealized_pnl=-100000.0,
    )
    reports = tuple(SimpleNamespace(leg_id=f"leg-{i}", filled_quantity=1) for i in range(4))
    market = SimpleNamespace(option_quotes_by_instrument_id={
        instrument_id: {"source": "SYNTHETIC:DERIVED_SCENARIO", "timestamp": observed.isoformat()}
        for instrument_id in ids
    })
    sources = SimpleNamespace(_tick=SimpleNamespace(timestamp=observed.isoformat()))

    evidence = adapter.pnl_evidence(
        snapshot=snapshot, reports=reports, is_entry=True,
        market=market, synthetic_sources=sources,
    )

    assert evidence["fees"] == pytest.approx(4000.0)
    assert evidence["slippage"] == pytest.approx(50000.0)
    assert evidence["net_pnl"] == pytest.approx(-154000.0)
    assert evidence["quote_freshness_verified"] is True


def test_validation_only_pnl_evidence_fails_closed_on_stale_quote(tmp_path):
    dataset, manifest = _dataset(tmp_path)
    adapter = Track2ValidationOnlyRuntimeAdapter(
        dataset=dataset, manifest_path=manifest,
        profile_path="config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json",
    )
    observed = datetime.fromisoformat("2026-10-12T09:00:00+09:00")
    current = datetime.fromisoformat("2026-10-12T09:00:10+09:00")
    ids = tuple(f"{SYNTHETIC_ID_PREFIX}stale-{i}" for i in range(4))
    adapter.quote_scenario_identity_ids = frozenset(ids)
    legs = tuple(SimpleNamespace(
        leg_id=f"leg-{i}", instrument_id=ids[i], quantity=1,
        contract_multiplier=250000, mark_source="BID_ASK_MID",
        quote_bid=40.0, quote_ask=41.0, quote_observed_at=observed,
    ) for i in range(4))
    snapshot = SimpleNamespace(
        complete=True, legs=legs, fees=4000.0, slippage=50000.0,
        realized_pnl=0.0, unrealized_pnl=-100000.0,
    )
    market = SimpleNamespace(option_quotes_by_instrument_id={
        instrument_id: {"source": "SYNTHETIC:DERIVED_SCENARIO", "timestamp": observed.isoformat()}
        for instrument_id in ids
    })
    sources = SimpleNamespace(_tick=SimpleNamespace(timestamp=current.isoformat()))

    evidence = adapter.pnl_evidence(
        snapshot=snapshot, reports=(), is_entry=False,
        market=market, synthetic_sources=sources,
    )
    assert evidence["quote_freshness_verified"] is None
