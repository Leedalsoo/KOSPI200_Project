from decimal import Decimal

from core.option.option_master import KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


class StubAuthoritativeOptionMaster:
    def __init__(self):
        self.calls = []

    def find_contract_identity(self, expiry, option_type, strike):
        self.calls.append((expiry, option_type, str(strike)))
        return KisOptionContractIdentity(
            shrn_iscd=f"PROBE_{option_type}_{strike}",
            stnd_iscd=None,
            expiry="2026-09-10",
            option_type=option_type,
            strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
        )

    def list_contract_identities(self, expiry=None):
        return tuple(
            KisOptionContractIdentity(
                shrn_iscd=f"PROBE_{option_type}_{strike}",
                stnd_iscd=None,
                expiry="2026-09-10",
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
    assert master.calls[0][0] == "202609"
    assert all(call[0] == "20260910" for call in master.calls[1:])
