from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from application.composition.track6_option_contract_source import Track6OptionContractSelection
from core.domain.market_models import MarketState
from tests.support import build_test_option_master
from tests.risk_guard_test_support import allow_risk_guard


def test_track6_runtime_uses_underlying_price_for_atm_contract_selection():
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=build_test_option_master(),
        risk_guard_status_source=allow_risk_guard(),
    )
    seen = []

    class Source:
        def select(self, *, expiry, current_price):
            seen.append((expiry, current_price))
            return Track6OptionContractSelection(
                Decimal("350"),
                SimpleNamespace(strike=Decimal("337.5"), contract_multiplier=Decimal("250000")),
                SimpleNamespace(strike=Decimal("362.5"), contract_multiplier=Decimal("250000")),
            )

    provider = StandardRuntimeInputProvider(
        bootstrap.bundle.market,
        option_master=bootstrap.bundle.option_master,
        track6_option_contract_source=Source(),
    )
    tick = next(bootstrap.bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    tick = replace(tick, underlying_price=Decimal("1130.63"))
    contexts = provider.build(
        tick,
        MarketState(as_of=datetime.fromisoformat(tick.timestamp), ticks={}, quality={}),
    )
    assert (tick.expiry, Decimal("1130.63")) in seen
    assert contexts["track6_daily_tail_insurance"].input.payload.listed_put_strike == Decimal("337.5")
