"""Materialize nine Strategy inputs without synthetic/default runtime values.

A strategy receives a typed payload only when every required source for that
payload is available. Missing authoritative data is represented explicitly by
UnavailableStrategyPayload and never by a numeric/boolean placeholder.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from application.composition.common_runtime_input_assembler import CommonRuntimeInputAssembler
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput, UnavailableStrategyPayload
from core.strategy.track1_tail_defense import Track1Input
from application.composition.track1_runtime_input_provider import Track1RuntimeInputProvider
from application.composition.track3_runtime_input_provider import Track3RuntimeInputProvider
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5ExecutionInput
from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7ExecutionInput
from application.composition.track7_option_contract_source import Track7OptionContractSource
from contracts.analytics import AnalyticsProvenance, AnalyticsStatus, MarketSnapshot
from contracts.risk_guard import RiskGuardStatusSource
from core.analytics.common import COMMON_METRIC_CONTRACTS, build_common_analytics_snapshot
from core.sensor.market_condition_sensor import MarketConditionSensor
from application.composition.track9_analytics_provider import build_track9_analytics_snapshot
from contracts.option_expiry_source import OptionExpirySource
from contracts.option_orderbook_source import OptionOrderBookSource
from contracts.volume_profile_source import VolumeProfileSource
from contracts.basis_source import BasisSource
from contracts.track2_market_metrics_source import Track2MarketMetricsSource
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
from contracts.track9_iv_event_materializer import Track9IVEventMaterializer, Track9ATMIVSource
from contracts.track9_fee_ledger import Track9FeeLedger
from contracts.track9_margin_read_model import Track9MarginReadModel
from contracts.track9_authoritative_sources import Track9PositionExecutionReadModel, Track9EventSource, Track9EventRiskSource
from contracts.kis_kospi200_daily_source import KOSPI200DailySource
from contracts.track6_volatility_source import Track6VolatilitySource
from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track5_option_contract_source import Track5OptionContractSource
from application.composition.track8_option_contract_source import Track8OptionContractSource
from application.composition.track2_analytics_provider import build_track2_analytics_snapshot
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from application.composition.track5_analytics_provider import build_track5_analytics_snapshot
from application.composition.track6_analytics_provider import build_track6_analytics_snapshot
from application.composition.track7_analytics_provider import build_track7_analytics_snapshot
from application.composition.track8_analytics_provider import build_track8_analytics_snapshot


class StandardRuntimeInputProvider:
    """Build standard inputs from observable VMS/VSSF sources only."""

    def __init__(self, market: Any, *, track9_fee_ledger: Track9FeeLedger | None = None, track9_margin_read_model: Track9MarginReadModel | None = None, track9_position_execution_source: Track9PositionExecutionReadModel | None = None, track9_event_source: Track9EventSource | None = None, track9_event_risk_source: Track9EventRiskSource | None = None, run_id: str | None = None, track7_order_timeout_source: Any | None = None, track7_support_resistance_source: Any | None = None, option_expiry_source: OptionExpirySource | None = None, trading_calendar: Any | None = None, option_master: Any | None = None, option_orderbook_source: OptionOrderBookSource | None = None, track9_iv_event_materializer: Track9IVEventMaterializer | None = None, track9_atm_iv_source: Track9ATMIVSource | None = None, volume_profile_source: VolumeProfileSource | None = None, basis_source: BasisSource | None = None, track2_metrics_source: Track2MarketMetricsSource | None = None, track2_option_iv_source: Track2OptionIVSource | None = None, track3_runtime_input_source: Any | None = None, track6_option_contract_source: Track6OptionContractSource | None = None, track7_option_contract_source: Track7OptionContractSource | None = None, track8_option_contract_source: Track8OptionContractSource | None = None, risk_guard_status_source: RiskGuardStatusSource | None = None, track4_greeks_provider: Track4KisGreeksProvider | None = None, kospi200_daily_source: KOSPI200DailySource | None = None, track6_volatility_source: Track6VolatilitySource | None = None, track1_fence_type_source: Any | None = None, track1_position_lot_store: Any | None = None, track1_option_delta_source: Any | None = None, strategy_keys: tuple[str, ...] | None = None) -> None:
        self.risk_guard_status_source = risk_guard_status_source
        self.strategy_keys = frozenset(strategy_keys or ())
        self.market_condition_sensor = MarketConditionSensor()
        self.track9_fee_ledger = track9_fee_ledger
        self.track9_margin_read_model = track9_margin_read_model
        self.track9_position_execution_source = track9_position_execution_source
        self.track9_event_source = track9_event_source
        self.track9_event_risk_source = track9_event_risk_source
        self.run_id = run_id
        self.track9_margin_ratio = None
        self.common_runtime_assembler = CommonRuntimeInputAssembler(
            fee_ledger=track9_fee_ledger, run_id=run_id
        )
        self.track7_order_timeout_source = track7_order_timeout_source
        self.track7_support_resistance_source = track7_support_resistance_source
        self.track6_option_contract_source = track6_option_contract_source
        self.track5_option_contract_source = Track5OptionContractSource(option_master, option_orderbook_source) if option_master is not None else None
        self.track7_option_contract_source = track7_option_contract_source
        self.track8_option_contract_source = track8_option_contract_source
        self.option_orderbook_source = option_orderbook_source
        self.data = VirtualRuntimeDataProvider(
            market, option_expiry_source=option_expiry_source, track7_order_timeout_source=track7_order_timeout_source, track7_support_resistance_source=track7_support_resistance_source, trading_calendar=trading_calendar, option_master=option_master,
            option_orderbook_source=option_orderbook_source,
            volume_profile_source=volume_profile_source,
            basis_source=basis_source,
            track2_metrics_source=track2_metrics_source,
            track2_option_iv_source=track2_option_iv_source,
            track9_iv_event_materializer=track9_iv_event_materializer,
            track9_atm_iv_source=track9_atm_iv_source,
            track4_greeks_provider=track4_greeks_provider,
            kospi200_daily_source=kospi200_daily_source,
            track6_volatility_source=track6_volatility_source,
        )
        self.track3 = Track3RuntimeInputProvider(track3_runtime_input_source)
        self.track1 = Track1RuntimeInputProvider(
            fence_type_source=track1_fence_type_source,
            position_lot_store=track1_position_lot_store,
            option_delta_source=track1_option_delta_source,
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
        instrument_id = (
            tick.instrument_id
            if tick.instrument_id in market_state.ticks
            else next(iter(market_state.ticks), None)
        )
        try:
            condition = (
                self.market_condition_sensor.analyze(market_state, instrument_id)
                if instrument_id is not None
                else None
            )
        except (KeyError, ValueError, TypeError):
            condition = None
        common = self.common_runtime_assembler.common_input(d, account)
        self.track9_margin_ratio = None
        if self.track9_margin_read_model is not None and self.run_id:
            snapshot = self.track9_margin_read_model.snapshot(run_id=self.run_id)
            if snapshot is not None:
                self.track9_margin_ratio = snapshot.used_margin / snapshot.total_balance

        risk_guard_status = (
            self.risk_guard_status_source.snapshot()
            if self.risk_guard_status_source is not None else None
        )
        common_analytics = self.common_runtime_assembler.analytics_snapshot(
            d,
            common,
            condition=condition,
            margin_ratio=self.track9_margin_ratio,
            risk_guard_status=risk_guard_status,
        )
        contexts: dict[str, StrategyContext] = {}

        # Strategy-specific Runtime Input is materialized only for strategies
        # selected for this run. This prevents an unrelated strategy's
        # authoritative source graph from becoming a hidden per-tick dependency.
        if self.strategy_keys == frozenset({"track4_gamma_scalping"}):
            if (
                d.option_delta is None
                or d.option_gamma is None
                or d.active_vol is None
                or d.base_vol is None
                or common.budget is None
                or common.current_pnl is None
                or not d.prices
            ):
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
                        track4_payload,
                        run_id=self.run_id or "virtual",
                        as_of=d.as_of,
                        common_snapshot=common_analytics,
                    ),
                )
            return contexts

        track1_result = self.track1.build(
            as_of=d.as_of,
            active_vol=d.active_vol,
            base_vol=d.base_vol,
            days_to_expiry=(float(d.days_to_expiry) if d.days_to_expiry is not None else None),
            underlying_history=tuple(getattr(self.data.market, "underlying_history", ())),
        )
        if track1_result.payload is None:
            contexts["TRACK1_TAIL_DEFENSE"] = self._unavailable(
                "TRACK1_TAIL_DEFENSE",
                track1_result.missing_sources,
                "TRACK1_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["TRACK1_TAIL_DEFENSE"] = StrategyContext(
                market_state,
                "TRACK1_TAIL_DEFENSE",
                StrategyInput(common, track1_result.payload),
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

        if self.strategy_keys == frozenset({"track2_asymmetric_trap"}):
            return contexts


        # Track3 is materialized only when Track3 is selected for this run. Other strategies must not depend on Track3-only analytics injection.
        if "Strategy_3_StatArb" in self.strategy_keys:
            if hasattr(self.track3.source, "set_common_analytics") and common_analytics is not None:
                active_metric = common_analytics.get("volatility.active")
                base_metric = common_analytics.get("volatility.base")
                regime_metric = common_analytics.get("market.current_regime")
                if active_metric is not None and base_metric is not None and regime_metric is not None:
                    if active_metric.value is not None and base_metric.value is not None and regime_metric.value is not None:
                        self.track3.source.set_common_analytics(
                            observed_at=market_state.as_of,
                            active_vol=float(active_metric.value),
                            base_vol=float(base_metric.value),
                            current_regime=str(regime_metric.value),
                        )
            if hasattr(self.track3.source, "set_execution_totals"):
                total_fees = common.total_fees
                premium_spent = None
                if self.track9_position_execution_source is not None and self.run_id:
                    position_snapshot = self.track9_position_execution_source.snapshot(
                        run_id=self.run_id, strategy_id="Strategy_3_StatArb"
                    )
                    if position_snapshot is not None:
                        premium_spent = position_snapshot.premium_spent
                if total_fees is not None and premium_spent is not None:
                    self.track3.source.set_execution_totals(
                        observed_at=market_state.as_of,
                        total_fees=Decimal(str(total_fees)),
                        premium_spent=Decimal(str(premium_spent)),
                    )
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

        # Track5 requires the authoritative KOSPI200 daily boundary and a
        # liquid second/third OTM option selection for the execution contract.
        daily_status = d.status.get("kospi200_daily")
        track5_execution_input = None
        track5_missing = []
        if daily_status is None or not daily_status.available:
            track5_missing.append("KOSPI200_daily_open_previous_close")
        elif self.track5_option_contract_source is None:
            track5_missing.append("track5_option_contract_source")
        else:
            try:
                gap_direction = (
                    "CALL" if Decimal(str(d.open_price)) > Decimal(str(d.previous_close))
                    else "PUT"
                )
                # For an opening gap that is initially flat, choose from the
                # current underlying move; the strategy itself still enforces
                # the 30-minute opening-window condition.
                if Decimal(str(d.open_price)) == Decimal(str(d.previous_close)):
                    gap_direction = "CALL" if Decimal(str(d.underlying_price)) >= Decimal(str(d.open_price)) else "PUT"
                selection = self.track5_option_contract_source.select(
                    expiry=str(getattr(tick, "expiry", "") or ""),
                    current_price=Decimal(str(d.underlying_price)),
                    option_type=gap_direction,
                )
                track5_execution_input = Track5ExecutionInput(
                    expiry=selection.expiry,
                    atm_strike=selection.atm_strike,
                    selected_strike=selection.selected_strike,
                    option_type=selection.option_type,
                    strike_rank=selection.strike_rank,
                    liquidity_score=selection.liquidity_score,
                )
            except (ValueError, TypeError, AttributeError) as exc:
                track5_missing.append(str(exc))
        if track5_missing:
            contexts["track5_gap_divergence"] = self._unavailable(
                "track5_gap_divergence",
                tuple(dict.fromkeys(track5_missing)),
                "TRACK5_REQUIRED_EXECUTION_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["track5_gap_divergence"] = StrategyContext(
                market_state,
                "track5_gap_divergence",
                StrategyInput(common, track5_execution_input),
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
                    expiry=getattr(tick, "expiry", ""), current_price=(Decimal(str(getattr(tick, "underlying_price"))) if getattr(tick, "underlying_price", None) is not None else None)
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

        # Track7 consumes canonical analytics only when every required source and
        # the authoritative Option Master contract pair are available.
        track7_missing_sources: list[str] = []
        if not all(value is not None for value in (d.is_new_week_start, d.is_expiry_day)):
            track7_missing_sources.append("expiry_calendar")

        track7_selection = None
        if self.track7_option_contract_source is None:
            track7_missing_sources.append("listed_option_contracts")
        else:
            try:
                track7_selection = self.track7_option_contract_source.select(
                    expiry=str(getattr(tick, "expiry", "") or ""),
                    reference_price=Decimal(str(getattr(tick, "underlying_price"))),
                )
            except (ValueError, TypeError, AttributeError):
                track7_missing_sources.append("listed_option_contracts")

        track7_option_prices = {}
        if track7_selection is not None and self.option_orderbook_source is not None:
            try:
                put_book = self.option_orderbook_source.get_order_book(str(track7_selection.put.shrn_iscd))
                call_book = self.option_orderbook_source.get_order_book(str(track7_selection.call.shrn_iscd))
                if put_book is not None and call_book is not None and put_book.bid_levels and call_book.bid_levels:
                    track7_option_prices = {
                        "put_mark_price": Decimal(str(put_book.bid_levels[0].price)),
                        "call_mark_price": Decimal(str(call_book.bid_levels[0].price)),
                    }
            except (AttributeError, TypeError, ValueError):
                track7_option_prices = {}
        # Option marks are required for Strategy7's trailing-profit exit, but they
        # are not required to establish the weekly entry. On the first replay tick
        # the historical book may legitimately have no prior bid for the selected
        # pair. Keep the analytics metric UNAVAILABLE in that case instead of
        # turning the whole strategy input into an unavailable payload.
        if track7_missing_sources:
            contexts["track7_volatility_skew_weekly_insurance"] = self._unavailable(
                "track7_volatility_skew_weekly_insurance", tuple(track7_missing_sources),
                "TRACK7_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            execution_input = Track7ExecutionInput(
                strategy_id="track7_volatility_skew_weekly_insurance",
                expiry=track7_selection.expiry,
                reference_price=Decimal(str(getattr(tick, "underlying_price"))),
                put_strike=track7_selection.put_strike,
                call_strike=track7_selection.call_strike,
                contract_multiplier=track7_selection.contract_multiplier,
            )
            contexts["track7_volatility_skew_weekly_insurance"] = StrategyContext(
                market_state, "track7_volatility_skew_weekly_insurance",
                StrategyInput(common, execution_input),
                analytics=build_track7_analytics_snapshot(
                    d, run_id=self.run_id or "virtual", as_of=d.as_of,
                    common_snapshot=common_analytics,
                    option_prices=track7_option_prices,
                ),
            )

        track8_selection = None
        if self.track8_option_contract_source is not None:
            try:
                expiry = str(d.option_expiry or getattr(tick, "expiry", ""))
                current_price = Decimal(str(getattr(tick, "underlying_price"))) if getattr(tick, "underlying_price", None) is not None else None
                track8_selection = self.track8_option_contract_source.select(
                    expiry=expiry, current_price=current_price
                )
            except (ValueError, TypeError, AttributeError):
                track8_selection = None

        # Track8 receives canonical common analytics only when every required
        # source is available. Common metrics are checked by AnalyticsStatus rather
        # than by the legacy RuntimeInput fields.
        track8_common_required = (
            "market.current_regime",
            "volatility.active",
            "portfolio.current_pnl",
            "portfolio.total_fees",
            "portfolio.margin_ratio",
            "risk.guard_active",
        )
        track8_common_missing = tuple(
            metric_key
            for metric_key in track8_common_required
            if (
                (metric := common_analytics.get(metric_key)) is None
                or metric.status != AnalyticsStatus.AVAILABLE
            )
        )
        track8_required = (
            d.days_to_expiry,
            d.option_iv,
            d.put_iv,
            track8_selection,
            self.track9_margin_ratio,
        )
        if not all(value is not None for value in track8_required) or track8_common_missing:
            missing = []
            if track8_selection is None:
                missing.append("track8_authoritative_option_contract")
            if d.days_to_expiry is None:
                missing.append("dte")
            if d.option_iv is None or d.put_iv is None:
                missing.append("option_iv_chain")
            if self.track9_margin_ratio is None:
                missing.append("margin_read_model")
            missing.extend(track8_common_missing)
            contexts["track8_macro_regime_monthly_strangle"] = self._unavailable(
                "track8_macro_regime_monthly_strangle",
                tuple(dict.fromkeys(missing)),
                "TRACK8_REQUIRED_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["track8_macro_regime_monthly_strangle"] = StrategyContext(
                market_state, "track8_macro_regime_monthly_strangle", StrategyInput(common),
                analytics=build_track8_analytics_snapshot(
                    d, run_id=self.run_id or "virtual", as_of=d.as_of,
                    option_contract_selection=track8_selection,
                    common_snapshot=common_analytics,
                ),
            )

        # Strategy9 is deliberately independent of macro/event/IV indicators.
        # Its only strategy-specific market dependency is the authoritative
        # ATM PUT/CALL contract pair used for the overnight insurance.
        track9_common_required = ("price.last",)
        track9_strategy_required = (
            "options.atm_call_strike",
            "options.atm_put_strike",
            "options.contract_multiplier",
        )
        track9_required = track9_common_required + track9_strategy_required

        track9_selection = None
        if self.track6_option_contract_source is not None:
            try:
                track9_selection = self.track6_option_contract_source.select(
                    expiry=getattr(tick, "expiry", ""),
                    current_price=(
                        Decimal(str(getattr(tick, "underlying_price")))
                        if getattr(tick, "underlying_price", None) is not None
                        else None
                    ),
                )
            except (ValueError, TypeError, AttributeError):
                track9_selection = None

        track9_option_prices = {}
        if track9_selection is not None and self.option_orderbook_source is not None:
            try:
                put_book = self.option_orderbook_source.get_order_book(
                    str(track9_selection.put.shrn_iscd)
                )
                call_book = self.option_orderbook_source.get_order_book(
                    str(track9_selection.call.shrn_iscd)
                )
                if (
                    put_book is not None
                    and call_book is not None
                    and put_book.ask_levels
                    and call_book.ask_levels
                    and put_book.bid_levels
                    and call_book.bid_levels
                ):
                    track9_option_prices = {
                        "put_mark_price": Decimal(str(put_book.bid_levels[0].price)),
                        "call_mark_price": Decimal(str(call_book.bid_levels[0].price)),
                    }
            except (AttributeError, TypeError, ValueError):
                track9_option_prices = {}

        # Entry prices become authoritative only after the VSSF reports both
        # option legs FILLED. Never substitute the pre-trade ASK as a fill price.
        if self.track9_position_execution_source is not None and self.run_id:
            execution_snapshot = self.track9_position_execution_source.snapshot(
                run_id=self.run_id,
                strategy_id="track9_event_overnight_insurance",
            )
            if execution_snapshot is not None:
                put_ts = execution_snapshot.put_entry_timestamp
                call_ts = execution_snapshot.call_entry_timestamp
                current_date = d.as_of.date()
                if (
                    put_ts is not None
                    and call_ts is not None
                    and getattr(put_ts, "date", lambda: None)() == current_date
                    and getattr(call_ts, "date", lambda: None)() == current_date
                    and execution_snapshot.put_entry_price is not None
                    and execution_snapshot.call_entry_price is not None
                ):
                    track9_option_prices["put_entry_price"] = execution_snapshot.put_entry_price
                    track9_option_prices["call_entry_price"] = execution_snapshot.call_entry_price

        track9_analytics = build_track9_analytics_snapshot(
            d,
            run_id=self.run_id or "virtual",
            as_of=d.as_of,
            option_contract_selection=track9_selection,
            option_prices=track9_option_prices,
            common_snapshot=common_analytics,
        )
        track9_missing = tuple(
            key for key in track9_required
            if (
                track9_analytics is None
                or track9_analytics.get(key) is None
                or track9_analytics.get(key).status != AnalyticsStatus.AVAILABLE
            )
        )
        if track9_selection is None:
            track9_missing = tuple(
                dict.fromkeys(track9_missing + ("track9_authoritative_option_contract",))
            )
        if track9_missing:
            contexts["track9_event_overnight_insurance"] = self._unavailable(
                "track9_event_overnight_insurance",
                track9_missing,
                "TRACK9_REQUIRED_CANONICAL_AND_AUTHORITATIVE_SOURCES_UNAVAILABLE",
            )
        else:
            contexts["track9_event_overnight_insurance"] = StrategyContext(
                market_state,
                "track9_event_overnight_insurance",
                StrategyInput(common),
                analytics=track9_analytics,
            )
        return contexts
