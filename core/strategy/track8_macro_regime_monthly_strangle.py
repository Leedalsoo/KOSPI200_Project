from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_CEILING
from typing import Sequence
from core.strategy.contracts import NonExecutionEvent, Signal, StrategyContext
from core.strategy.multi_leg_plan import build_pair_plan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from contracts.analytics import AnalyticsStatus
from core.market.session_policy import MarketSessionPolicy

@dataclass(frozen=True)
class Track8State:
    is_active: bool = False
    premium_spent: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    qty_call: int = 0
    qty_put: int = 0
    entry_date: str | None = None
    expiry: str | None = None
    entry_pending: bool = False
    entry_stage: str = "IDLE"
    entry_group_id: str | None = None
    entry_block_reason: str | None = None
    retry_window_started_at: datetime | None = None
    retry_due_at: datetime | None = None
    retry_leg: str | None = None
    call_retry_count: int = 0
    put_retry_count: int = 0
    call_entry_fill_price: Decimal | None = None
    put_entry_fill_price: Decimal | None = None
    call_peak_mark: Decimal = Decimal("0")
    put_peak_mark: Decimal = Decimal("0")
    call_contract_multiplier: Decimal = Decimal("0")
    put_contract_multiplier: Decimal = Decimal("0")
    call_open: bool = False
    put_open: bool = False
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False
    hysteresis_hold_counter: int = 0
    macro_hedge_scaled: bool = False

class Track8MacroRegimeMonthlyStrangle:
    strategy_id = "track8_macro_regime_monthly_strangle"
    version = "2.0"
    # Decision Log No.1169: require at least 10 trading days to expiry; retire the 200,000 KRW minimum-budget gate.
    DTE_ENTRY: Decimal | None = Decimal("10")
    MIN_BUDGET: Decimal | None = None  # Retired; retained only as a compatibility marker.
    PROFIT_TARGET = Decimal("300000")
    BASE_CALL_QTY = 1
    HIGH_VOL_PUT_QTY_MULTIPLIER = 2
    NORMAL_PUT_QTY_MULTIPLIER = 1.5
    TAKE_PROFIT_RETAIN_RATIO = Decimal("0.85")
    MACRO_HEDGE_MARGIN_LIMIT = Decimal("0.85")
    EXPIRY_HOLD_DTE_CUTOFF = Decimal("4")
    MACRO_HEDGE_SCALE_MULTIPLIER = Decimal("1.5")
    CONFIGURABLE_PARAMETERS = (
        "DTE_ENTRY", "MIN_BUDGET", "BASE_CALL_QTY", "HIGH_VOL_PUT_QTY_MULTIPLIER",
        "NORMAL_PUT_QTY_MULTIPLIER", "TAKE_PROFIT_RETAIN_RATIO",
        "MACRO_HEDGE_MARGIN_LIMIT", "EXPIRY_HOLD_DTE_CUTOFF",
        "MACRO_HEDGE_SCALE_MULTIPLIER",
    )

    def __init__(
        self,
        profit_target: Decimal = PROFIT_TARGET,
        *,
        runtime_config_verified: bool = False,
        risk_limits_available: bool = False,
    ):
        self.profit_target = profit_target
        # First-rank, timeout-split, limit-price and account-risk gates are unresolved.
        self.runtime_config_verified = runtime_config_verified
        self.risk_limits_available = risk_limits_available
        self.state = Track8State()
        self._exit_pending = False
        self.retry_calendar = None

    @staticmethod
    def _retry_kst(value: datetime) -> datetime:
        kst = ZoneInfo("Asia/Seoul")
        return value.replace(tzinfo=kst) if value.tzinfo is None else value.astimezone(kst)

    def initialize(self, context: StrategyContext) -> None: self.reset()
    def on_market_state(self, context: StrategyContext) -> None: return None
    def reset(self) -> None:
        self.state = Track8State()
        self._exit_pending = False

    def on_execution_result(self, purpose: str, result: object) -> None:
        reports = tuple(getattr(result, "reports", ()) or ())
        if purpose == "MONTHLY_STRANGLE_ENTRY" and self.state.entry_pending:
            by_leg = {str(getattr(report, "leg_id", "")).lower(): report for report in reports}
            call = by_leg.get("call")
            put = by_leg.get("put")
            def valid_fill(report, qty: int) -> bool:
                return bool(report) and str(getattr(report, "status", "")).upper() == "FILLED" and int(getattr(report, "filled_quantity", 0) or 0) == qty and int(getattr(report, "remaining_quantity", -1)) == 0 and bool(getattr(report, "execution_id", None)) and getattr(report, "execution_timestamp", None) is not None and isinstance(getattr(report, "execution_price", None), Decimal)
            if valid_fill(call, self.state.qty_call) and valid_fill(put, self.state.qty_put) and bool(getattr(result, "group_complete", False)) and not bool(getattr(result, "position_flat", True)):
                premium = call.execution_price * self.state.qty_call * self.state.call_contract_multiplier + put.execution_price * self.state.qty_put * self.state.put_contract_multiplier
                self.state = replace(self.state, is_active=True, entry_pending=False,
                    call_entry_fill_price=call.execution_price, put_entry_fill_price=put.execution_price,
                    call_peak_mark=call.execution_price, put_peak_mark=put.execution_price,
                    premium_spent=premium, call_open=True, put_open=True)
            return
        if purpose in {"MONTHLY_STRANGLE_CLOSE_CALL", "MONTHLY_STRANGLE_CLOSE_PUT"} and self._exit_pending:
            if reports and all(str(getattr(r, "status", "")).upper() == "FILLED" and int(getattr(r, "remaining_quantity", -1)) == 0 and bool(getattr(r, "execution_id", None)) and getattr(r, "execution_timestamp", None) is not None for r in reports):
                self.state = replace(self.state, call_open=False if purpose.endswith("_CALL") else self.state.call_open,
                    put_open=False if purpose.endswith("_PUT") else self.state.put_open)
                self._exit_pending = False
                if not self.state.call_open and not self.state.put_open:
                    if bool(getattr(result, "position_flat", False)):
                        self.reset()
                    else:
                        self._exit_pending = True
            return
        if purpose == "MONTHLY_STRANGLE_CLOSE" and self._exit_pending and bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
            self.reset()

    @staticmethod
    def _m(snapshot, key):
        metric = snapshot.get(key)
        return None if metric is None or metric.status is not AnalyticsStatus.AVAILABLE else metric.value

    def feature_requirements(self):
        return tuple(self._requirement(k) for k in (
            "options.dte", "options.expiry_date", "options.call_iv", "options.put_iv", "options.atm_iv",
            "options.call_strike", "options.put_strike", "options.call_contract_multiplier",
            "options.put_contract_multiplier", "options.track8_call_mark_price", "options.track8_put_mark_price",
            "options.moneyness", "market.current_regime",
            "volatility.active", "portfolio.current_pnl", "portfolio.total_fees",
            "portfolio.net_pnl", "portfolio.margin_ratio", "risk.guard_active"))

    @staticmethod
    def _requirement(key):
        from core.strategy.contracts import StrategyFeatureRequirement
        return StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))

    def _analytics(self, context):
        return context.analytics

    def evaluate_entry(self, context: StrategyContext) -> Sequence[Signal]:
        a = self._analytics(context)
        if (a is None or self.state.is_active or self.state.entry_pending
                or not self.runtime_config_verified or not self.risk_limits_available
                or self.DTE_ENTRY is None):
            return ()
        dte, regime = self._m(a, "options.dte"), self._m(a, "market.current_regime")
        call, put = self._m(a, "options.call_strike"), self._m(a, "options.put_strike")
        qcall, qput = self._m(a, "options.call_contract_multiplier"), self._m(a, "options.put_contract_multiplier")
        expiry = self._m(a, "options.expiry_date")
        if not all(v is not None for v in (dte, call, put, qcall, qput, expiry)) or dte < self.DTE_ENTRY: return ()
        if qcall <= 0 or qput <= 0 or qcall != qput or not isinstance(expiry, str) or len(expiry) != 8 or not expiry.isdigit(): return ()
        qty_call = 1
        qty_put = 1
        self.state = replace(
            self.state, is_active=False, entry_pending=True, entry_stage="CALL_READY",
            entry_group_id=None, entry_block_reason=None, retry_window_started_at=None,
            retry_due_at=None, retry_leg=None, call_retry_count=0, put_retry_count=0,
            premium_spent=Decimal("0"),
            call_entry_fill_price=None, put_entry_fill_price=None,
            call_open=False, put_open=False, call_strike=call, put_strike=put,
            qty_call=qty_call, qty_put=qty_put, entry_date=context.input.common.date_str,
            expiry=expiry, call_contract_multiplier=Decimal(str(qcall)),
            put_contract_multiplier=Decimal(str(qput)),
        )
        return (Signal(
            self.strategy_id, "BUY_LIMIT_TRANCHE", 1.0,
            f"DTE:{dte};CALL:{call};PUT:{put};QTY_CALL:{qty_call};QTY_PUT:{qty_put};PRICING:MID_PRICE_OFFSET",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=qty_call,
                asset_type="OPTION",
                side="BUY",
                track_id=self.strategy_id,
                tag_id="MONTHLY_STRANGLE_ENTRY_CALL",
                option_type="CALL",
                strike=call,
            ),
        ),)

    def _call_entry_signal(self, *, retry: bool = False) -> Sequence[Signal]:
        if not self.state.entry_pending or self.state.entry_stage not in {"CALL_READY", "CALL_RETRY_READY"}:
            return ()
        suffix = f";RETRY:{self.state.call_retry_count + 1}" if retry else ""
        return (Signal(
            self.strategy_id, "BUY_LIMIT_TRANCHE", 1.0,
            f"SEQUENTIAL_ENTRY:CALL{suffix};EXPIRY:{self.state.expiry}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.state.qty_call, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="MONTHLY_STRANGLE_ENTRY_CALL",
                option_type="CALL", strike=self.state.call_strike,
            ),
        ),)

    def _put_entry_signal(self) -> Sequence[Signal]:
        if not self.state.entry_pending or self.state.entry_stage not in {"PUT_READY", "PUT_RETRY_READY"}:
            return ()
        return (Signal(
            self.strategy_id, "BUY_LIMIT_TRANCHE", 1.0,
            f"SEQUENTIAL_ENTRY:PUT_AFTER_CALL_FILL;EXPIRY:{self.state.expiry}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.state.qty_put,
                asset_type="OPTION", side="BUY", track_id=self.strategy_id,
                tag_id="MONTHLY_STRANGLE_ENTRY_PUT", option_type="PUT",
                strike=self.state.put_strike,
            ),
        ),)

    def evaluate_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.is_active or self._exit_pending:
            return ()
        a = self._analytics(context)
        if a is None:
            return ()
        for option_type, is_open, entry_fill, peak_mark, strike, quantity, metric_key in (
            ("CALL", self.state.call_open, self.state.call_entry_fill_price, self.state.call_peak_mark, self.state.call_strike, self.state.qty_call, "options.track8_call_mark_price"),
            ("PUT", self.state.put_open, self.state.put_entry_fill_price, self.state.put_peak_mark, self.state.put_strike, self.state.qty_put, "options.track8_put_mark_price"),
        ):
            mark = self._m(a, metric_key)
            if not is_open or not isinstance(entry_fill, Decimal) or entry_fill <= 0 or not isinstance(mark, Decimal) or mark < 0:
                continue
            high = max(peak_mark, mark)
            if option_type == "CALL":
                self.state = replace(self.state, call_peak_mark=high)
            else:
                self.state = replace(self.state, put_peak_mark=high)
            reason = None
            if mark <= entry_fill * Decimal("0.50"):
                reason = f"{option_type}_LEG_50PCT_ENTRY_FILL_STOP"
            elif high >= entry_fill * Decimal("2.0") and mark <= high * Decimal("0.90"):
                reason = f"{option_type}_LEG_2X_ARMED_10PCT_DRAWDOWN"
            if reason:
                self._exit_pending = True
                return (Signal(self.strategy_id, "CLOSE_LEG", 1.0, reason,
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=quantity, asset_type="OPTION", requested_price=None, side="SELL",
                        track_id=self.strategy_id, tag_id=f"MONTHLY_STRANGLE_CLOSE_{option_type}",
                        option_type=option_type, strike=strike)),)
        return ()

    def evaluate_macro_regime_protection(self, context: StrategyContext) -> Sequence[Signal]:
        # The approved S8 spec retires the macro PUT add-on/scale-up path.
        return ()
        a = self._analytics(context); regime = self._m(a, "market.current_regime") if a else None
        if regime not in {"HIGH_VOL", "CIRCUIT_BREAKER", "CRASH"}:
            return ()
        if not self.state.is_active or self.state.put_strike <= 0:
            return (Signal(self.strategy_id, "MACRO_HEDGE_SCALE_UP", 1.0,
                f"REGIME:{regime};HEDGE_MULTIPLIER:{self.MACRO_HEDGE_SCALE_MULTIPLIER}",
                kind="NON_EXECUTION",
                non_execution_event=NonExecutionEvent("TRACK8_MACRO_HEDGE_STATE", "MONTHLY_STRANGLE_NOT_ACTIVE")),)
        if self.state.macro_hedge_scaled:
            return ()
        extra_put = max(1, int((Decimal(self.state.qty_put) * (self.MACRO_HEDGE_SCALE_MULTIPLIER - Decimal("1"))).to_integral_value(rounding=ROUND_CEILING)))
        self.state = replace(self.state, macro_hedge_scaled=True)
        return (Signal(self.strategy_id, "MACRO_HEDGE_SCALE_UP", 1.0,
            f"REGIME:{regime};HEDGE_MULTIPLIER:{self.MACRO_HEDGE_SCALE_MULTIPLIER};EXTRA_PUT_QTY:{extra_put}",
            execution_proposal=StrategyExecutionProposal(proposed_quantity=extra_put, asset_type="OPTION", requested_price=None, side="BUY",
                track_id=self.strategy_id, tag_id="MACRO_HEDGE_SCALE_UP", option_type="PUT", strike=self.state.put_strike)),)

    def evaluate_profit_rebuild(self, context: StrategyContext) -> Sequence[Signal]:
        # Dynamic profit/rebuild signals are not approved S8 behavior.
        return ()
        a = self._analytics(context)
        if a is None or not self.state.is_active or self._m(a, "risk.guard_active") is True or (self._m(a, "portfolio.margin_ratio") or Decimal("1")) > self.MACRO_HEDGE_MARGIN_LIMIT: return ()
        if (self._m(a, "portfolio.net_pnl") or Decimal("0")) < self.profit_target: return ()
        return (Signal(self.strategy_id, "DYNAMIC_PROFIT_TAKE", 1.0, f"NET_PNL:{self._m(a,'portfolio.net_pnl')}"), Signal(self.strategy_id, "DYNAMIC_REBUILD_FENCE", 1.0, "REBUILD_REQUIRES_AUTHORITATIVE_OPTION_SELECTION"))

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.is_active or self._exit_pending:
            return ()
        a = self._analytics(context)
        if a is None or not self.state.expiry or self.state.expiry != a.as_of.strftime("%Y%m%d"):
            return ()
        if a.as_of.strftime("%H:%M:%S") < "15:10:00":
            return ()
        self._exit_pending = True
        return (Signal(self.strategy_id, "EXPIRY_FORCE_CLOSE", 1.0, "MONTHLY_EXPIRY_15:10_FORCE_CLOSE",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=max(self.state.qty_call, self.state.qty_put), asset_type="OPTION", side="SELL",
                track_id=self.strategy_id, tag_id="MONTHLY_STRANGLE_CLOSE",
                option_type="PUT", strike=self.state.put_strike)),)

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal | None = None) -> MultiLegExecutionPlan | None:
        if self.state.entry_pending:
            if proposal is None or str(getattr(proposal, "side", "")).upper() != "BUY":
                raise ValueError("TRACK8_SEQUENTIAL_ENTRY_PROPOSAL_REQUIRED")
            tag = str(getattr(proposal, "tag_id", "") or "")
            option_type = str(getattr(proposal, "option_type", "") or "").upper()
            strike = Decimal(str(getattr(proposal, "strike", "0")))
            if self.state.entry_stage in {"CALL_READY", "CALL_RETRY_READY"}:
                if tag != "MONTHLY_STRANGLE_ENTRY_CALL" or option_type != "CALL" or strike != self.state.call_strike:
                    raise ValueError("TRACK8_CALL_FIRST_LEG_IDENTITY_MISMATCH")
                retry = self.state.entry_stage == "CALL_RETRY_READY"
                if not retry and self.state.entry_group_id is not None and self.state.entry_group_id != group_id:
                    raise ValueError("TRACK8_ENTRY_GROUP_ID_CONFLICT")
                attempt_id = f"CALL-RETRY-{self.state.call_retry_count + 1}" if retry else None
                self.state = replace(
                    self.state, entry_group_id=group_id if not retry else self.state.entry_group_id,
                    entry_stage="CALL_PENDING", call_retry_count=self.state.call_retry_count + (1 if retry else 0),
                    retry_due_at=None, retry_leg=None,
                )
                return MultiLegExecutionPlan(
                    group_id=self.state.entry_group_id or group_id, strategy_id=self.strategy_id,
                    purpose="MONTHLY_STRANGLE_ENTRY_CALL",
                    legs=(ExecutionLeg("call", "BUY", self.state.qty_call, "CALL", self.state.call_strike),),
                    attempt_id=attempt_id,
                )
            if self.state.entry_stage in {"PUT_READY", "PUT_RETRY_READY"}:
                if tag != "MONTHLY_STRANGLE_ENTRY_PUT" or option_type != "PUT" or strike != self.state.put_strike:
                    raise ValueError("TRACK8_PUT_SECOND_LEG_IDENTITY_MISMATCH")
                entry_group_id = self.state.entry_group_id
                if not entry_group_id:
                    raise ValueError("TRACK8_ENTRY_GROUP_ID_REQUIRED")
                retry = self.state.entry_stage == "PUT_RETRY_READY"
                attempt_id = f"PUT-RETRY-{self.state.put_retry_count + 1}" if retry else None
                self.state = replace(
                    self.state, entry_stage="PUT_PENDING", put_retry_count=self.state.put_retry_count + (1 if retry else 0),
                    retry_due_at=None, retry_leg=None,
                )
                return MultiLegExecutionPlan(
                    group_id=entry_group_id, strategy_id=self.strategy_id,
                    purpose="MONTHLY_STRANGLE_ENTRY_PUT",
                    legs=(ExecutionLeg("put", "BUY", self.state.qty_put, "PUT", self.state.put_strike),),
                    attempt_id=attempt_id,
                )
            raise ValueError(f"TRACK8_ENTRY_STAGE_NOT_SUBMITTABLE:{self.state.entry_stage}")
        if not self.state.is_active or self.state.call_strike <= 0 or self.state.put_strike <= 0:
            if self.state.entry_pending:
                raise ValueError("TRACK8_SEQUENTIAL_ENTRY_POLICY_UNRESOLVED")
            return None
        if self._exit_pending and proposal is not None and proposal.tag_id in {"MONTHLY_STRANGLE_CLOSE_CALL", "MONTHLY_STRANGLE_CLOSE_PUT"}:
            if proposal.tag_id.endswith("_CALL") and proposal.option_type == "CALL" and Decimal(str(proposal.strike)) == self.state.call_strike:
                return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_CLOSE_CALL", legs=(ExecutionLeg("call", "SELL", self.state.qty_call, "CALL", self.state.call_strike),))
            if proposal.tag_id.endswith("_PUT") and proposal.option_type == "PUT" and Decimal(str(proposal.strike)) == self.state.put_strike:
                return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_CLOSE_PUT", legs=(ExecutionLeg("put", "SELL", self.state.qty_put, "PUT", self.state.put_strike),))
            raise ValueError("TRACK8_CLOSE_LEG_IDENTITY_MISMATCH")
        if self._exit_pending:
            return build_pair_plan(group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_CLOSE", put_strike=self.state.put_strike, call_strike=self.state.call_strike, put_quantity=self.state.qty_put, call_quantity=self.state.qty_call, side="SELL")
        raise ValueError("TRACK8_SEQUENTIAL_ENTRY_POLICY_UNRESOLVED")

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None or self._exit_pending:
            return ()
        if self.state.entry_pending:
            if self.state.entry_stage in {"RETRY_WAIT"}:
                now = getattr(context.analytics, "as_of", None)
                submitted_at = self.state.retry_window_started_at
                if self.retry_calendar is None or not callable(getattr(self.retry_calendar, "is_retry_window_open", None)):
                    self.state = replace(self.state, entry_stage="BLOCKED", entry_block_reason="TRACK8_RETRY_VALIDATION_CALENDAR_UNAVAILABLE")
                    return ()
                if not isinstance(now, datetime) or submitted_at is None or self.state.retry_due_at is None:
                    self.state = replace(self.state, entry_stage="BLOCKED", entry_block_reason="TRACK8_RETRY_TIME_CONTEXT_UNAVAILABLE")
                    return ()
                try:
                    submitted_at = self._retry_kst(submitted_at)
                    now = self._retry_kst(now)
                    due_at = self._retry_kst(self.state.retry_due_at)
                    window_open = self.retry_calendar.is_retry_window_open(submitted_at, now)
                except (TypeError, ValueError):
                    window_open = False
                if not window_open:
                    self.state = replace(self.state, entry_stage="BLOCKED", entry_block_reason="TRACK8_RETRY_WINDOW_CLOSED_OR_UNVERIFIED")
                    return ()
                if now < due_at:
                    return ()
                next_stage = "CALL_RETRY_READY" if self.state.retry_leg == "call" else "PUT_RETRY_READY"
                self.state = replace(self.state, entry_stage=next_stage)
            if self.state.entry_stage in {"CALL_READY", "CALL_RETRY_READY"}:
                return self._call_entry_signal(retry=self.state.entry_stage == "CALL_RETRY_READY")
            if self.state.entry_stage in {"PUT_READY", "PUT_RETRY_READY"}:
                return self._put_entry_signal()
            return ()
        if self.state.is_active:
            expiry_exit = self.evaluate_expiry_cutoff(context)
            if expiry_exit:
                return expiry_exit
            return self.evaluate_take_profit(context)
        return self.evaluate_entry(context)


    def on_execution_result(self, purpose: str, result: object) -> None:
        if purpose not in {"MONTHLY_STRANGLE_ENTRY_CALL", "MONTHLY_STRANGLE_ENTRY_PUT"}:
            return
        leg_id = "call" if purpose.endswith("_CALL") else "put"

        def block_entry(reason: str) -> None:
            preserve_exposure = self.state.call_open or self.state.put_open
            self.state = replace(
                self.state, entry_stage="BLOCKED", entry_block_reason=reason,
                entry_pending=False if preserve_exposure else self.state.entry_pending,
                is_active=True if preserve_exposure else self.state.is_active,
            )

        expected_group = self.state.entry_group_id
        observed_group = str(getattr(result, "group_id", "") or "")
        if not expected_group or observed_group != expected_group:
            block_entry("TRACK8_ENTRY_RESULT_GROUP_ID_MISMATCH")
            return
        quantity = self.state.qty_call if leg_id == "call" else self.state.qty_put

        reports = tuple(getattr(result, "reports", ()) or ())
        report = next((item for item in reversed(reports) if str(getattr(item, "leg_id", "")).lower() == leg_id), None)
        if report is None:
            block_entry(f"TRACK8_{leg_id.upper()}_ENTRY_REPORT_MISSING")
            return
        raw_status = getattr(report, "status", "")
        status = str(getattr(raw_status, "value", raw_status)).upper()
        filled = int(getattr(report, "filled_quantity", 0) or 0)
        remaining = int(getattr(report, "remaining_quantity", max(0, quantity - filled)) or 0)
        if status in {"NEW", "PENDING", "PARTIALLY_FILLED", "ACCEPTED"} and filled < quantity:
            return
        if status == "CANCELLED":
            lifecycle_reason = str(getattr(report, "lifecycle_reason", "") or "").upper()
            if lifecycle_reason != "TIMEOUT_10M":
                block_entry(f"TRACK8_{leg_id.upper()}_CANCEL_NOT_RETRYABLE:{lifecycle_reason or 'UNSPECIFIED'}")
                return
            if filled > 0:
                fill_price = getattr(report, "execution_price", None)
                if filled > quantity:
                    block_entry(f"TRACK8_{leg_id.upper()}_PARTIAL_FILL_QUANTITY_MISMATCH")
                    return
                if fill_price is None or Decimal(str(fill_price)) <= 0:
                    reason = f"TRACK8_{leg_id.upper()}_PARTIAL_FILL_PRICE_UNAVAILABLE"
                    if leg_id == "call":
                        self.state = replace(
                            self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                            call_open=True, qty_call=filled, call_entry_fill_price=None,
                            entry_block_reason=reason,
                        )
                    else:
                        self.state = replace(
                            self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                            put_open=True, qty_put=filled, put_entry_fill_price=None,
                            entry_block_reason=reason,
                        )
                    return
                fill_price = Decimal(str(fill_price))
                if leg_id == "call":
                    premium = fill_price * filled * self.state.call_contract_multiplier
                    self.state = replace(
                        self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                        call_open=True, qty_call=filled, call_entry_fill_price=fill_price,
                        call_peak_mark=fill_price, premium_spent=premium,
                        entry_block_reason="TRACK8_CALL_PARTIAL_FILL_REQUIRES_RECONCILIATION",
                    )
                    return
                if not self.state.call_open or self.state.call_entry_fill_price is None:
                    self.state = replace(
                        self.state, entry_stage="BLOCKED", entry_pending=False,
                        entry_block_reason="TRACK8_PUT_PARTIAL_FILL_WITHOUT_CALL_POSITION",
                    )
                    return
                premium = (
                    self.state.call_entry_fill_price * self.state.qty_call * self.state.call_contract_multiplier
                    + fill_price * filled * self.state.put_contract_multiplier
                )
                self.state = replace(
                    self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                    put_open=True, qty_put=filled, put_entry_fill_price=fill_price,
                    put_peak_mark=fill_price, premium_spent=premium,
                    entry_block_reason="TRACK8_PUT_PARTIAL_FILL_REQUIRES_RECONCILIATION",
                )
                return
            if remaining != quantity:
                reason = f"TRACK8_{leg_id.upper()}_PARTIAL_FILL_REQUIRES_RECONCILIATION"
                if leg_id == "put" and self.state.call_open:
                    self.state = replace(
                        self.state, entry_stage="BLOCKED", entry_pending=False,
                        is_active=True, entry_block_reason=reason,
                    )
                else:
                    self.state = replace(self.state, entry_stage="BLOCKED", entry_block_reason=reason)
                return
            submitted_at = getattr(report, "submitted_at", None)
            observed_at = getattr(report, "execution_timestamp", None)
            if not isinstance(submitted_at, datetime) or not isinstance(observed_at, datetime):
                block_entry("TRACK8_RETRY_ORDER_TIMESTAMPS_UNAVAILABLE")
                return
            submitted_at = self._retry_kst(submitted_at)
            observed_at = self._retry_kst(observed_at)
            window_started_at = self._retry_kst(self.state.retry_window_started_at) if self.state.retry_window_started_at else submitted_at
            if self.retry_calendar is None or not callable(getattr(self.retry_calendar, "is_retry_window_open", None)):
                block_entry("TRACK8_RETRY_VALIDATION_CALENDAR_UNAVAILABLE:CANCELLED")
                return
            try:
                window_open = self.retry_calendar.is_retry_window_open(window_started_at, observed_at)
            except (TypeError, ValueError):
                window_open = False
            retry_count = self.state.call_retry_count if leg_id == "call" else self.state.put_retry_count
            if not window_open:
                reason = "TRACK8_RETRY_WINDOW_CLOSED_OR_UNVERIFIED"
            elif retry_count >= 3:
                reason = f"TRACK8_{leg_id.upper()}_RETRY_LIMIT_REACHED"
            elif observed_at < submitted_at + timedelta(seconds=600):
                reason = "TRACK8_TIMEOUT_BEFORE_10M_CONFIRMATION"
            else:
                self.state = replace(
                    self.state, entry_stage="RETRY_WAIT",
                    retry_window_started_at=window_started_at,
                    retry_due_at=submitted_at + timedelta(seconds=600),
                    retry_leg=leg_id, entry_block_reason=None,
                )
                return
            block_entry(reason)
            return
        if status != "FILLED" or filled != quantity or remaining != 0 or not bool(getattr(result, "group_complete", False)):
            reason = str(getattr(report, "rejected_reason", "") or f"TRACK8_{leg_id.upper()}_ENTRY_NOT_FULLY_FILLED:{status}")
            block_entry(reason)
            return
        fill_price = getattr(report, "execution_price", None)
        if fill_price is None or Decimal(str(fill_price)) <= 0:
            reason = f"TRACK8_{leg_id.upper()}_ENTRY_FILL_PRICE_REQUIRED"
            if leg_id == "call":
                self.state = replace(
                    self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                    call_open=True, qty_call=filled, call_entry_fill_price=None,
                    entry_block_reason=reason,
                )
            else:
                self.state = replace(
                    self.state, entry_stage="BLOCKED", entry_pending=False, is_active=True,
                    put_open=True, qty_put=filled, put_entry_fill_price=None,
                    entry_block_reason=reason,
                )
            return
        fill_price = Decimal(str(fill_price))
        if leg_id == "call":
            self.state = replace(
                self.state, call_open=True, call_entry_fill_price=fill_price,
                call_peak_mark=fill_price, entry_stage="PUT_READY",
                premium_spent=fill_price * self.state.qty_call * self.state.call_contract_multiplier,
                retry_window_started_at=(self.state.retry_window_started_at or getattr(report, "submitted_at", None)),
            )
            return
        if not self.state.call_open or self.state.call_entry_fill_price is None:
            self.state = replace(
                self.state, entry_stage="BLOCKED",
                entry_block_reason="TRACK8_PUT_FILLED_BEFORE_CALL_RECONCILIATION",
            )
            return
        premium = (
            self.state.call_entry_fill_price * self.state.qty_call * self.state.call_contract_multiplier
            + fill_price * self.state.qty_put * self.state.put_contract_multiplier
        )
        self.state = replace(
            self.state, is_active=True, entry_pending=False, entry_stage="COMPLETE",
            put_open=True, put_entry_fill_price=fill_price, put_peak_mark=fill_price,
            premium_spent=premium, entry_block_reason=None,
            retry_window_started_at=(self.state.retry_window_started_at or getattr(report, "submitted_at", None)),
        )
