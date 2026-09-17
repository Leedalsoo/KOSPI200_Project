from decimal import Decimal

import pytest

from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


def _master(multiplier: str) -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    for option_type in ("CALL", "PUT"):
        for strike in (335, 350, 365):
            master.register_contract_identity(KisOptionContractIdentity(
                shrn_iscd=f"AUTH-{option_type[0]}-{strike}", stnd_iscd=None,
                expiry="2026-09-10", option_type=option_type,
                strike=Decimal(str(strike)), contract_multiplier=Decimal(multiplier),
            ))
    return master


def test_generated_option_quotes_use_authoritative_master_multiplier() -> None:
    market = VirtualMarketSimulatorRuntime(option_master=_master("123456"))
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    assert tick.contract_multiplier == Decimal("123456")
    assert market.option_quotes[("CALL", 350.0, "202609")]["contract_multiplier"] == Decimal("123456")
    assert market.option_quotes[("PUT", 365.0, "202609")]["contract_multiplier"] == Decimal("123456")


def test_generated_option_quotes_fail_closed_without_authoritative_master() -> None:
    market = VirtualMarketSimulatorRuntime()
    with pytest.raises(ValueError, match="VIRTUAL_AUTHORITATIVE_OPTION_MULTIPLIER_SOURCE_REQUIRED"):
        next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
