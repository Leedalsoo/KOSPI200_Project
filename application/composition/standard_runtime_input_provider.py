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
from application.composition.track3_runtime_input_provider import Track3RuntimeInputProvider
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
from contracts.track2_market_metrics_source import Track2MarketMetricsSource
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer, Track9ATMIVSource
from contracts.track9_fee_ledger import Track9FeeLedger


class StandardRuntimeInputProvider:
    """Build standard inputs from observable VMS/VSSF sources only."""

    def __init__(self, market: Any, *, track9_fee_ledger: Track9FeeLedger | None = None, run_id: str | None = None, track7_order_timeout_source: Any | None = None, track7_support_resistance_source: Any | None = None, option_expiry_source: OptionExpirySource | None = None, trading_calendar: Any | None = None, option_master: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, track9_iv_event_materializer: Track9IVEventMaterializer | None = None, track9_atm_iv_source: Track9ATMIVSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None, track2_metrics_source: Track2MarketMetricsSource | None = None, track2_option_iv_source: Track2OptionIVSource | None = None, track3_runtime_input_source: Any | None = None) -> None:
        self.track9_fee_ledger = track9_fee_ledger
        self.run_id = run_id
        self.track7_order_timeout_source = track7_order_timeout_source
        self.track7_support_resistance_source = track7_support_resistance_source
        self.data = VirtualRuntimeDataProvider(
            market, option_expiry_source=option_expiry_source, track7_order_timeout_source=track7_order_timeout_source, track7_support_resistance_source=track7_support_resistance_source, trading_calendar=trading_calendar, option_master=option_master,
            option_orderbook_source=option_orderbook_source,
            volume_profile_source=volume_profile_source,
            basis_source=basis_source,
            track2_metrics_source=track2_metrics_source,
            track2_option_iv_source=track2_option_iv_source,
            track9_iv_event_materializer=track9_iv_event_materializer,
            track9_atm_iv_source=track9_atm_iv_source,
        )
        self.track3 = Track3RuntimeInputProvider(track3_runtime_input_source)

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

    def _common(self, d: Any, account: Any | None) -> CommonStrategyInput:
        snapshot = self._account_snapshot(account)
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
            total_fees=(self.track9_fee_ledger.total(run_id=self.run_id) if self.track9_fee_ledger is not None and self.run_id else None),
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
            elif d.bbw_window is None or d.volume_window is None:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("bbw_window", "volume_window"),
                    "TRACK2_BBW_VOLUME_SOURCE_UNAVAILABLE",
                )
            elif d.active_vol is None or d.base_vol is None:
                contexts["track2_asymmetric_trap"] = self._unavailable(
                    "track2_asymmetric_trap", ("active_vol", "base_vol"),
                    "TRACK2_VOLATILITY_SOURCE_UNAVAILABLE",
                )
            else:
                contexts["track2_asymmetric_trap"] = StrategyContext(
                    market_state, "track2_asymmetric_trap", StrategyInput(
                        common, Track2MarketInputs(
                            bbw_window=tuple(float(x) for x in d.bbw_window),
                            volume_window=tuple(float(x) for x in d.volume_window),
                            basis=d.basis, put_iv=d.put_iv, call_iv=d.option_iv,
                            poc_price=d.poc_price, bid_qtys=d.option_bid_qtys,
                            ask_qtys=d.option_ask_qtys, active_vol=float(d.active_vol),
                            base_vol=float(d.base_vol),
                        )
                    )
                )

        # Track3 is materialized only through its authoritative source seam.
        contexts["Strategy_3_StatArb"] = self.track3.build(market_state, account=account)

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

        # Track7 may consume CALL/PUT IV already projected from the injected
        # authoritative Track2/KIS IV source. Do not report IV as missing when
        # both observations are actually available; the remaining dedicated
        # sources still keep the whole Track7 payload fail-closed.
        track7_missing_sources: list[str] = []
        if d.option_iv is None or d.put_iv is None:
            track7_missing_sources.append("option_iv_chain")
        if not all(value is not None for value in (d.ma_1m, d.ma_3m, d.ma_5m, d.ma_10m)):
            track7_missing_sources.append("moving_average")
        if not all(value is not None for value in (d.is_new_week_start, d.is_expiry_day, d.is_week_end)):
            track7_missing_sources.append("expiry_calendar")
        if d.order_timeout is None:
            track7_missing_sources.append("order_timeout")
        if d.status.get("track7_support_resistance") is None or not d.status["track7_support_resistance"].available:
            track7_missing_sources.append("support_resistance")
        if "support_resistance" not in track7_missing_sources and not track7_missing_sources:
            contexts["track7_volatility_skew_weekly_insurance"] = StrategyContext(
                market_state, "track7_volatility_skew_weekly_insurance", StrategyInput(
                    common, Track7MarketInput(
                        "track7_volatility_skew_weekly_insurance", d.price, common.budget,
                        d.as_of.date().isoformat(), bool(d.is_new_week_start), d.active_vol,
                        call_iv=d.option_iv, put_iv=d.put_iv, skew_limit_timeout=False,
                        ma_1m=d.ma_1m, ma_3m=d.ma_3m, ma_5m=d.ma_5m, ma_10m=d.ma_10m,
                        support=d.support, resistance=d.resistance,
                        time_str=d.as_of.strftime("%H:%M:%S"),
                        is_expiry_day=bool(d.is_expiry_day), is_week_end=bool(d.is_week_end),
                    )
                )
            )
        else:
            contexts["track7_volatility_skew_weekly_insurance"] = self._unavailable(
                "track7_volatility_skew_weekly_insurance",
                tuple(track7_missing_sources),
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
