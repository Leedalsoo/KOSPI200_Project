from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.composition.track9_validation_only_contract_adapter import (
    Track9SyntheticContractProfile,
    Track9SyntheticProfileError,
)
from core.strategy.track9_independent_policy import select_nearest_expiry_atm_pair

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"


def identity(symbol, expiry, side, strike, family="STANDARD"):
    return SimpleNamespace(
        shrn_iscd=symbol,
        expiry=expiry,
        option_type=side,
        strike=Decimal(str(strike)),
        instrument_family=family,
    )


def test_profile_is_explicitly_synthetic_and_production_disabled():
    profile = Track9SyntheticContractProfile.load(PROFILE_PATH)
    assert profile.provenance == "SYNTHETIC"
    assert profile.contract_multiplier == Decimal("100000")
    assert profile.tradable is True


def test_adapter_preserves_master_identity_and_injects_only_synthetic_fields():
    profile = Track9SyntheticContractProfile.load(PROFILE_PATH)
    candidates = profile.build_candidates((
        identity("S9P1", "2026-11-12", "PUT", "500"),
        identity("S9C1", "2026-11-12", "CALL", "500"),
        identity("S9PM", "2026-11-10", "PUT", "500", family="MINI"),
    ))
    assert [item.symbol for item in candidates] == ["S9P1", "S9C1"]
    assert {item.expiry for item in candidates} == {date(2026, 11, 12)}
    assert {item.strike for item in candidates} == {Decimal("500")}
    assert all(item.contract_multiplier == Decimal("100000") for item in candidates)
    assert all(item.tradable is True for item in candidates)


def test_synthetic_candidates_run_through_independent_s9_p0_pair_policy():
    profile = Track9SyntheticContractProfile.load(PROFILE_PATH)
    candidates = profile.build_candidates((
        identity("S9P1", "2026-11-12", "PUT", "500"),
        identity("S9C1", "2026-11-12", "CALL", "500"),
        identity("S9P2", "2026-11-19", "PUT", "501"),
        identity("S9C2", "2026-11-19", "CALL", "501"),
    ))
    pair = select_nearest_expiry_atm_pair(
        candidates, underlying_price=Decimal("500.4"), as_of_date=date(2026, 11, 9)
    )
    assert pair.expiry == date(2026, 11, 12)
    assert pair.strike == Decimal("500")
    assert pair.contract_multiplier == Decimal("100000")


def test_profile_rejects_any_production_or_order_permission(tmp_path):
    import json

    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["orders_allowed"] = True
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Track9SyntheticProfileError, match="PRODUCTION_GUARD"):
        Track9SyntheticContractProfile.load(path)


def test_profile_rejects_non_synthetic_or_non_validation_only_source(tmp_path):
    import json

    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["provenance"] = "OFFICIAL"
    path = tmp_path / "not_synthetic.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Track9SyntheticProfileError, match="VALIDATION_ONLY_REQUIRED"):
        Track9SyntheticContractProfile.load(path)


def test_adapter_rejects_duplicate_contract_symbols():
    profile = Track9SyntheticContractProfile.load(PROFILE_PATH)
    with pytest.raises(Track9SyntheticProfileError, match="DUPLICATE"):
        profile.build_candidates((
            identity("S9P1", "2026-11-12", "PUT", "500"),
            identity("S9P1", "2026-11-12", "PUT", "500"),
        ))