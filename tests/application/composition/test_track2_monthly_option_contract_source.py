from datetime import date
import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from application.composition.track2_option_contract_source import Track2OptionContractSource
from contracts.kis_option_product_spec import KIS_MONTHLY_OPTION_EXPIRY_RULE_ID, KIS_MONTHLY_OPTION_EXPIRY_SOURCE, KIS_OPTION_PRODUCT_SPEC_URL
from core.option.option_master import KisOptionContractIdentity


def identity(code, expiry, option_type, strike, *, series="MONTHLY", family="STANDARD"):
    return KisOptionContractIdentity(
        shrn_iscd=code,
        stnd_iscd=None,
        expiry=expiry,
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
        instrument_family=family,
        product_series=series,
        expiry_source="KIS_REST:futs_last_tr_date",
        expiry_observed_at="2026-11-09T00:00:00+00:00",
        expiry_endpoint="/uapi/domestic-futureoption/v1/quotations/inquire-price",
        expiry_tr_id="FHMIF10000000",
        expiry_response_sha256="c" * 64,
        expiry_master_sha256="a" * 64,
        master_sha256="a" * 64,
    )


class Master:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def list_contract_identities(self, expiry=None):
        if expiry is None:
            return self.rows
        exact = str(expiry).replace("-", "")[:8]
        return tuple(x for x in self.rows if x.expiry == exact)

    def get_contract_identity(self, instrument_id):
        return next((x for x in self.rows if x.shrn_iscd == instrument_id), None)


def test_nearest_expiry_ignores_weekly_and_nonstandard_contracts():
    master = Master((
        identity("WEEKLY", "20261112", "PUT", 500, series="THURSDAY_WEEKLY"),
        identity("MINI", "20261119", "PUT", 500, family="MINI"),
        identity("MONTHLY", "20261210", "PUT", 500),
    ))

    assert Track2OptionContractSource(master).nearest_expiry(as_of=date(2026, 11, 10)) == "20261210"


def test_monthly_selection_uses_lower_strike_when_atm_distance_ties():
    rows = []
    for strike in (490, 510):
        rows.extend((
            identity(f"P{strike}", "20261210", "PUT", strike),
            identity(f"C{strike}", "20261210", "CALL", strike),
        ))
    rows.append(identity("WEEKLY-P", "20261210", "PUT", 500, series="MONDAY_WEEKLY"))
    rows.append(identity("WEEKLY-C", "20261210", "CALL", 500, series="MONDAY_WEEKLY"))

    selected = Track2OptionContractSource(Master(rows)).select(
        expiry="20261210", current_price=Decimal("500")
    )

    assert selected.atm_strike == Decimal("490")
    assert selected.put.shrn_iscd == "P490"
    assert selected.call.shrn_iscd == "C490"


def test_nearest_expiry_fails_when_only_weekly_or_mini_series_exist():
    master = Master((
        identity("WEEKLY", "20261112", "PUT", 500, series="THURSDAY_WEEKLY"),
        identity("MINI", "20261119", "PUT", 500, family="MINI"),
    ))

    with pytest.raises(ValueError, match="TRACK2_OPTION_EXPIRY_NOT_FOUND"):
        Track2OptionContractSource(master).nearest_expiry(as_of=date(2026, 11, 10))


def test_select_fails_closed_when_expiry_has_no_monthly_standard_pair():
    master = Master((
        identity("WEEKLY-P", "20261210", "PUT", 500, series="MONDAY_WEEKLY"),
        identity("WEEKLY-C", "20261210", "CALL", 500, series="MONDAY_WEEKLY"),
    ))

    with pytest.raises(ValueError, match="TRACK2_LISTED_STRIKE_NOT_FOUND"):
        Track2OptionContractSource(master).select(
            expiry="20261210", current_price=Decimal("500")
        )


def test_resolve_identity_binds_exact_monthly_standard_contract():
    monthly = identity("MONTHLY-P-490", "20261210", "PUT", 490)
    weekly = identity("WEEKLY-P-490", "20261210", "PUT", 490, series="THURSDAY_WEEKLY")
    source = Track2OptionContractSource(Master((weekly, monthly)))

    selected = source.resolve_identity(
        expiry="20261210", option_type="PUT", strike=Decimal("490")
    )

    assert selected is monthly
    assert selected.product_series == "MONTHLY"
    assert selected.instrument_family == "STANDARD"


def test_resolve_identity_blocks_weekly_or_mini_substitution():
    source = Track2OptionContractSource(Master((
        identity("WEEKLY-P-490", "20261210", "PUT", 490, series="THURSDAY_WEEKLY"),
    )))

    with pytest.raises(ValueError, match="TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE"):
        source.resolve_identity(
            expiry="20261210", option_type="PUT", strike=Decimal("490")
        )


def test_resolve_identity_blocks_missing_multiplier():
    item = KisOptionContractIdentity(
        shrn_iscd="MONTHLY-P-490",
        stnd_iscd=None,
        expiry="20261210",
        option_type="PUT",
        strike=Decimal("490"),
        contract_multiplier=None,
        instrument_family="STANDARD",
        product_series="MONTHLY",
        expiry_source="KIS_REST:futs_last_tr_date",
        expiry_observed_at="2026-11-09T00:00:00+00:00",
        expiry_endpoint="/uapi/domestic-futureoption/v1/quotations/inquire-price",
        expiry_tr_id="FHMIF10000000",
        expiry_response_sha256="c" * 64,
        expiry_master_sha256="a" * 64,
        master_sha256="a" * 64,
    )
    source = Track2OptionContractSource(Master((item,)))

    with pytest.raises(ValueError, match="TRACK2_CONTRACT_MULTIPLIER_REQUIRED"):
        source.resolve_identity(
            expiry="20261210", option_type="PUT", strike=Decimal("490")
        )


def test_resolve_identity_blocks_duplicate_monthly_contract_identity():
    rows = (
        identity("MONTHLY-P-490-A", "20261210", "PUT", 490),
        identity("MONTHLY-P-490-B", "20261210", "PUT", 490),
    )
    source = Track2OptionContractSource(Master(rows))

    with pytest.raises(ValueError, match="TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE"):
        source.resolve_identity(
            expiry="20261210", option_type="PUT", strike=Decimal("490")
        )


def test_factory_binds_all_four_track2_legs_from_monthly_option_master():
    source = Path("application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8")
    assert "track2_option_contract_source.resolve_identity(" in source
    assert "instrument_identity=OptionInstrumentIdentity(" in source
    assert "return replace(plan, legs=tuple(bound_legs))" in source


def test_virtual_bridge_accepts_matching_stored_monthly_standard_identity():
    from contracts.types import OptionInstrumentIdentity
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from core.oms.multi_leg_plan import build_trap_plan

    monthly = identity("MONTHLY-P-490", "20261210", "PUT", 490)
    master = Master((monthly,))
    plan = build_trap_plan(
        group_id="s2-monthly-identity",
        strategy_id="track2_asymmetric_trap",
        purpose="ASYMMETRIC_TRAP_WIDE",
        short_put=Decimal("490"), short_call=Decimal("510"),
        long_put=Decimal("495"), long_call=Decimal("505"), quantity=1,
    )
    stored = OptionInstrumentIdentity(
        instrument_id=monthly.shrn_iscd, symbol=monthly.shrn_iscd,
        expiry=monthly.expiry, option_type=monthly.option_type,
        strike=monthly.strike, contract_multiplier=monthly.contract_multiplier,
        identity_source="OPTION_MASTER",
    )
    from dataclasses import replace
    plan = replace(plan, legs=(replace(plan.legs[0], instrument_identity=stored), *plan.legs[1:]))
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.option_master = master

    assert bridge.identity_for_leg(plan, plan.legs[0]) is stored


def test_virtual_bridge_blocks_stored_identity_multiplier_mismatch():
    from contracts.types import OptionInstrumentIdentity
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from core.oms.multi_leg_plan import build_trap_plan
    from dataclasses import replace

    monthly = identity("MONTHLY-P-490", "20261210", "PUT", 490)
    master = Master((monthly,))
    plan = build_trap_plan(
        group_id="s2-monthly-multiplier",
        strategy_id="track2_asymmetric_trap",
        purpose="ASYMMETRIC_TRAP_WIDE",
        short_put=Decimal("490"), short_call=Decimal("510"),
        long_put=Decimal("495"), long_call=Decimal("505"), quantity=1,
    )
    stored = OptionInstrumentIdentity(
        instrument_id=monthly.shrn_iscd, symbol=monthly.shrn_iscd,
        expiry=monthly.expiry, option_type=monthly.option_type,
        strike=monthly.strike, contract_multiplier=Decimal("50000"),
        identity_source="OPTION_MASTER",
    )
    plan = replace(plan, legs=(replace(plan.legs[0], instrument_identity=stored), *plan.legs[1:]))
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.option_master = master

    with pytest.raises(ValueError, match="TRACK2_STORED_IDENTITY_NOT_AUTHORITATIVE_MONTHLY_STANDARD"):
        bridge.identity_for_leg(plan, plan.legs[0])


def test_all_four_entry_legs_resolve_from_one_exact_monthly_standard_series():
    from core.oms.multi_leg_plan import build_trap_plan

    rows = tuple(
        identity(f"{option_type}-{strike}", "20261210", option_type, strike)
        for strike in (490, 495, 505, 510)
        for option_type in ("PUT", "CALL")
    )
    source = Track2OptionContractSource(Master(rows))
    plan = build_trap_plan(
        group_id="s2-four-contract-monthly",
        strategy_id="track2_asymmetric_trap",
        purpose="ASYMMETRIC_TRAP_WIDE",
        short_put=Decimal("490"), short_call=Decimal("510"),
        long_put=Decimal("495"), long_call=Decimal("505"), quantity=1,
    )

    resolved = tuple(
        source.resolve_identity(
            expiry="20261210", option_type=leg.option_type, strike=leg.strike
        )
        for leg in plan.legs
    )

    assert len(resolved) == 4
    assert len({x.shrn_iscd for x in resolved}) == 4
    assert {x.product_series for x in resolved} == {"MONTHLY"}
    assert {x.instrument_family for x in resolved} == {"STANDARD"}


def test_four_leg_monthly_resolution_blocks_if_one_strike_is_missing():
    from core.oms.multi_leg_plan import build_trap_plan

    rows = tuple(
        identity(f"{option_type}-{strike}", "20261210", option_type, strike)
        for strike in (490, 495, 505)
        for option_type in ("PUT", "CALL")
    )
    source = Track2OptionContractSource(Master(rows))
    plan = build_trap_plan(
        group_id="s2-four-contract-incomplete",
        strategy_id="track2_asymmetric_trap",
        purpose="ASYMMETRIC_TRAP_WIDE",
        short_put=Decimal("490"), short_call=Decimal("510"),
        long_put=Decimal("495"), long_call=Decimal("505"), quantity=1,
    )

    with pytest.raises(ValueError, match="TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE"):
        tuple(
            source.resolve_identity(
                expiry="20261210", option_type=leg.option_type, strike=leg.strike
            )
            for leg in plan.legs
        )


def test_nearest_expiry_fails_closed_without_kis_expiry_provenance():
    item = KisOptionContractIdentity(
        shrn_iscd="MONTHLY-P-500",
        stnd_iscd=None,
        expiry="20261210",
        option_type="PUT",
        strike=Decimal("500"),
        contract_multiplier=Decimal("250000"),
        instrument_family="STANDARD",
        product_series="MONTHLY",
        expiry_source=None,
        expiry_master_sha256=None,
        master_sha256=None,
    )
    with pytest.raises(ValueError, match="TRACK2_OPTION_EXPIRY_NOT_FOUND"):
        Track2OptionContractSource(Master((item,))).nearest_expiry(
            as_of=date(2026, 11, 10)
        )


def test_resolve_identity_fails_closed_without_kis_expiry_provenance():
    item = KisOptionContractIdentity(
        shrn_iscd="MONTHLY-P-490",
        stnd_iscd=None,
        expiry="20261210",
        option_type="PUT",
        strike=Decimal("490"),
        contract_multiplier=Decimal("250000"),
        instrument_family="STANDARD",
        product_series="MONTHLY",
        expiry_source=None,
        expiry_master_sha256=None,
        master_sha256=None,
    )
    with pytest.raises(ValueError, match="TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE"):
        Track2OptionContractSource(Master((item,))).resolve_identity(
            expiry="20261210", option_type="PUT", strike=Decimal("490")
        )


def test_resolve_identity_fails_closed_when_expiry_and_master_snapshot_hashes_differ():
    item = identity(
        "MISMATCH-P-500",
        "20261210",
        "PUT",
        Decimal("500"),
    )
    item = dataclasses.replace(item, master_sha256="d" * 64)
    with pytest.raises(ValueError, match="TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE"):
        Track2OptionContractSource(Master((item,))).resolve_identity(
            expiry="20261210", option_type="PUT", strike=Decimal("500")
        )


def test_kis_official_monthly_product_spec_is_accepted_as_expiry_provenance():
    item = dataclasses.replace(
        identity("PRODUCT-SPEC-P-500", "20261112", "PUT", Decimal("500")),
        expiry_source=KIS_MONTHLY_OPTION_EXPIRY_SOURCE,
        expiry_observed_at=None,
        expiry_endpoint=KIS_OPTION_PRODUCT_SPEC_URL,
        expiry_tr_id=KIS_MONTHLY_OPTION_EXPIRY_RULE_ID,
        expiry_response_sha256=None,
    )
    source = Track2OptionContractSource(Master((item,)))

    assert source.nearest_expiry(as_of=date(2026, 11, 10)) == "20261112"
    assert source.resolve_identity(
        expiry="20261112", option_type="PUT", strike=Decimal("500")
    ) == item


def test_kis_official_monthly_product_spec_fails_closed_for_untrusted_source_url():
    item = dataclasses.replace(
        identity("BAD-PRODUCT-SPEC-P-500", "20261112", "PUT", Decimal("500")),
        expiry_source=KIS_MONTHLY_OPTION_EXPIRY_SOURCE,
        expiry_observed_at=None,
        expiry_endpoint="https://example.invalid/product-guide",
        expiry_tr_id=KIS_MONTHLY_OPTION_EXPIRY_RULE_ID,
        expiry_response_sha256=None,
    )
    with pytest.raises(ValueError, match="TRACK2_OPTION_EXPIRY_NOT_FOUND"):
        Track2OptionContractSource(Master((item,))).nearest_expiry(
            as_of=date(2026, 11, 10)
        )
