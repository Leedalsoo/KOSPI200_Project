from decimal import Decimal

from application.composition.live_option_quote_virtual_bridge import LiveOptionQuoteVirtualBridge
from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


def test_live_option_quote_binds_master_identity_and_virtual_quote_store() -> None:
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(
        KisOptionContractIdentity(
            shrn_iscd="C01609335",
            stnd_iscd="STND-C01609335",
            expiry="2026-09-10",
            option_type="PUT",
            strike=Decimal("335"),
        )
    )
    market = VirtualMarketSimulatorRuntime()
    bridge = LiveOptionQuoteVirtualBridge(
        option_master=master,
        virtual_market=market,
        contract_multiplier=Decimal("250000"),
    )

    key = bridge.publish(
        KisIndexOptionMarketObservation(
            shrn_iscd="C01609335",
            observed_hour="101530",
            last_price=Decimal("2.90"),
            ask_price=Decimal("3.00"),
            bid_price=Decimal("2.80"),
            volume=Decimal("17"),
            source="fixture:KIS:H0IOCNT0",
        )
    )

    assert key == ("PUT", 335.0, "202609")
    quote = market.option_quotes[key]
    assert quote["bid"] == Decimal("2.80")
    assert quote["ask"] == Decimal("3.00")
    assert quote["last"] == Decimal("2.90")
    assert quote["shrn_iscd"] == "C01609335"
    assert quote["contract_multiplier"] == Decimal("250000")
