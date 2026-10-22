from contracts.trading_date import format_trading_date
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.multi_leg_plan import ExecutionLeg
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

@dataclass(frozen=True)
class Track7ExecutionInput:
    strategy_id: str
    expiry: str
    reference_price: Decimal
    put_strike: Decimal
    call_strike: Decimal
    contract_multiplier: Decimal

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc

@dataclass(frozen=True)
class Track7State:
    insurance_active: bool = False
    entry_pending: bool = False
    bought_date: str | None = None
    expiry: str | None = None
    reference_price: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    contract_multiplier: Decimal = Decimal("0")
    peak_profit: Decimal = Decimal("0")
    put_entry_fill_price: Decimal | None = None
    call_entry_fill_price: Decimal | None = None
    put_peak_mark: Decimal = Decimal("0")
    call_peak_mark: Decimal = Decimal("0")
    put_open: bool = False
    call_open: bool = False

    def __post_init__(self) -> None:
        if self.expiry:
            try:
                object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
            except CanonicalOptionExpiryError as exc:
                raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc

class Track7VolatilitySkewWeeklyInsurance:
    strategy_id = "track7_volatility_skew_weekly_insurance"
    version = "1.0"
    INSURANCE_QTY = 1
    STRIKE_OFFSET = Decimal("12.5")
    TRAILING_DRAWDOWN = Decimal("0.10")
    PER_LEG_STOP_MULTIPLE = Decimal("0.50")
    PER_LEG_TRAILING_ACTIVATION_MULTIPLE = Decimal("2.0")
    CONFIGURABLE_PARAMETERS = ("STRIKE_OFFSET", "TRAILING_DRAWDOWN")

    def __init__(
        self,
        insurance_qty: int = INSURANCE_QTY,
        *,
        runtime_config_verified: bool = False,
        risk_limits_available: bool = False,
    ) -> None:
        # Rank selection, timeout split and aggregate risk remain provisional/null.
        self.runtime_config_verified = runtime_config_verified
        self.risk_limits_available = risk_limits_available
        self.insurance_qty = insurance_qty
        self.state = Track7State()
        self._exit_pending = False

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(StrategyFeatureRequirement(k, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
                     for k in ("price.last", "calendar.is_new_week_start", "calendar.is_expiry_day",
                               "volatility.active", "volatility.base",
                               "options.track7_put_mark_price", "options.track7_call_mark_price"))

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track7State()
        self._exit_pending = False

    def mark_exit_pending(self) -> None:
        self._exit_pending = True

    def on_execution_result(self, purpose: str, result: object) -> None:
        """Promote entry only from both authoritative fills; reset only after confirmed flat."""
        reports = tuple(getattr(result, "reports", ()) or ())
        if purpose == "WEEKLY_INSURANCE_ENTRY" and self.state.entry_pending:
            by_leg = {str(getattr(report, "leg_id", "")).lower(): report for report in reports}
            put = by_leg.get("put")
            call = by_leg.get("call")
            def valid_fill(report) -> bool:
                return bool(report) and str(getattr(report, "status", "")).upper() == "FILLED" and int(getattr(report, "filled_quantity", 0) or 0) == self.insurance_qty and int(getattr(report, "remaining_quantity", -1)) == 0 and bool(getattr(report, "execution_id", None)) and getattr(report, "execution_timestamp", None) is not None and isinstance(getattr(report, "execution_price", None), Decimal)
            if valid_fill(put) and valid_fill(call) and bool(getattr(result, "group_complete", False)) and not bool(getattr(result, "position_flat", True)):
                self.state = replace(self.state, insurance_active=True, entry_pending=False,
                    put_entry_fill_price=put.execution_price, call_entry_fill_price=call.execution_price,
                    put_peak_mark=put.execution_price, call_peak_mark=call.execution_price,
                    put_open=True, call_open=True)
            return
        if purpose in {"WEEKLY_INSURANCE_CLOSE_PUT", "WEEKLY_INSURANCE_CLOSE_CALL"} and self._exit_pending:
            if reports and all(str(getattr(r, "status", "")).upper() == "FILLED" and int(getattr(r, "filled_quantity", 0) or 0) == self.insurance_qty and int(getattr(r, "remaining_quantity", -1)) == 0 and bool(getattr(r, "execution_id", None)) and getattr(r, "execution_timestamp", None) is not None for r in reports):
                self.state = replace(self.state, put_open=False if purpose.endswith("_PUT") else self.state.put_open,
                    call_open=False if purpose.endswith("_CALL") else self.state.call_open)
                self._exit_pending = False
                if not self.state.put_open and not self.state.call_open and bool(getattr(result, "position_flat", False)):
                    self.reset()
            return
        if purpose == "WEEKLY_INSURANCE_CLOSE" and self._exit_pending and bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
            self.reset()
        # Partial/unknown outcomes stay pending; do not silently reopen entry evaluation.

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        m = snapshot.get(key)
        if m is None or m.status is not AnalyticsStatus.AVAILABLE:
            return None
        return m.value

    @staticmethod
    def _execution_input(context: StrategyContext) -> Track7ExecutionInput | None:
        payload = getattr(getattr(context, "input", None), "payload", None)
        return payload if isinstance(payload, Track7ExecutionInput) else None

    def _close_signal(self, reason: str, *, option_type: str | None = None) -> Signal:
        if option_type == "PUT":
            tag_id, strike = "WEEKLY_INSURANCE_CLOSE_PUT", self.state.put_strike
        elif option_type == "CALL":
            tag_id, strike = "WEEKLY_INSURANCE_CLOSE_CALL", self.state.call_strike
        else:
            tag_id, strike = "WEEKLY_INSURANCE_CLOSE", self.state.put_strike
        self._exit_pending = True
        return Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE", 1.0, reason,
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                track_id=self.strategy_id, tag_id=tag_id,
                option_type=option_type or "PUT", strike=strike))

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None or self._exit_pending:
            return ()
        if self.state.entry_pending:
            return ()
        if self.state.insurance_active:
            put_mark = self._metric(context.analytics, "options.track7_put_mark_price")
            call_mark = self._metric(context.analytics, "options.track7_call_mark_price")
            if isinstance(put_mark, Decimal) and self.state.put_open and self.state.put_entry_fill_price is not None:
                peak = max(self.state.put_peak_mark, put_mark)
                self.state = replace(self.state, put_peak_mark=peak)
                if put_mark <= self.state.put_entry_fill_price * self.PER_LEG_STOP_MULTIPLE:
                    return (self._close_signal("PUT_LEG_50PCT_STOP", option_type="PUT"),)
                if peak >= self.state.put_entry_fill_price * self.PER_LEG_TRAILING_ACTIVATION_MULTIPLE and put_mark <= peak * (Decimal("1") - self.TRAILING_DRAWDOWN):
                    return (self._close_signal("PUT_LEG_2X_ARMED_10PCT_DRAWDOWN", option_type="PUT"),)
            if isinstance(call_mark, Decimal) and self.state.call_open and self.state.call_entry_fill_price is not None:
                peak = max(self.state.call_peak_mark, call_mark)
                self.state = replace(self.state, call_peak_mark=peak)
                if call_mark <= self.state.call_entry_fill_price * self.PER_LEG_STOP_MULTIPLE:
                    return (self._close_signal("CALL_LEG_50PCT_STOP", option_type="CALL"),)
                if peak >= self.state.call_entry_fill_price * self.PER_LEG_TRAILING_ACTIVATION_MULTIPLE and call_mark <= peak * (Decimal("1") - self.TRAILING_DRAWDOWN):
                    return (self._close_signal("CALL_LEG_2X_ARMED_10PCT_DRAWDOWN", option_type="CALL"),)
            # Exact expiry-day terminal close supersedes per-leg mark triggers.
            if self.state.expiry == context.analytics.as_of.strftime("%Y%m%d"):
                hhmm = context.analytics.as_of.hour * 100 + context.analytics.as_of.minute
                if hhmm >= 1510:
                    return (self._close_signal("WEEKLY_EXACT_EXPIRY_15:10"),)
            return ()
        if not self.runtime_config_verified or not self.risk_limits_available:
            return ()
        # Approved spec: no new entry/retry at or after the group-start day's 15:00 cutoff.
        if context.analytics.as_of.strftime("%H:%M:%S") >= "15:00:00":
            return ()
        if self._metric(context.analytics, "calendar.is_new_week_start") is not True:
            return ()
        active_vol = self._metric(context.analytics, "volatility.active")
        base_vol = self._metric(context.analytics, "volatility.base")
        if not isinstance(active_vol, Decimal) or not isinstance(base_vol, Decimal) or base_vol <= 0 or active_vol < base_vol * Decimal("1.3"):
            return ()
        contract = self._execution_input(context)
        if contract is None or contract.contract_multiplier <= 0:
            return ()
        self.state = replace(self.state, insurance_active=False, entry_pending=True,
            bought_date=format_trading_date(context.analytics.as_of.date()), expiry=contract.expiry,
            reference_price=contract.reference_price, put_strike=contract.put_strike,
            call_strike=contract.call_strike, contract_multiplier=contract.contract_multiplier,
            peak_profit=Decimal("0"), put_open=False, call_open=False)
        return (Signal(self.strategy_id, "BUY_WEEKLY_INSURANCE", 1.0,
            f"NEW_WEEK:{self.state.bought_date};REF:{contract.reference_price};PUT:{contract.put_strike};CALL:{contract.call_strike}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_ENTRY",
                option_type="PUT", strike=contract.put_strike)),)

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal) -> MultiLegExecutionPlan:
        if proposal.option_type not in {"PUT", "CALL"} or proposal.strike is None:
            raise ValueError("TRACK7_EXECUTION_PROPOSAL_CONTRACT_REQUIRED")
        side = str(proposal.side).upper()
        if side == "BUY":
            if not self.runtime_config_verified or not self.risk_limits_available or not self.state.entry_pending:
                raise ValueError("TRACK7_CONFIG_OR_RISK_GATE_BLOCKED")
            if proposal.option_type != "PUT" or Decimal(str(proposal.strike)) != self.state.put_strike:
                raise ValueError("TRACK7_EXECUTION_STRIKE_MISMATCH")
            return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                purpose="WEEKLY_INSURANCE_ENTRY",
                legs=(ExecutionLeg("put","BUY",self.insurance_qty,"PUT",self.state.put_strike),
                      ExecutionLeg("call","BUY",self.insurance_qty,"CALL",self.state.call_strike)))
        if side == "SELL":
            self._exit_pending = True
            if proposal.tag_id == "WEEKLY_INSURANCE_CLOSE_PUT":
                if proposal.option_type != "PUT" or Decimal(str(proposal.strike)) != self.state.put_strike:
                    raise ValueError("TRACK7_PUT_CLOSE_IDENTITY_MISMATCH")
                return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                    purpose="WEEKLY_INSURANCE_CLOSE_PUT",
                    legs=(ExecutionLeg("put","SELL",self.insurance_qty,"PUT",self.state.put_strike),))
            if proposal.tag_id == "WEEKLY_INSURANCE_CLOSE_CALL":
                if proposal.option_type != "CALL" or Decimal(str(proposal.strike)) != self.state.call_strike:
                    raise ValueError("TRACK7_CALL_CLOSE_IDENTITY_MISMATCH")
                return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                    purpose="WEEKLY_INSURANCE_CLOSE_CALL",
                    legs=(ExecutionLeg("call","SELL",self.insurance_qty,"CALL",self.state.call_strike),))
            if proposal.option_type != "PUT" or Decimal(str(proposal.strike)) != self.state.put_strike:
                raise ValueError("TRACK7_EXECUTION_STRIKE_MISMATCH")
            return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                purpose="WEEKLY_INSURANCE_CLOSE",
                legs=(ExecutionLeg("put","SELL",self.insurance_qty,"PUT",self.state.put_strike),
                      ExecutionLeg("call","SELL",self.insurance_qty,"CALL",self.state.call_strike)))
        raise ValueError("TRACK7_EXECUTION_SIDE_REQUIRED")
