from datetime import datetime
from decimal import Decimal

from infrastructure.kis.track6_atm_volatility_source import KISTrack6ATMVolatilitySource


class Identity:
    def __init__(self, option_type, strike):
        self.option_type = option_type
        self.strike = Decimal(str(strike))


class Observation:
    def __init__(self, value, source="KIS:FHMIF10000000+FHMIF10010000"):
        self.implied_volatility = Decimal(str(value))
        self.source = source


class OptionSource:
    def __init__(self):
        self.values = {}
    def get_observation(self, *, expiry, option_type, strike):
        return Observation(self.values.get((expiry, option_type, Decimal(str(strike)))) or 0)
    def get_iv(self, **kwargs):
        return None


class Master:
    def list_contract_identities(self, expiry):
        return [Identity("CALL", 1090), Identity("PUT", 1090), Identity("CALL", 1087.5), Identity("PUT", 1087.5)]


def test_active_and_base_use_same_session_atm_iv():
    source = OptionSource()
    source.values.update({
        ("20261008", "CALL", Decimal("1090")): "40",
        ("20261008", "PUT", Decimal("1090")): "40",
    })
    v = KISTrack6ATMVolatilitySource(option_master=Master(), option_iv_source=source)
    first = v.snapshot(expiry="20261008", current_price=Decimal("1089.8"), observed_at=datetime(2026, 9, 30, 9, 1))
    assert first.active_vol == Decimal("0.40")
    assert first.base_vol == Decimal("0.40")
    source.values[("20261008", "CALL", Decimal("1090"))] = "52"
    source.values[("20261008", "PUT", Decimal("1090"))] = "52"
    second = v.snapshot(expiry="20261008", current_price=Decimal("1089.8"), observed_at=datetime(2026, 9, 30, 10, 0))
    assert second.active_vol == Decimal("0.52")
    assert second.base_vol == Decimal("0.40")


def test_session_reset_rebaselines():
    source = OptionSource()
    source.values.update({
        ("20261008", "CALL", Decimal("1090")): "50",
        ("20261008", "PUT", Decimal("1090")): "50",
    })
    v = KISTrack6ATMVolatilitySource(option_master=Master(), option_iv_source=source)
    first = v.snapshot(expiry="20261008", current_price=Decimal("1090"), observed_at=datetime(2026, 9, 30, 9, 1))
    assert first.base_vol == Decimal("0.50")
    source.values[("20261008", "CALL", Decimal("1090"))] = "60"
    source.values[("20261008", "PUT", Decimal("1090"))] = "60"
    second = v.snapshot(expiry="20261008", current_price=Decimal("1090"), observed_at=datetime(2026, 10, 1, 9, 1))
    assert second.base_vol == Decimal("0.60")
