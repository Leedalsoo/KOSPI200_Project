from decimal import Decimal

from core.option.option_master import KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


class StubAuthoritativeOptionMaster:
    def __init__(self, expiry="2026-09-10"):
        self.calls = []
        self.list_calls = []
        self.expiry = expiry

    def find_contract_identity(self, expiry, option_type, strike):
        self.calls.append((expiry, option_type, str(strike)))
        return KisOptionContractIdentity(
            shrn_iscd=f"PROBE_{option_type}_{strike}",
            stnd_iscd=None,
            expiry=self.expiry,
            option_type=option_type,
            strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
        )

    def list_contract_identities(self, expiry=None):
        self.list_calls.append(expiry)
        return tuple(
            KisOptionContractIdentity(
                shrn_iscd=f"PROBE_{option_type}_{strike}",
                stnd_iscd=None,
                expiry=self.expiry,
                option_type=option_type,
                strike=Decimal(str(strike)),
                contract_multiplier=Decimal("250000"),
            )
            for option_type in ("CALL", "PUT")
            for strike in ("320", "325", "330", "332.5", "335", "337.5", "340", "345", "350")
        )


def test_generated_tick_uses_authoritative_exact_expiry():
    master = StubAuthoritativeOptionMaster()
    runtime = VirtualMarketSimulatorRuntime(option_master=master)

    tick = next(runtime.generate_tick_stream(total_days=1, ticks_per_day=1))

    assert tick.expiry == "20260910"
    assert len(tick.expiry) == 8
    assert master.list_calls[0] is None
    assert all(call == "20260910" for call in master.list_calls[1:])


def test_generated_tick_resolves_identity_when_legacy_month_is_unavailable():
    master = StubAuthoritativeOptionMaster(expiry="2026-10-15")
    runtime = VirtualMarketSimulatorRuntime(option_master=master)

    tick = next(runtime.generate_tick_stream(total_days=1, ticks_per_day=1))

    assert tick.expiry == "20261015"
    assert master.list_calls[0] is None
