from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.composition.track2_option_contract_source import Track2OptionContractSource
from contracts.types import OptionInstrumentIdentity
from core.option.option_master import KisProductionOptionContractMaster, parse_kis_fo_idx_mst_result


class _Calendar:
    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5

    def prev_trading_day(self, value: date) -> date:
        candidate = value - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def trading_days_between(self, start: date, end: date) -> int:
        return 0


class _Master:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, symbol):
        return self.identity if symbol == self.identity.shrn_iscd else None


def _bridge_for(identity):
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.option_master = _Master(identity)
    return bridge


def test_virtual_runtime_bridge_accepts_kis_product_spec_bound_monthly_standard_identity():
    raw = "5|B01611887|KR4B016B8873|C 202611   887.5|3|00887.50| |2001|KOSPI200"
    parsed = parse_kis_fo_idx_mst_result(raw, _Calendar(), master_sha256="a" * 64)
    master_identity = parsed.identities["B01611887"]
    stored = OptionInstrumentIdentity(
        instrument_id="B01611887",
        symbol="B01611887",
        expiry="20261112",
        option_type="CALL",
        strike=Decimal("887.5"),
        contract_multiplier=Decimal("250000"),
    )

    resolved = _bridge_for(master_identity).identity_for_leg(
        SimpleNamespace(strategy_id="track2_asymmetric_trap"),
        SimpleNamespace(instrument_identity=stored),
    )

    assert resolved == stored


@pytest.mark.parametrize(
    "stored",
    [
        OptionInstrumentIdentity(
            instrument_id="B01611887",
            symbol="B01611887",
            expiry="20261112",
            option_type="CALL",
            strike=Decimal("887.5"),
            contract_multiplier=Decimal("50000"),
        ),
        OptionInstrumentIdentity(
            instrument_id="B01611887",
            symbol="B01611887",
            expiry="20261119",
            option_type="CALL",
            strike=Decimal("887.5"),
            contract_multiplier=Decimal("250000"),
        ),
    ],
)
def test_virtual_runtime_bridge_rejects_wrong_multiplier_or_expiry(stored):
    raw = "5|B01611887|KR4B016B8873|C 202611   887.5|3|00887.50| |2001|KOSPI200"
    parsed = parse_kis_fo_idx_mst_result(raw, _Calendar(), master_sha256="a" * 64)
    master_identity = parsed.identities["B01611887"]

    with pytest.raises(ValueError, match="TRACK2_STORED_IDENTITY_NOT_AUTHORITATIVE_MONTHLY_STANDARD"):
        _bridge_for(master_identity).identity_for_leg(
            SimpleNamespace(strategy_id="track2_asymmetric_trap"),
            SimpleNamespace(instrument_identity=stored),
        )


def test_raw_kis_mst_virtual_option_master_resolves_four_monthly_legs_offline():
    raw = "\n".join(
        (
            "5|B01611887|KR4B016B8873|C 202611   887.5|3|00887.50| |2001|KOSPI200",
            "5|B01611892|KR4B016B8923|C 202611   892.5|3|00892.50| |2001|KOSPI200",
            "6|C01611877|KR4C016B8772|P 202611   877.5|2|00877.50| |2001|KOSPI200",
            "6|C01611882|KR4C016B8822|P 202611   882.5|2|00882.50| |2001|KOSPI200",
        )
    )
    master = KisProductionOptionContractMaster(calendar=_Calendar(), auto_load=False)
    master.load_from_raw_mst_content(raw)
    source = Track2OptionContractSource(master)

    assert source.nearest_expiry(as_of=date(2026, 11, 10)) == "20261112"
    expected = {
        ("PUT", Decimal("877.5")): "C01611877",
        ("PUT", Decimal("882.5")): "C01611882",
        ("CALL", Decimal("887.5")): "B01611887",
        ("CALL", Decimal("892.5")): "B01611892",
    }
    for (option_type, strike), symbol in expected.items():
        identity = source.resolve_identity(
            expiry="20261112", option_type=option_type, strike=strike
        )
        assert identity.shrn_iscd == symbol
        assert identity.contract_multiplier == Decimal("250000")
        assert identity.expiry_master_sha256 == identity.master_sha256
