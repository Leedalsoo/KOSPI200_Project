from contracts.trading_date import format_trading_date
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from core.market.session_policy import MarketSessionPolicy
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import NonExecutionEvent, Signal, SignalKind, StrategyContext, StrategyFeatureRequirement
from core.strategy.multi_leg_plan import build_pair_plan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track6_order_lifecycle import (
    Track6LifecycleConfig, Track6LifecycleStatus, Track6OrderLifecycle,
)


@dataclass(frozen=True)
class Track6OptionMark:
    """Identity-bound option quote used for per-leg validation-only MTM."""
    instrument_id: str
    option_type: str
    strike: Decimal
    expiry: str
    bid_price: Decimal
    ask_price: Decimal
    last_price: Decimal
    as_of: datetime
    source: str
    evidence_sha256: str


@dataclass(frozen=True)
class Track6ExecutionInput:
    """Listed contract selection and currently fresh, identity-bound option marks."""
    strategy_id: str
    date_str: str
    time_str: str = "09:00:00"
    listed_put_strike: Decimal | None = None
    listed_call_strike: Decimal | None = None
    contract_multiplier: Decimal | None = None
    listed_put_instrument_id: str | None = None
    listed_call_instrument_id: str | None = None
    listed_put_identity: Any | None = None
    listed_call_identity: Any | None = None
    expiry: str | None = None
    option_marks: tuple[Track6OptionMark, ...] = ()
    ranked_candidates: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Track6State:
    is_active: bool = False
    entry_pending: bool = False
    bought_date: str | None = None
    long_put_strike: Decimal = Decimal("0")
    long_call_strike: Decimal = Decimal("0")
    put_instrument_id: str | None = None
    call_instrument_id: str | None = None
    put_instrument_identity: Any | None = None
    call_instrument_identity: Any | None = None
    put_entry_fill_price: Decimal = Decimal("0")
    call_entry_fill_price: Decimal = Decimal("0")
    put_high_watermark: Decimal = Decimal("0")
    call_high_watermark: Decimal = Decimal("0")
    put_trailing_active: bool = False
    call_trailing_active: bool = False
    put_open: bool = False
    call_open: bool = False
    put_exit_pending: bool = False
    call_exit_pending: bool = False
    force_close_pending: bool = False


class Track6DailyTailInsurance:
    strategy_id = "track6_daily_tail_insurance"
    version = "1.0"
    VOL_TRIGGER_MULTIPLIER = Decimal("1.3")
    INSURANCE_QTY = 1

    def __init__(
        self,
        vol_trigger_multiplier: Decimal = VOL_TRIGGER_MULTIPLIER,
        insurance_qty: int = INSURANCE_QTY,
        *,
        runtime_config_verified: bool = False,
        risk_limits_available: bool = False,
        lifecycle_config: Track6LifecycleConfig | None = None,
        lifecycle_state_store: Any | None = None,
        lifecycle_run_id: str | None = None,
    ) -> None:
        self.vol_trigger_multiplier = vol_trigger_multiplier
        self.insurance_qty = insurance_qty
        # S6 spec has PROVISIONAL/null order-price, freshness and risk settings.
        self.runtime_config_verified = runtime_config_verified
        self.risk_limits_available = risk_limits_available
        self.state = Track6State()
        self.lifecycle_config = lifecycle_config
        self.lifecycle_state_store = lifecycle_state_store
        self.lifecycle_run_id = lifecycle_run_id
        self.lifecycle: Track6OrderLifecycle | None = None
        self.restart_reconciliation_provider = None
        self.restart_reconciliation_restore_provider = None

    @property
    def sequential_lifecycle_enabled(self) -> bool:
        return self.lifecycle_config is not None

    def configure_validation_lifecycle(self, config: Track6LifecycleConfig, *, state_store: Any, run_id: str) -> None:
        if not run_id or state_store is None:
            raise ValueError("TRACK6_VALIDATION_LIFECYCLE_STORE_AND_RUN_ID_REQUIRED")
        self.lifecycle_config = config
        self.lifecycle_state_store = state_store
        self.lifecycle_run_id = run_id
        self.lifecycle = None

    def _ensure_lifecycle(self, trading_date: str) -> Track6OrderLifecycle | None:
        if self.lifecycle_config is None or not self.lifecycle_run_id:
            return None
        if self.lifecycle is not None and self.lifecycle.snapshot.trading_date != trading_date:
            prior = self.lifecycle.snapshot
            if (prior.status in {Track6LifecycleStatus.FLAT_CONFIRMED, Track6LifecycleStatus.ENTRY_WINDOW_CLOSED}
                    and not any(prior.open_quantity.values()) and prior.working_client_order_id is None):
                self.lifecycle = Track6OrderLifecycle(
                    self.lifecycle_config, run_id=self.lifecycle_run_id, trading_date=trading_date,
                )
        if self.lifecycle is None:
            self.lifecycle = Track6OrderLifecycle(
                self.lifecycle_config, run_id=self.lifecycle_run_id, trading_date=trading_date,
            )
            if self.lifecycle_state_store is not None:
                latest = self.lifecycle_state_store.load_latest()
                if latest is not None:
                    prior = latest["snapshot"]
                    prior_flat = (
                        prior.get("status") in {"FLAT_CONFIRMED", "ENTRY_WINDOW_CLOSED"}
                        and not any(int(value) for value in prior.get("open_quantity", {}).values())
                        and not prior.get("working_client_order_id")
                    )
                    if str(prior.get("trading_date")) == trading_date or not prior_flat:
                        self.lifecycle = Track6OrderLifecycle.restore_snapshot(
                            self.lifecycle_config, prior,
                        )
        return self.lifecycle

    def _persist_lifecycle(self) -> None:
        if self.lifecycle is not None and self.lifecycle_state_store is not None:
            self.lifecycle_state_store.append(self.lifecycle.export_snapshot())

    def lifecycle_clock_action(self, now: datetime):
        if self.lifecycle is None:
            return None
        before = self.lifecycle.export_snapshot()
        kst = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul"))
        if kst.strftime("%H:%M:%S") >= "15:10:00" and self.lifecycle.snapshot.status in {
            Track6LifecycleStatus.ORDER_WORKING, Track6LifecycleStatus.CANCEL_PENDING,
        }:
            action = self.lifecycle.force_close_due(now)
        else:
            action = self.lifecycle.timeout_action(now)
        if self.lifecycle.export_snapshot() != before:
            self._persist_lifecycle()
        return action

    def complete_restart_reconciliation(self, *, open_orders: dict[str, str], positions: dict[str, int],
                                         order_ids_match: bool):
        if self.lifecycle is None:
            raise RuntimeError("TRACK6_LIFECYCLE_NOT_INITIALIZED")
        action = self.lifecycle.complete_restart_reconciliation(
            open_orders=open_orders, positions=positions, order_ids_match=order_ids_match,
        )
        self._persist_lifecycle()
        return action

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.last", "volatility.active", "volatility.base", "volatility.ratio",
                "portfolio.premium_spent",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        if not self.sequential_lifecycle_enabled or context.analytics is None:
            return
        data = self._as_execution_input(context)
        if data is None:
            return
        lifecycle = self._ensure_lifecycle(self._as_date(context.analytics))
        if lifecycle is None or lifecycle.snapshot.status != Track6LifecycleStatus.RECONCILIATION_REQUIRED:
            return
        selected = next((item for item in data.ranked_candidates
                         if item.rank == lifecycle.snapshot.selected_rank), None)
        if selected is None:
            return
        self.state = replace(
            self.state,
            bought_date=lifecycle.snapshot.trading_date,
            long_put_strike=Decimal(str(selected.put_strike)),
            long_call_strike=Decimal(str(selected.call_strike)),
            put_instrument_id=selected.put_identity.instrument_id,
            call_instrument_id=selected.call_identity.instrument_id,
            put_instrument_identity=selected.put_identity,
            call_instrument_identity=selected.call_identity,
            is_active=any(lifecycle.snapshot.open_quantity.values()),
            entry_pending=bool(lifecycle.snapshot.working_client_order_id),
            put_open=lifecycle.snapshot.open_quantity.get("put", 0) > 0,
            call_open=lifecycle.snapshot.open_quantity.get("call", 0) > 0,
            put_entry_fill_price=lifecycle.snapshot.average_fill_price.get("put") or Decimal("0"),
            call_entry_fill_price=lifecycle.snapshot.average_fill_price.get("call") or Decimal("0"),
        )
        provider = self.restart_reconciliation_provider
        if not callable(provider):
            return
        open_orders, positions, order_ids_match = provider(data, lifecycle)
        action = self.complete_restart_reconciliation(
            open_orders=open_orders, positions=positions, order_ids_match=order_ids_match,
        )
        if action.kind == "RECONCILED":
            restore_provider = self.restart_reconciliation_restore_provider
            if callable(restore_provider):
                restore_provider(data, lifecycle)
            snapshot = lifecycle.snapshot
            self.state = replace(
                self.state,
                is_active=any(snapshot.open_quantity.values()),
                entry_pending=bool(snapshot.working_client_order_id),
                put_open=snapshot.open_quantity.get("put", 0) > 0,
                call_open=snapshot.open_quantity.get("call", 0) > 0,
            )

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        # Preserve the daily entry-attempt tombstone after a completed exit.
        # A new trading date naturally permits a fresh entry.
        self.state = Track6State(bought_date=self.state.bought_date)

    def on_execution_result(self, purpose: str, result: object) -> None:
        reports = tuple(getattr(result, "reports", ()) or ())
        if (self.sequential_lifecycle_enabled and purpose in {
                "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT",
                "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL",
            } and self.lifecycle is not None):
            report = next((item for item in reversed(reports)
                           if str(getattr(item, "status", "")).upper() == "FILLED"
                           and int(getattr(item, "filled_quantity", 0) or 0) == 1), None)
            if report is None or not bool(getattr(result, "group_complete", False)):
                return
            leg_id = "put" if purpose.endswith("_PUT") else "call"
            action = self.lifecycle.close_leg_filled(leg_id=leg_id, filled_quantity=1)
            self._persist_lifecycle()
            if action.kind in {"LEG_CLOSED", "FLAT_CONFIRMED"}:
                self.state = replace(
                    self.state,
                    put_open=False if leg_id == "put" else self.state.put_open,
                    call_open=False if leg_id == "call" else self.state.call_open,
                    put_exit_pending=False if leg_id == "put" else self.state.put_exit_pending,
                    call_exit_pending=False if leg_id == "call" else self.state.call_exit_pending,
                )
                if action.kind == "FLAT_CONFIRMED":
                    self.reset()
            return
        if (self.sequential_lifecycle_enabled and purpose == "DAILY_TAIL_INSURANCE_FORCE_CLOSE"
                and self.lifecycle is not None):
            flat = bool(getattr(result, "position_flat", False))
            no_pending = int(getattr(result, "pending_legs", 0) or 0) == 0
            action = self.lifecycle.complete_force_close(
                remaining_positions={"put": 0, "call": 0} if flat else dict(self.lifecycle.snapshot.open_quantity),
                orders_reconciled=no_pending,
            )
            self._persist_lifecycle()
            if action.kind == "FLAT_CONFIRMED":
                self.reset()
            return
        if self.sequential_lifecycle_enabled and purpose == "DAILY_TAIL_INSURANCE_ENTRY" and self.lifecycle is not None:
            expected_id = self.lifecycle.snapshot.working_client_order_id
            report = next((item for item in reversed(reports)
                           if getattr(item, "client_order_id", None) == expected_id), None)
            if report is not None:
                observed_at = (getattr(report, "execution_timestamp", None)
                               or getattr(report, "submitted_at", None)
                               or datetime.now(timezone.utc))
                action = self.lifecycle.execution_report(
                    leg_id=str(getattr(report, "leg_id", self.lifecycle.snapshot.working_leg) or ""),
                    client_order_id=str(getattr(report, "client_order_id", "")),
                    status=str(getattr(report, "status", "UNKNOWN")),
                    filled_quantity=int(getattr(report, "filled_quantity", 0) or 0),
                    remaining_quantity=int(getattr(report, "remaining_quantity", 0) or 0),
                    average_fill_price=(Decimal(str(report.execution_price))
                                        if getattr(report, "execution_price", None) is not None else None),
                    now=observed_at,
                )
                snap = self.lifecycle.snapshot
                self.state = replace(
                    self.state,
                    is_active=any(snap.open_quantity.values()),
                    entry_pending=snap.status in {
                        Track6LifecycleStatus.SINGLE_LEG_FILLED,
                        Track6LifecycleStatus.ORDER_WORKING,
                        Track6LifecycleStatus.CANCEL_PENDING,
                    },
                    put_open=snap.open_quantity.get("put", 0) > 0,
                    call_open=snap.open_quantity.get("call", 0) > 0,
                    put_entry_fill_price=snap.average_fill_price.get("put") or self.state.put_entry_fill_price,
                    call_entry_fill_price=snap.average_fill_price.get("call") or self.state.call_entry_fill_price,
                )
                self._persist_lifecycle()
            return
        group_complete = bool(getattr(result, "group_complete", False))
        position_flat = bool(getattr(result, "position_flat", False))
        if purpose == "DAILY_TAIL_INSURANCE_ENTRY" and self.state.entry_pending:
            by_leg = {str(getattr(report, "leg_id", "")).strip().lower(): report for report in reports}
            confirmed = all(
                leg_id in by_leg
                and str(getattr(by_leg[leg_id], "status", "")).strip().upper() == "FILLED"
                and int(getattr(by_leg[leg_id], "filled_quantity", 0) or 0) == self.insurance_qty
                and int(getattr(by_leg[leg_id], "remaining_quantity", -1)) == 0
                and bool(getattr(by_leg[leg_id], "execution_id", None))
                and getattr(by_leg[leg_id], "execution_timestamp", None) is not None
                and getattr(by_leg[leg_id], "execution_price", None) is not None
                and Decimal(str(getattr(by_leg[leg_id], "execution_price", 0))) > 0
                for leg_id in ("put", "call")
            )
            if confirmed and group_complete and not position_flat:
                self.state = replace(
                    self.state, is_active=True, entry_pending=False,
                    put_entry_fill_price=Decimal(str(by_leg["put"].execution_price)),
                    call_entry_fill_price=Decimal(str(by_leg["call"].execution_price)),
                    put_open=True, call_open=True,
                )
            return
        if purpose == "DAILY_TAIL_INSURANCE_FORCE_CLOSE" and self.state.force_close_pending:
            if group_complete and position_flat:
                self.reset()
            return
        if purpose in {"DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT", "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL"}:
            if not (group_complete and position_flat):
                return
            if purpose.endswith("_PUT"):
                self.state = replace(self.state, put_open=False, put_exit_pending=False)
            else:
                self.state = replace(self.state, call_open=False, call_exit_pending=False)
            if not self.state.put_open and not self.state.call_open:
                self.reset()

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        metric = snapshot.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    @staticmethod
    def _as_execution_input(context: StrategyContext) -> Track6ExecutionInput | None:
        payload = getattr(getattr(context, "input", None), "payload", None)
        return payload if isinstance(payload, Track6ExecutionInput) else None

    @staticmethod
    def _as_time(snapshot: AnalyticsSnapshot) -> str:
        return snapshot.as_of.strftime("%H:%M:%S")

    @staticmethod
    def _as_date(snapshot: AnalyticsSnapshot) -> str:
        return format_trading_date(snapshot.as_of.date())

    def evaluate_buy(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        data = self._as_execution_input(context)
        if (analytics is None or data is None or self.state.is_active or self.state.entry_pending
                or not self.runtime_config_verified or not self.risk_limits_available):
            return ()
        if self.state.bought_date == self._as_date(analytics):
            return ()
        # S6 may inspect pre-open replay ticks, but must not submit before the
        # regular 09:00 KST session or after the 11:00 entry cutoff.
        entry_time = self._as_time(analytics)
        if entry_time < "09:00:00" or entry_time >= "11:00:00":
            return ()
        current_price = self._metric(analytics, "price.last")
        active_vol = self._metric(analytics, "volatility.active")
        base_vol = self._metric(analytics, "volatility.base")
        if not all(isinstance(value, Decimal) for value in (current_price, active_vol, base_vol)):
            return ()
        if data.contract_multiplier is None or data.contract_multiplier <= 0:
            return ()
        if (data.listed_put_strike is None or data.listed_call_strike is None
                or not data.listed_put_instrument_id or not data.listed_call_instrument_id
                or not data.expiry):
            return ()
        marks = {mark.instrument_id: mark for mark in data.option_marks}
        put_mark = marks.get(data.listed_put_instrument_id)
        call_mark = marks.get(data.listed_call_instrument_id)
        if not self._valid_option_mark(put_mark, option_type="PUT", strike=data.listed_put_strike,
                                       expiry=data.expiry, as_of=analytics.as_of):
            return ()
        if not self._valid_option_mark(call_mark, option_type="CALL", strike=data.listed_call_strike,
                                       expiry=data.expiry, as_of=analytics.as_of):
            return ()
        if base_vol <= 0 or active_vol < base_vol * self.vol_trigger_multiplier:
            return ()
        if self.sequential_lifecycle_enabled:
            lifecycle = self._ensure_lifecycle(self._as_date(analytics))
            if lifecycle is None or not lifecycle.config_valid:
                return ()
            if not data.ranked_candidates:
                return ()
            if lifecycle.snapshot.status == Track6LifecycleStatus.RECONCILIATION_REQUIRED:
                return ()
            action = lifecycle.start_preflight(
                tuple(data.ranked_candidates), analytics.as_of,
                group_id=f"{self.lifecycle_run_id}-track6-{self.state.bought_date or analytics.as_of.strftime('%Y%m%d')}",
            )
            by_rank = {item.rank: item for item in data.ranked_candidates}
            while action.kind == "PREFLIGHT":
                candidate = by_rank.get(action.rank)
                action = lifecycle.preflight_result(
                    rank=action.rank, available=candidate is not None, now=analytics.as_of,
                )
            if action.kind != "SELECT_RANK":
                self._persist_lifecycle()
                return ()
            candidate = by_rank.get(action.rank)
            if candidate is None:
                self._persist_lifecycle()
                return ()
            self.state = replace(
                self.state, is_active=False, entry_pending=True,
                bought_date=self._as_date(analytics),
                long_put_strike=Decimal(str(candidate.put_strike)),
                long_call_strike=Decimal(str(candidate.call_strike)),
                put_instrument_id=str(candidate.put_identity.instrument_id),
                call_instrument_id=str(candidate.call_identity.instrument_id),
                put_instrument_identity=candidate.put_identity,
                call_instrument_identity=candidate.call_identity,
                put_high_watermark=Decimal("0"), call_high_watermark=Decimal("0"),
                put_trailing_active=False, call_trailing_active=False,
                put_open=False, call_open=False,
                put_exit_pending=False, call_exit_pending=False, force_close_pending=False,
            )
            self._persist_lifecycle()
            return (Signal(
                self.strategy_id, "BUY_INSURANCE", 1.0,
                f"VOL_SPIKE:{active_vol}>={base_vol * self.vol_trigger_multiplier};RANK:{action.rank};SEQUENTIAL_ENTRY",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                    track_id=self.strategy_id, tag_id="DAILY_TAIL_INSURANCE_ENTRY",
                    option_type="PUT", strike=self.state.long_put_strike,
                ),
            ),)
        put_strike = data.listed_put_strike
        call_strike = data.listed_call_strike
        self.state = replace(
            self.state, is_active=False, entry_pending=True,
            bought_date=self._as_date(analytics),
            long_put_strike=put_strike, long_call_strike=call_strike,
            put_instrument_id=data.listed_put_instrument_id,
            call_instrument_id=data.listed_call_instrument_id,
            put_instrument_identity=data.listed_put_identity,
            call_instrument_identity=data.listed_call_identity,
            put_high_watermark=Decimal("0"), call_high_watermark=Decimal("0"),
            put_trailing_active=False, call_trailing_active=False,
            put_open=False, call_open=False,
            put_exit_pending=False, call_exit_pending=False, force_close_pending=False,
        )
        return (Signal(
            self.strategy_id, "BUY_INSURANCE", 1.0,
            f"VOL_SPIKE:{active_vol}>={base_vol * self.vol_trigger_multiplier};PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="DAILY_TAIL_INSURANCE_ENTRY",
                option_type="PUT", strike=put_strike,
            ),
        ),)

    def _close_execution_proposal(self, *, tag_id: str, option_type: str | None = None,
                                  strike: Decimal | None = None) -> StrategyExecutionProposal:
        if self.state.long_put_strike <= 0 or self.state.long_call_strike <= 0:
            raise ValueError("TRACK6_OPTION_SELECTION_REQUIRED")
        return StrategyExecutionProposal(
            proposed_quantity=self.insurance_qty,
            asset_type="OPTION",
            side="SELL",
            track_id=self.strategy_id,
            tag_id=tag_id,
            option_type=option_type,
            strike=strike,
        )

    @staticmethod
    def _valid_option_mark(mark: Track6OptionMark | None, *, option_type: str,
                           strike: Decimal, expiry: str, as_of: datetime) -> bool:
        if mark is None:
            return False
        try:
            return (
                mark.option_type.upper() == option_type
                and Decimal(str(mark.strike)) == Decimal(str(strike))
                and str(mark.expiry).replace("-", "")[:8] == str(expiry).replace("-", "")[:8]
                and mark.as_of.tzinfo is not None and as_of.tzinfo is not None
                and mark.as_of <= as_of
                and mark.bid_price > 0 and mark.ask_price >= mark.bid_price and mark.last_price > 0
                and bool(mark.source) and len(mark.evidence_sha256) == 64
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not (self.state.is_active or self.state.entry_pending) or self.state.long_put_strike <= 0 or self.state.long_call_strike <= 0:
            return None
        if self.state.put_instrument_identity is None or self.state.call_instrument_identity is None:
            return None
        plan = build_pair_plan(group_id=group_id, strategy_id=self.strategy_id,
                               purpose="DAILY_TAIL_INSURANCE_ENTRY",
                               put_strike=self.state.long_put_strike, call_strike=self.state.long_call_strike,
                               put_quantity=self.insurance_qty, call_quantity=self.insurance_qty, side="BUY")
        legs = tuple(
            replace(leg, instrument_identity=(
                self.state.put_instrument_identity if str(leg.option_type).upper() == "PUT"
                else self.state.call_instrument_identity
            ))
            for leg in plan.legs
        )
        return replace(plan, legs=legs)

    def build_sequential_execution_plan(self, group_id: str, *, now: datetime,
                                        client_order_id_factory) -> MultiLegExecutionPlan | None:
        if self.lifecycle is None or not self.sequential_lifecycle_enabled:
            return self.build_execution_plan(group_id)
        if self.state.put_instrument_identity is None or self.state.call_instrument_identity is None:
            return None
        pair = self.build_execution_plan(group_id)
        if pair is None:
            return None
        open_qty = self.lifecycle.snapshot.open_quantity
        leg_id = "call" if open_qty.get("put", 0) else "put"
        leg = next((item for item in pair.legs if item.leg_id.lower() == leg_id), None)
        if leg is None:
            return None
        identity = leg.instrument_identity
        client_order_id = client_order_id_factory(pair, leg, identity)
        action = self.lifecycle.submit_order(
            leg_id=leg_id, client_order_id=client_order_id, quantity=int(leg.quantity), now=now,
        )
        if action.kind != "SUBMIT":
            self._persist_lifecycle()
            return None
        self._persist_lifecycle()
        return replace(pair, legs=(leg,))

    def evaluate_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        data = self._as_execution_input(context)
        if analytics is None or data is None or not self.state.is_active:
            return ()
        if self.state.put_exit_pending or self.state.call_exit_pending or self.state.force_close_pending:
            return ()
        marks = {mark.instrument_id: mark for mark in data.option_marks}
        candidates = (
            ("PUT", self.state.put_open, self.state.put_instrument_id,
             self.state.put_entry_fill_price, self.state.put_high_watermark,
             self.state.put_trailing_active, self.state.long_put_strike),
            ("CALL", self.state.call_open, self.state.call_instrument_id,
             self.state.call_entry_fill_price, self.state.call_high_watermark,
             self.state.call_trailing_active, self.state.long_call_strike),
        )
        for option_type, is_open, instrument_id, entry_price, high_water, trailing_active, strike in candidates:
            if not is_open or not instrument_id or entry_price <= 0:
                continue
            mark = marks.get(instrument_id)
            if not self._valid_option_mark(mark, option_type=option_type, strike=strike,
                                           expiry=data.expiry or "", as_of=analytics.as_of):
                continue
            # Long-option liquidation value is measured at the executable bid, not
            # underlying intrinsic value or a synthetic theoretical mid.
            liquidation_mark = mark.bid_price
            activated_now = not trailing_active and liquidation_mark >= entry_price * Decimal("2.0")
            if activated_now:
                if option_type == "PUT":
                    self.state = replace(self.state, put_trailing_active=True, put_high_watermark=liquidation_mark)
                else:
                    self.state = replace(self.state, call_trailing_active=True, call_high_watermark=liquidation_mark)
                continue
            if not trailing_active:
                continue
            new_high = max(high_water, liquidation_mark)
            if liquidation_mark <= high_water * Decimal("0.90") and high_water > 0:
                tag = f"DAILY_TAIL_INSURANCE_TRAILING_CLOSE_{option_type}"
                proposal = self._close_execution_proposal(tag_id=tag, option_type=option_type, strike=strike)
                if option_type == "PUT":
                    self.state = replace(self.state, put_exit_pending=True, put_high_watermark=new_high)
                else:
                    self.state = replace(self.state, call_exit_pending=True, call_high_watermark=new_high)
                return (Signal(
                    self.strategy_id, "CLOSE", 1.0,
                    f"PER_LEG_TRAILING_STOP:{option_type};BID:{liquidation_mark};HIGH:{high_water};DRAWDOWN:0.10",
                    execution_proposal=proposal,
                ),)
            if new_high != high_water:
                if option_type == "PUT":
                    self.state = replace(self.state, put_high_watermark=new_high)
                else:
                    self.state = replace(self.state, call_high_watermark=new_high)
        return ()

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        if (not self.state.is_active or context.analytics is None or self.state.force_close_pending
                or self.state.put_exit_pending or self.state.call_exit_pending):
            return ()
        time_str = self._as_time(context.analytics)
        if time_str >= "15:10:00":
            if self.state.force_close_pending:
                return ()
            data = self._as_execution_input(context)
            if data is None and (self.state.put_open or self.state.call_open):
                return ()
            marks = {mark.instrument_id: mark for mark in data.option_marks} if data is not None else {}
            if self.state.put_open and not self._valid_option_mark(
                marks.get(self.state.put_instrument_id), option_type="PUT",
                strike=self.state.long_put_strike, expiry=data.expiry or "", as_of=context.analytics.as_of,
            ):
                return ()
            if self.state.call_open and not self._valid_option_mark(
                marks.get(self.state.call_instrument_id), option_type="CALL",
                strike=self.state.long_call_strike, expiry=data.expiry or "", as_of=context.analytics.as_of,
            ):
                return ()
            proposal = self._close_execution_proposal(tag_id="DAILY_TAIL_INSURANCE_FORCE_CLOSE")
            self.state = replace(self.state, force_close_pending=True,
                                 put_exit_pending=self.state.put_open,
                                 call_exit_pending=self.state.call_open)
            return (Signal(
                self.strategy_id, "CLOSE_FORCE", 1.0, "DAILY_INSURANCE_15:10_FORCE_CLOSE",
                execution_proposal=proposal,
            ),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if (self.sequential_lifecycle_enabled and self.lifecycle is not None
                and self.lifecycle.snapshot.status == Track6LifecycleStatus.SINGLE_LEG_FILLED
                and self.lifecycle.snapshot.working_client_order_id is None
                and context.analytics.as_of.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S") < "15:10:00"):
            data = self._as_execution_input(context)
            next_leg = "call" if self.lifecycle.snapshot.open_quantity.get("put", 0) else "put"
            option_type = "CALL" if next_leg == "call" else "PUT"
            strike = self.state.long_call_strike if next_leg == "call" else self.state.long_put_strike
            instrument_id = self.state.call_instrument_id if next_leg == "call" else self.state.put_instrument_id
            mark = next((item for item in (data.option_marks if data is not None else ())
                         if item.instrument_id == instrument_id), None)
            if data is None or not self._valid_option_mark(
                mark, option_type=option_type, strike=strike, expiry=data.expiry or "",
                as_of=context.analytics.as_of,
            ):
                return ()
            return (Signal(
                self.strategy_id, "BUY_INSURANCE_OPPOSITE", 1.0,
                f"SEQUENTIAL_OPPOSITE_LEG:{option_type}",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                    track_id=self.strategy_id, tag_id="DAILY_TAIL_INSURANCE_ENTRY",
                    option_type=option_type, strike=strike,
                ),
            ),)
        if self.state.is_active:
            cutoff = self.evaluate_expiry_cutoff(context)
            return cutoff or self.evaluate_take_profit(context)
        return self.evaluate_buy(context)
