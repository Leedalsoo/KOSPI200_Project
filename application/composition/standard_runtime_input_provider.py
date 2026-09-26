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
from application.composition.track3_runtime_input_provider import Track3RuntimeInputProvider
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput
from contracts.analytics import AnalyticsProvenance, MarketSnapshot
from core.analytics.common import COMMON_METRIC_CONTRACTS, build_common_analytics_snapshot
from application.composition.track9_analytics_provider import build_track9_analytics_snapshot
from contracts.option_expiry_source import OptionExpirySource
from contracts.option_orderbook_source import OptionOrderBookSource
from contracts.volume_profile_source import VolumeProfileSource
from contracts.basis_source import BasisSource
from contracts.track2_market_metrics_source import Track2MarketMetricsSource
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer, Track9ATMIVSource
from contracts.track9_fee_ledger import Track9FeeLedger
from contracts.track9_margin_read_model import Track9MarginReadModel
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track2_analytics_provider import build_track2_analytics_snapshot
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from application.composition.track5_analytics_provider import build_track5_analytics_snapshot
from application.composition.track6_analytics_provider import build_track6_analytics_snapshot
from application.composition.track7_analytics_provider import build_track7_analytics_snapshot
from application.composition.track8_analytics_provider import build_track8_analytics_snapshot


class StandardRuntimeInputProvider:
    """Build standard inputs from observable VMS/VSSF sources only."""

    def __init__(self, market: Any, *, track9_fee_ledger: Track9FeeLedger | None = None, track9_margin_read_model: Track9MarginReadModel | None = None, run_id: str | None = None, track7_order_timeout_source: Any | None = None, track7_support_resistance_source: Any | None = None, option_expiry_source: OptionExpirySource | None = None, trading_calendar: Any | None = None, option_master: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, track9_iv_event_materializer: Track9IVEventMaterializer | None = None, track9_atm_iv_source: Track9ATMIVSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None, track2_metrics_source: Track2MarketMetricsSource | None = None, track2_option_iv_source: Track2OptionIVSource | None = None, track3_runtime_input_source: Any | None = None, track6_option_contract_source: Track6OptionContractSource | None = None) -> None:
        self.track9_fee_ledger = track9_fee_ledger
        self.track9_margin_read_model = track9_margin_read_model
        self.run_id = run_id
        self.track9_margin_ratio = None
        self.track7_order_timeout_source = track7_order_timeout_source
        self.track7_support_resistance_source = track7_support_resistance_source
        self.track6_option_contract_source = track6_option_contract_source
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
        realized_pnl = balances.get("realized_pnl")
        unrealized_pnl = balances.get("unrealized_pnl")
        pnl = (Decimal(str(realized_pnl)) + Decimal(str(unrealized_pnl))) if realized_pnl is not None and unrealized_pnl is not None else None
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
        self.track9_margin_ratio = None
        if self.track9_margin_read_model is not None and self.run_id:
            snapshot = self.track9_margin_read_model.snapshot(run_id=self.run_id)
            if snapshot is not None:
                self.track9_margin_ratio = snapshot.used_margin / snapshot.total_balance

        common_market_snapshot = MarketSnapshot(
            run_id=self.run_id or "virtual",
            as_of=d.as_of,
            provenance=AnalyticsProvenance(source="standard-runtime.common"),
            instrument_identity=None,
            observations={
                "current_price": d.price,
                "active_vol": d.active_vol,
                "base_vol": d.base_vol,
                "current_pnl": common.current_pnl,
                "total_fees": common.total_fees,
                "margin_ratio": self.track9_margin_ratio,
                "risk_guard_active": None,
            },
        )
        common_analytics = build_common_analytics_snapshot(
            common_market_snapshot,
            tuple(COMMON_METRIC_CONTRACTS),
        )
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
                    market_state, "track2_asymmetric_trap", StrategyInput(common),
                    analytics=build_track2_analytics_snapshot(
                        d, run_id=self.run_id or "virtual", common_snapshot=common_analytics
                    ),
                )

        # Track3 is materialized only through its authoritative source seam.
        contexts["Strategy_3_StatArb"] = self.track3.build(
            market_state, account=account, common_snapshot=common_analytics
        )

        # Track4 consumes canonical analytics. Same-tick Greeks remain authoritative
        # inputs when supplied; optional attribution metrics remain unavailable without
        # their dedicated authoritative source.
        if d.option_delta is None or d.option_gamma is None or d.active_vol is None or d.base_vol is None or common.budget is None or common.current_pnl is None or not d.prices:
            contexts["track4_gamma_scalping"] = self._unavailable(
                "track4_gamma_scalping",
                ("option_greeks", "account_equity", "ohlc_history"),
                "TRACK4_COMMON_ANALYTICS_INPUTS_UNAVAILABLE",
            )
        else:
            track4_payload = Track4MarketInput(
                observed_at=d.as_of,
                current_price=d.price,
                active_vol=d.active_vol,
                base_vol=d.base_vol,
                time_str=d.as_of.strftime("%H:%M:%S"),
                current_delta=d.option_delta,
                current_gamma=d.option_gamma,
                current_pnl=common.current_pnl,
                current_equity=common.budget,
                price_history=d.prices,
                current_theta=None,
            )
            contexts["track4_gamma_scalping"] = StrategyContext(
                market_state,
                "track4_gamma_scalping",
                StrategyInput(common, track4_payload),
                analytics=build_track4_analytics_snapshot(
                    track4_payload, run_id=self.run_id or "virtual", as_of=d.as_of,
                    common_snapshot=common_analytics,
                ),
            )

        # Track5 always receives the canonical AnalyticsSnapshot. Missing
        # authoritative observations become unavailable metrics and the Strategy
        # remains fail-closed at its feature boundary.
        contexts["track5_gap_divergence"] = StrategyContext(
            market_state,
            "track5_gap_divergence",
            StrategyInput(common),
            analytics=build_track5_analytics_snapshot(
                d, run_id=self.run_id or "virtual", as_of=d.as_of,
                common_snapshot=common_analytics,
            ),
        )

        if self.track6_option_contract_source is None:
            contexts["track6_daily_tail_insurance"] = self._unavailable(
                "track6_daily_tail_insurance", ("listed_option_contracts",), "TRACK6_OPTION_CONTRACT_SOURCE_UNAVAILABLE"
            )
        else:
            try:
                selection = self.track6_option_contract_source.select(
                    expiry=getattr(tick, "expiry", ""), current_price=d.price
                )
                multiplier = Decimal(str(selection.put.contract_multiplier))
                call_multiplier = Decimal(str(selection.call.contract_multiplier))
                if multiplier <= 0 or call_multiplier <= 0 or multiplier != call_multiplier:
                    raise ValueError("TRACK6_CONTRACT_MULTIPLIER_REQUIRED")
            except (ValueError, TypeError, AttributeError) as exc:
                contexts["track6_daily_tail_insurance"] = self._unavailable(
                    "track6_daily_tail_insurance", ("listed_option_contracts",), str(exc)
                )
            else:
                execution_input = Track6ExecutionInput(
                    strategy_id="track6_daily_tail_insurance",
                    date_str=d.as_of.date().isoformat(),
                    time_str=d.as_of.strftime("%H:%M:%S"),
                    listed_put_strike=Decimal(str(selection.put.strike)),
                    listed_call_strike=Decimal(str(selection.call.strike)),
                    contract_multiplier=multiplier,
                )
                contexts["track6_daily_tail_insurance"] = StrategyContext(
                    market_state, "track6_daily_tail_insurance", StrategyInput(common, execution_input),
                    analytics=build_track6_analytics_snapshot(
                        d, run_id=self.run_id or "virtual", as_of=d.as_of,
                        common_snapshot=common_analytics,
                    ),
                )

        # Track7 consumes canonical analytics only when every required source is available.
        track7_missing_sources: list[str] = []
        if d.option_iv is None or d.put_iv is None:
            track7_missing_sources.append("option_iv_chain")
        if not all(value is not None for value in (d.ma_1m, d.ma_3m, d.ma_5m, d.ma_10m)):
            track7_missing_sources.append("moving_average")
        if not all(value is not None for value in (d.is_new_week_start, d.is_expiry_day, d.is_week_end)):
            track7_missing_sources.append("expiry_calendar")
        if d.order_timeout is None:
            track7_missing_sources.append("order_timeout")
        support_status = d.status.get("track7_support_resistance")
        if support_status is None or not support_status.available:
            track7_missing_sources.append("support_resistance")
        if track7_missing_sources:
            contexts["track7_volatility_skew_weekly_insurance"] = self._unavailable(
                "track7_volatility_skew_weekly_insurance", tuple(track7_missing_sources),
                "TRACK7_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["track7_volatility_skew_weekly_insurance"] = StrategyContext(
                market_state, "track7_volatility_skew_weekly_insurance", StrategyInput(common),
                analytics=build_track7_analytics_snapshot(
                    d, run_id=self.run_id or "virtual", as_of=d.as_of,
                    common_snapshot=common_analytics,
                ),
            )

        # Track8 receives canonical analytics only when the authoritative
        # option contract, fee, margin and risk inputs are all present.
        track8_required = (
            d.days_to_expiry, d.option_iv, d.put_iv, d.macro_regime, common.current_pnl,
            common.total_fees, self.track9_margin_ratio,
        )
        if not all(value is not None for value in track8_required):
            contexts["track8_macro_regime_monthly_strangle"] = self._unavailable(
                "track8_macro_regime_monthly_strangle",
                ("track8_authoritative_option_contract", "fee_ledger", "margin_read_model", "risk_guard"),
                "TRACK8_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["track8_macro_regime_monthly_strangle"] = StrategyContext(
                market_state, "track8_macro_regime_monthly_strangle", StrategyInput(common),
                analytics=build_track8_analytics_snapshot(
                    d, run_id=self.run_id or "virtual", as_of=d.as_of,
                    common_snapshot=common_analytics,
                ),
            )

        # Track9 consumes canonical AnalyticsSnapshot. Dedicated event calendar, event budget, premium attribution and risk guard remain unavailable until their authoritative sources are connected.
        track9_selection = None
        if self.track6_option_contract_source is not None:
            try:
                track9_selection = self.track6_option_contract_source.select(expiry=getattr(tick, "expiry", ""), current_price=d.price)
            except (ValueError, TypeError, AttributeError):
                track9_selection = None
        contexts["track9_event_overnight_insurance"] = StrategyContext(
            market_state, "track9_event_overnight_insurance", StrategyInput(common),
            analytics=build_track9_analytics_snapshot(
                d, run_id=self.run_id or "virtual", as_of=d.as_of,
                total_fees=common.total_fees, margin_ratio=self.track9_margin_ratio,
                option_contract_selection=track9_selection, common_snapshot=common_analytics,
            ),
        )
        return contexts
