"""Independent Strategy 9: buy an ATM PUT+CALL pair for overnight insurance."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Sequence

from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import (Signal, StrategyContext, StrategyFeatureRequirement,
                                      validate_strategy_features)
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track9_independent_policy import (
    ENTRY_EVALUATION_TIME,
    Track9AtmPair,
    Track9OptionCandidate,
    Track9PolicyBlocked,
    Track9RuntimeInput,
    evaluate_track9_opening_move,
    is_track9_entry_evaluation_time,
    select_nearest_expiry_atm_pair,
)


@dataclass(frozen=True)
class Track9State:
    entry_date: date | None = None
    pair: Track9AtmPair | None = None
    entry_qty: int = 0
    put_entry_fill_price: Decimal | None = None
    call_entry_fill_price: Decimal | None = None
    exit_reason: str | None = None
    state: str = "WAITING_ENTRY"


class Track9EventOvernightInsurance:
    """Independent ATM PUT+CALL overnight insurance; no S1 exposure linkage."""

    strategy_id = "track9_event_overnight_insurance"
    version = "3.0"
    ENTRY_TIME = ENTRY_EVALUATION_TIME
    CONFIGURABLE_PARAMETERS = ()

    def __init__(self, pair_quantity: int = 1,
                 opening_shock_threshold: Decimal = Decimal("0.01"),
                 ENTRY_TIME: time = ENTRY_EVALUATION_TIME,
                 TRAILING_PROFIT_GIVEBACK: Decimal = Decimal("0.30")) -> None:
        if isinstance(pair_quantity, bool) or pair_quantity <= 0:
            raise ValueError("TRACK9_PAIR_QUANTITY_MUST_BE_POSITIVE")
        threshold = Decimal(str(opening_shock_threshold))
        if not threshold.is_finite() or threshold != Decimal("0.01"):
            raise ValueError("TRACK9_OPENING_THRESHOLD_MUST_MATCH_APPROVED_P0")
        self.pair_quantity = int(pair_quantity)
        self.opening_shock_threshold = threshold
        # Legacy manifest fields are accepted for compatibility but never override P0.
        self.ENTRY_TIME = ENTRY_EVALUATION_TIME
        self.state = Track9State()
        self._exit_pending = False
        self.validation_only_runtime = False

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        self._restore_from_open_lots(self._runtime_input(context))

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track9State()
        self._exit_pending = False

    @staticmethod
    def _runtime_input(context: StrategyContext) -> Track9RuntimeInput | None:
        payload = context.input.payload if context.input is not None else None
        return payload if isinstance(payload, Track9RuntimeInput) else None

    @staticmethod
    def _provenance_ready(payload: Track9RuntimeInput) -> bool:
        sources = dict(payload.source_provenance)
        required = ("contract_identity", "contract_multiplier", "tradability", "option_quotes",
                    "previous_official_close", "next_session_official_open", "trading_calendar",
                    "account", "position", "risk_limits")
        return all(sources.get(key) in {"OFFICIAL", "SYNTHETIC"} for key in required)

    @staticmethod
    def _quotes_ready(payload: Track9RuntimeInput, pair: Track9AtmPair) -> bool:
        quotes = {item.instrument_id: item for item in payload.option_quotes}
        for candidate in (pair.put, pair.call):
            quote = quotes.get(candidate.symbol)
            if quote is None:
                return False
            if (quote.option_type != candidate.option_type or quote.expiry != candidate.expiry
                    or quote.strike != candidate.strike or quote.bid <= 0
                    or quote.ask < quote.bid or quote.last <= 0):
                return False
            if quote.observed_at.tzinfo is None or payload.as_of.tzinfo is None:
                return False
            age = (payload.as_of - quote.observed_at).total_seconds()
            if age < 0 or Decimal(str(age)) > payload.max_quote_age_seconds:
                return False
        return True

    def _restore_from_open_lots(self, payload: Track9RuntimeInput | None) -> None:
        if payload is None:
            return
        lots = tuple(item for item in payload.open_lots
                     if item.strategy_id == self.strategy_id and item.side.upper() == "BUY"
                     and item.remaining_quantity > 0)
        if not lots:
            return
        by_type = {item.option_type.upper(): item for item in lots}
        if len(lots) != 2 or set(by_type) != {"PUT", "CALL"}:
            self.state = Track9State(state="RECONCILIATION_REQUIRED")
            return
        put_lot, call_lot = by_type["PUT"], by_type["CALL"]
        if (put_lot.expiry != call_lot.expiry or put_lot.strike != call_lot.strike
                or put_lot.contract_multiplier != call_lot.contract_multiplier
                or put_lot.remaining_quantity != call_lot.remaining_quantity):
            self.state = Track9State(state="RECONCILIATION_REQUIRED")
            return
        put = Track9OptionCandidate(put_lot.instrument_id, put_lot.expiry, "PUT", put_lot.strike,
                                    "STANDARD", put_lot.contract_multiplier, True)
        call = Track9OptionCandidate(call_lot.instrument_id, call_lot.expiry, "CALL", call_lot.strike,
                                      "STANDARD", call_lot.contract_multiplier, True)
        pair = Track9AtmPair(put.expiry, put.strike, put, call, put.contract_multiplier)
        entry_date = min(put_lot.executed_at, call_lot.executed_at).date()
        self.state = Track9State(
            entry_date=entry_date, pair=pair, entry_qty=put_lot.remaining_quantity,
            put_entry_fill_price=put_lot.entry_price, call_entry_fill_price=call_lot.entry_price,
            state="OVERNIGHT_INSURANCE_ACTIVE",
        )

    def mark_exit_pending(self) -> None:
        self._exit_pending = True
        if self.state.pair is not None:
            self.state = replace(self.state, state="EXIT_PENDING")

    def on_execution_result(self, purpose: str, result: object) -> None:
        reports = tuple(getattr(result, "reports", ()) or ())
        if purpose == "OVERNIGHT_INSURANCE":
            filled = {str(getattr(item, "leg_id", "")): item for item in reports
                      if str(getattr(item, "status", "")).upper() == "FILLED"
                      and int(getattr(item, "filled_quantity", 0) or 0) > 0}
            if bool(getattr(result, "group_complete", False)) and {"put", "call"}.issubset(filled):
                self.state = replace(
                    self.state,
                    put_entry_fill_price=Decimal(str(filled["put"].execution_price)),
                    call_entry_fill_price=Decimal(str(filled["call"].execution_price)),
                    state="OVERNIGHT_INSURANCE_ACTIVE",
                )
            else:
                self.state = replace(self.state, state="RECONCILIATION_REQUIRED")
            return
        if purpose != "OVERNIGHT_INSURANCE_CLOSE" or not self._exit_pending:
            return
        if bool(getattr(result, "group_complete", False)) and bool(getattr(result, "position_flat", False)):
            self.state = replace(self.state, state="OVERNIGHT_INSURANCE_CLOSED", exit_reason=None)
            self._exit_pending = False
        else:
            self.state = replace(self.state, state="EXIT_PENDING")

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        keys = ("price.last", "options.atm_call_strike", "options.atm_put_strike",
                "options.contract_multiplier", "options.track9_put_mark_price",
                "options.track9_call_mark_price")
        return tuple(StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
                     for key in keys)

    def _entry_signal(self, payload: Track9RuntimeInput) -> Sequence[Signal]:
        if not is_track9_entry_evaluation_time(payload.as_of.timetz().replace(tzinfo=None)):
            return ()
        try:
            pair = select_nearest_expiry_atm_pair(
                payload.contract_candidates, underlying_price=payload.underlying_price,
                as_of_date=payload.as_of.date(),
            )
        except Track9PolicyBlocked:
            return ()
        if not self._quotes_ready(payload, pair):
            return ()
        self.state = Track9State(
            entry_date=payload.as_of.date(), pair=pair, entry_qty=self.pair_quantity,
            state="ENTRY_PENDING",
        )
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.pair_quantity, asset_type="OPTION", side="BUY",
            track_id=self.strategy_id, tag_id="OVERNIGHT_INSURANCE_ENTRY",
            option_type="PUT", strike=pair.put.strike,
        )
        return (Signal(
            self.strategy_id, "ENTER_OVERNIGHT_ATM_PUT_CALL", 1.0,
            f"S9_P0_ENTRY:15:00;EXPIRY:{pair.expiry:%Y%m%d};ATM:{pair.strike};"
            f"PUT:{pair.put.symbol};CALL:{pair.call.symbol};QTY:{self.pair_quantity};"
            f"PROVENANCE:{payload.provenance};SCENARIO:{payload.scenario_id}",
            execution_proposal=proposal,
        ),)

    def _opening_exit_signal(self, payload: Track9RuntimeInput) -> Sequence[Signal]:
        if self.state.state != "OVERNIGHT_INSURANCE_ACTIVE" or self.state.pair is None:
            return ()
        if self.state.entry_date is None or payload.as_of.date() <= self.state.entry_date:
            return ()
        if not self._quotes_ready(payload, self.state.pair):
            return ()
        try:
            decision = evaluate_track9_opening_move(
                previous_official_close=payload.previous_official_close,
                next_session_official_open=payload.next_session_official_open,
            )
        except Track9PolicyBlocked:
            return ()
        reason = ("OPENING_MOVE_AT_OR_ABOVE_1PCT_CLOSE_INSURANCE" if decision.action == "CLOSE_INSURANCE"
                  else "OPENING_MOVE_BELOW_1PCT_STOP_LOSS")
        self.state = replace(self.state, state="EXIT_PENDING", exit_reason=reason)
        self._exit_pending = True
        proposal = StrategyExecutionProposal(
            proposed_quantity=self.state.entry_qty, asset_type="OPTION", side="SELL",
            track_id=self.strategy_id, tag_id="OVERNIGHT_INSURANCE_CLOSE",
            option_type="PUT", strike=self.state.pair.put.strike,
        )
        return (Signal(
            self.strategy_id, "CLOSE_OVERNIGHT_ATM_PUT_CALL", 1.0,
            f"{reason};MOVE:{decision.move};THRESHOLD:0.01;"
            f"PREVIOUS_CLOSE:{payload.previous_official_close};"
            f"NEXT_OPEN:{payload.next_session_official_open};SCENARIO:{payload.scenario_id}",
            execution_proposal=proposal,
        ),)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            return ()
        payload = self._runtime_input(context)
        if payload is None or not self._provenance_ready(payload) or context.analytics is None:
            return ()
        metrics = validate_strategy_features(self.feature_requirements(), context.analytics)
        if any(metric.status is not AnalyticsStatus.AVAILABLE or metric.value is None for metric in metrics):
            return ()
        if self.state.state == "WAITING_ENTRY":
            return self._entry_signal(payload)
        if self.state.state == "OVERNIGHT_INSURANCE_CLOSED":
            if payload.as_of.time() == self.ENTRY_TIME:
                self.state = Track9State()
                return self._entry_signal(payload)
            return ()
        if self.state.state == "OVERNIGHT_INSURANCE_ACTIVE":
            return self._opening_exit_signal(payload)
        return ()

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal) -> MultiLegExecutionPlan:
        if proposal.asset_type != "OPTION" or proposal.track_id != self.strategy_id:
            raise ValueError("TRACK9_OPTION_EXECUTION_PROPOSAL_REQUIRED")
        pair = self.state.pair
        if pair is None or self.state.entry_qty <= 0:
            raise ValueError("TRACK9_INDEPENDENT_PAIR_STATE_REQUIRED")
        side = str(proposal.side or "").upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("TRACK9_PAIR_SIDE_REQUIRED")
        def identity(candidate: Track9OptionCandidate) -> OptionInstrumentIdentity:
            return OptionInstrumentIdentity(
                instrument_id=candidate.symbol, symbol=candidate.symbol,
                expiry=candidate.expiry.strftime("%Y%m%d"), option_type=candidate.option_type,
                strike=candidate.strike, contract_multiplier=candidate.contract_multiplier,
                identity_source="SYNTHETIC:DERIVED_SCENARIO",
            )
        return MultiLegExecutionPlan(
            group_id=group_id, strategy_id=self.strategy_id,
            purpose="OVERNIGHT_INSURANCE" if side == "BUY" else "OVERNIGHT_INSURANCE_CLOSE",
            legs=(
                ExecutionLeg("put", side, self.state.entry_qty, "PUT", pair.put.strike,
                             position_role="OVERNIGHT_INSURANCE", instrument_identity=identity(pair.put)),
                ExecutionLeg("call", side, self.state.entry_qty, "CALL", pair.call.strike,
                             position_role="OVERNIGHT_INSURANCE", instrument_identity=identity(pair.call)),
            ),
            strategy_code_version=self.version,
        )


__all__ = ("Track9EventOvernightInsurance", "Track9State")
