from __future__ import annotations

from typing import Callable, Sequence

from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_runtime_input_provider import Track4RuntimeInputProvider
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from contracts.account import AccountProvider


class Track4RuntimeInputProviderFactory:
    """Build the Track4 partial Runtime provider graph from explicit authoritative sources.

    The factory wires existing source adapters only. It does not synthesize missing
    valuation, OHLC, attribution, risk-free-rate, or DTE inputs and does not start
    the Track4 production process_tick loop.
    """

    @staticmethod
    def create(
# *,
        snapshot_supplier: Callable[[], MarketConditionSnapshot | None],
        price_history_supplier: Callable[[str], Sequence[float]],
        account_provider: AccountProvider,
        greeks_provider: Track4KisGreeksProvider | None = None,
    ) -> Track4RuntimeInputProvider:
        market_provider = Track4MarketProjectionProvider(
            snapshot_supplier=snapshot_supplier,
            price_history_supplier=price_history_supplier,
            greeks_provider=greeks_provider,
        )
        account_projection = Track4VSSFAccountProjectionProvider(account_provider)
        return Track4CompositeRuntimeInputProvider(market_provider, account_projection)
