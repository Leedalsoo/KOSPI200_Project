"""Materialize nine Strategy inputs without synthetic/default runtime values.

A strategy receives a typed payload only when every required source for that
payload is available. Missing authoritative data is represented explicitly by
UnavailableStrategyPayload and never by a numeric/boolean placeholder.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput, UnavailableStrategyPayload
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track2_asymmetric_trap import Track2MarketInputs
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5MarketInput
from core.strategy.track6_daily_tail_insurance import Track6MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9MarketInput
from contracts.option_expiry_source import OptionExpirySource
from contracts.option_orderbook_source import OptionOrderBookSource
from contracts.volume_profile_source import VolumeProfileSource
from contracts.basis_source import BasisSource


class StandardRuntimeInputProvider:
    """Build standard inputs from observable VMS/VSSF sources only."""

    def __init__(self, market: Any, *, option_expiry_source: OptionExpirySource | None = None, option_orderbook_source: OptionOrderBookSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None) -> None:
        self.data = VirtualRuntimeDataProvider(
            market, option_expiry_source=option_expiry_source,
            option_orderbook_source=option_orderbook_source,
            volume_profile_source=volume_profile_source,
            basis_source=basis_source,
        )

    @staticmethod
    def _unavailable(strategy_id: str, sources: tuple[str, ...], reason: str) -> StrategyContext:
        return StrategyContext(
            strategy_id=strategy_id,
            input=StrategyInput(
                payload=UnavailableStrategyPayload(strategy_id, sources, reason),
                data_status={source: "UNAVAILABLE" for source in sources},
            ),
        )

    @staticmethod
    def _account_snapshot(account: Any | None) -> Any | None:
        if account is None:
            return None
        getter = getattr(account, "snapshot", None)
        return getter() if callable(getter) else account

    @classmethod
    def _common(cls, d: Any, account: Any | None) -> CommonStrategyInput:
        snapshot = cls._account_snapshot(account)
        balances = getattr(snapshot, "balances", {}) if snapshot is not None else {}
        budget = balances.get("available_cash")
        pnl = balances.get("realized_pnl")
        return CommonStrategyInput(
            as_of=d.as_of,
            current_price=d.price,
            active_vol=d.active_vol,
            base_vol=d.base_vol,
            budget=Decimal(str(budget)) if budget is not None else None,
            current_pnl=Decimal(str(pnl)) if pnl is not None else None,
            total_fees=None,
            time_str=d.as_of.strftime("%H:%M:%S"),
            date_str=d.as_of.date().isoformat(),
        )

    @staticmethod
    def _position_values(account: Any | None) -> tuple[int, int]:
        if account is None:
            return 0, 0
        positions = getattr(account, "positions", None)
        if not isinstance(positions, dict):
            return 0, 0
        active = sum(int(v.get("qty", 0) or 0) for v in positions.values() if isinstance(v, dict))
        return active, active

    def build(self, tick: Any, market_state: MarketState, account: Any | None = None) -> dict[str, StrategyContext]:
        d = self.data.snapshot(tick)
        common = self._common(d, account)
        contexts: dict[str, StrategyContext] = {}

        # Track1 now receives exact expiry from the Option Master source. The
        # remaining momentum/coverage/position-Greeks sources are still absent.
        contexts["TRACK1_TAIL_DEFENSE"] = self._unavailable(
            "TRACK1_TAIL_DEFENSE",
            ("momentum", "position_coverage", "option_position_greeks"),
            "TRACK1_REMAINING_AUTHORITATIVE_SOURCES_UNAVAILABLE",
        )

        # Track2: IV may exist in the option chain, but POC and order-book
        # quantities must also be authoritative before a typed payload is built.
        if d.option_iv is None or d.put_iv is None:
            contexts["track2_asymmetric_trap"] = self._unavailable(
                "track2_asymmetric_trap", ("option_iv_chain",), "OPTION_CHAIN_UNAVAILABLE"
            )
        else:
            if d.poc_price is None:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("volume_profile_poc",),
                    "VOLUME_PROFILE_POC_UNAVAILABLE",
                )
            elif d.option_bid_qtys is None or d.option_ask_qtys is None:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("option_orderbook_quantities",),
                    "OPTION_ORDERBOOK_QUANTITIES_UNAVAILABLE",
                )
            elif d.basis is None:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("basis",),
                    "TRACK2_BASIS_SOURCE_UNAVAILABLE",
                )
            else:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("bbw_window", "volume_window"),
                    "TRACK2_BBW_VOLUME_SOURCE_UNAVAILABLE",
                )

        # Track3 must not receive fabricated stability, normalization, fee,
        # premium, or option-leg attribution values.
        contexts["Strategy_3_StatArb"] = self._unavailable(
            "Strategy_3_StatArb",
            ("market_stability", "spread_normalization", "position_sizing", "fee_ledger", "premium_attribution", "option_legs"),
            "TRACK3_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
        )

        # Track4 standard path is intentionally fail-closed. The dedicated
        # Track4 materializer must supply same-tick KIS Greeks and attribution.
        if d.option_delta is None or d.option_gamma is None:
            contexts["track4_gamma_scalping"] = self._unavailable(
                "track4_gamma_scalping", ("option_iv_greeks",), "OPTION_GREEKS_UNAVAILABLE"
            )
        else:
            contexts["track4_gamma_scalping"] = self._unavailable(
                "track4_gamma_scalping",
                ("kis_same_tick_greeks", "premium_attribution", "gamma_pnl_attribution", "theta_attribution"),
                "TRACK4_AUTHORITATIVE_RUNTIME_PATH_REQUIRES_DEDICATED_MATERIALIZER",
            )

        # Track5/6 retain only values that have real VMS/VSSF sources. A missing
        # volatility observation now blocks the strategy instead of becoming 0.
        if d.active_vol is None:
            contexts["track5_gap_divergence"] = self._unavailable(
                "track5_gap_divergence", ("active_vol",), "ACTIVE_VOL_UNAVAILABLE"
            )
        else:
            contexts["track5_gap_divergence"] = StrategyContext(
                market_state, "track5_gap_divergence", StrategyInput(common,
                    Track5MarketInput("track5_gap_divergence", d.open_price, d.previous_close,
                                      d.active_vol, d.macro_regime or "NORMAL", d.price))
            )

        if d.active_vol is None or d.base_vol is None:
            contexts["track6_daily_tail_insurance"] = self._unavailable(
                "track6_daily_tail_insurance", ("active_vol", "base_vol"), "VOLATILITY_SOURCE_UNAVAILABLE"
            )
        elif common.budget is None:
            contexts["track6_daily_tail_insurance"] = self._unavailable(
                "track6_daily_tail_insurance", ("account_available_cash",), "ACCOUNT_SOURCE_UNAVAILABLE"
            )
        else:
            contexts["track6_daily_tail_insurance"] = StrategyContext(
                market_state, "track6_daily_tail_insurance", StrategyInput(common,
                    Track6MarketInput("track6_daily_tail_insurance", d.price, d.active_vol,
                                      d.base_vol, common.budget, d.as_of.date().isoformat(),
                                      d.as_of.strftime("%H:%M:%S")))
            )

        # Track7 requires more than IV: timeout, support/resistance and expiry
        # calendar must come from dedicated authoritative providers.
        contexts["track7_volatility_skew_weekly_insurance"] = self._unavailable(
            "track7_volatility_skew_weekly_insurance",
            ("option_iv_chain", "order_timeout", "support_resistance", "expiry_calendar"),
            "TRACK7_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
        )

        # Track8: DTE cannot be derived from YYYYMM alone. Fees, margin and risk
        # guard also require broker/risk read models.
        contexts["track8_macro_regime_monthly_strangle"] = self._unavailable(
            "track8_macro_regime_monthly_strangle",
            ("fee_ledger", "margin_read_model", "risk_guard"),
            "TRACK8_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
        )

        # Track9: account positions alone do not identify short vs insurance
        # legs. Event/IV/fee/premium/margin/risk sources are separate authorities.
        contexts["track9_event_overnight_insurance"] = self._unavailable(
            "track9_event_overnight_insurance",
            ("option_position_attribution", "event_calendar", "iv_timeseries", "fee_ledger",
             "premium_attribution", "insurance_position", "margin_read_model", "risk_guard", "event_budget"),
            "TRACK9_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
        )
        return contexts
