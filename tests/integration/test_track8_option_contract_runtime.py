from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.track8_analytics_provider import build_track8_analytics_snapshot
from application.composition.track8_option_contract_source import Track8OptionContractSource
from core.option.option_master import KisOptionContractIdentity


def _identity(option_type, strike):
    return KisOptionContractIdentity(
        shrn_iscd=f"{option_type}{strike}",
        stnd_iscd="",
        expiry="2026-10-08",
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
    )


class Master:
    def list_contract_identities(self, expiry=None):
        return tuple(
            _identity(t, s)
            for s in (1075, 1090, 1105)
            for t in ("PUT", "CALL")
        )


def test_option_master_selection_materializes_into_track8_analytics():
    source = Track8OptionContractSource(Master())
    selection = source.select(expiry="2026-10-08", current_price=Decimal("1091"))
    data = SimpleNamespace(
        price=Decimal("1091"),
        days_to_expiry=10,
        macro_regime=None,
        active_vol=Decimal("1"),
        option_iv=Decimal("12"),
        put_iv=Decimal("13"),
        current_pnl=None,
        total_fees=None,
        margin_ratio=None,
        risk_guard_active=None,
    )
    snapshot = build_track8_analytics_snapshot(
        data,
        run_id="test-track8",
        as_of=datetime(2026, 9, 28, 10, 0),
        option_contract_selection=selection,
    )
    assert snapshot.get("options.call_strike").value == Decimal("1105")
    assert snapshot.get("options.put_strike").value == Decimal("1075")
    assert snapshot.get("options.call_contract_multiplier").value == Decimal("250000")
    assert snapshot.get("options.put_contract_multiplier").value == Decimal("250000")
