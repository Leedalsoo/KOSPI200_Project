from datetime import date
from decimal import Decimal

from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from tests.support import build_test_option_master


def test_runtime_provider_consumes_master_expiry_without_yyyy_mm_derivation():
    market = VirtualMarketSimulatorRuntime(option_master=build_test_option_master())
    ticks = list(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    tick = ticks[-1]
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd=tick.symbol, stnd_iscd=None, expiry="2026-10-15",
        option_type=tick.option_type, strike=Decimal(str(tick.strike_price)),
        contract_multiplier=Decimal("250000"),
    ))
    source = KisOptionMasterExpirySource(master)
    data = VirtualRuntimeDataProvider(market, option_expiry_source=source).snapshot(tick)
    observed = date.fromisoformat(tick.timestamp[:10])
    assert data.option_expiry == date(2026, 10, 15)
    assert data.days_to_expiry == (date(2026, 10, 15) - observed).days
    assert data.status["option_expiry"].available is True
    assert data.status["option_expiry"].source == "KIS.OptionMaster.expiry"
