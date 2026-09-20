from __future__ import annotations

from datetime import datetime

from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from core.strategy.track4_gamma_scalping import Track4MarketInput


class Track4RuntimeInputMaterializer:
    """Materialize Track4MarketInput from same-tick authoritative providers."""

    def __init__(self, runtime_provider: Track4CompositeRuntimeInputProvider, greeks_provider: Track4KisGreeksProvider) -> None:
        self._runtime_provider = runtime_provider
        self._greeks_provider = greeks_provider

    def materialize(self, tick_observed_at: datetime) -> Track4MarketInput:
        source_at = self._runtime_provider.observed_at()
        if source_at != tick_observed_at:
            raise Track4InputSourceUnavailable(
                f"TRACK4_TICK_SOURCE_TIMESTAMP_MISMATCH: tick={tick_observed_at!s} source={source_at!s}"
            )

        greeks_raw = self._greeks_provider.snapshot.observed_at
        try:
            greeks_at = datetime.fromisoformat(greeks_raw)
        except (TypeError, ValueError) as exc:
            raise Track4InputSourceUnavailable(
                f"TRACK4_GREEKS_TIMESTAMP_INVALID: {greeks_raw!s}"
            ) from exc
        if greeks_at != tick_observed_at:
            raise Track4InputSourceUnavailable(
                f"TRACK4_GREEKS_TIMESTAMP_MISMATCH: tick={tick_observed_at!s} greeks={greeks_at!s}"
            )

        readiness = self._runtime_provider.readiness()
        if not (readiness.market and readiness.history and readiness.account_pnl):
            raise Track4InputSourceUnavailable("TRACK4_CORE_INPUT_INCOMPLETE")

        history = tuple(self._runtime_provider.price_history())
        if not history:
            raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")

        return Track4MarketInput(
            observed_at=tick_observed_at,
            current_price=self._runtime_provider.current_price(),
            active_vol=self._greeks_provider.active_vol(),
            base_vol=self._runtime_provider.base_vol(),
            time_str=tick_observed_at.strftime("%H:%M:%S"),
            current_delta=self._greeks_provider.current_delta(),
            current_gamma=self._greeks_provider.current_gamma(),
            current_pnl=self._runtime_provider.current_pnl(),
            current_equity=self._runtime_provider.current_equity(),
            price_history=history,
            premium_spent=None,
            accumulated_gamma_profit=None,
            theta_decay_cost=None,
            current_theta=self._greeks_provider.current_theta(),
        )
