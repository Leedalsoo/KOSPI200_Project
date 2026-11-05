from datetime import datetime
from decimal import Decimal

from contracts.clock import ClockProvider
from environments.virtual.authoritative_vssf.canonical import CanonicalMarketTick, VSSFExecutionFill, VSSFOrderResult
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from environments.virtual.authoritative_vssf.execution_engine import ExecutionEngine
from environments.virtual.authoritative_vssf.order_book import OrderBook
from environments.virtual.authoritative_vssf.reconciliation import AuthoritativeReconciliationEngine
from environments.virtual.authoritative_vssf.settlement_engine import SettlementEngine
from environments.virtual.authoritative_vssf.state_recovery import StateRecoveryEngine


class VirtualSecuritiesFirmRuntime:
    """Authoritative Virtual Broker/VSSF order and execution state owner."""

    def __init__(self, initial_capital=25000000.0, *, clock: ClockProvider | None = None):
        self.account = PaperTradingAccount(initial_capital)
        self.execution_engine = ExecutionEngine()
        self.order_book = OrderBook()
        self.reconciliation_engine = AuthoritativeReconciliationEngine(initial_capital)
        self.settlement_engine = SettlementEngine(self.account)
        self.recovery_engine = StateRecoveryEngine(self.account)
        self.margin_engine = self.account.margin_engine
        self.clock = clock
        self._market_time: datetime | None = None
        self._submitted_at: dict[str, datetime] = {}
        self._lifecycle_results: dict[str, VSSFOrderResult] = {}
        self.timeout_source = None
        self.metrics = {"market_ticks": 0, "order_commands": 0, "executions_issued": 0, "settlement_runs": 0}

    @property
    def orderbook(self):
        return self.order_book

    def attach_clock(self, clock: ClockProvider) -> None:
        self.clock = clock

    def attach_timeout_source(self, source) -> None:
        self.timeout_source = source

    def _now(self) -> datetime:
        if self.clock is not None:
            return self.clock.now()
        if self._market_time is not None:
            return self._market_time
        raise RuntimeError("VSSF_RUNTIME_CLOCK_REQUIRED")

    def process_market_data(self, tick):
        self.metrics["market_ticks"] += 1
        self._market_time = datetime.fromisoformat(tick.timestamp)
        self.order_book.update_bid_ask(tick.bid_price, tick.ask_price, instrument_id=getattr(tick, "instrument_id", None))
        mark_price = getattr(tick, "last_price", None)
        if mark_price is not None and float(mark_price) > 0:
            self.account.update_tick_price(mark_price, getattr(tick, "symbol", None) or getattr(tick, "instrument_id", None))
        self.process_pending_orders()
        if self.timeout_source is not None:
            self.process_timeouts()

    def process_futures_market_data(self, quote):
        """Consume authoritative futures quote data without changing option VMS state."""
        self.metrics["market_ticks"] += 1
        self._market_time = quote.observed_at
        self.order_book.update_bid_ask(
            quote.bid_price,
            quote.ask_price,
            instrument_id=quote.instrument_id,
        )
        if quote.last_price is not None and float(quote.last_price) > 0:
            self.account.update_tick_price(quote.last_price, quote.instrument_id)
        self.process_pending_orders()
        if self.timeout_source is not None:
            self.process_timeouts()

    def process_order(self, command):
        self.metrics["order_commands"] += 1
        now = self._now()
        symbol = str(getattr(command, "symbol", None) or getattr(command, "instrument_id", None) or "").strip()
        current_position = self.account.positions.get(symbol)
        order_side = getattr(command.side, "value", command.side)
        if isinstance(current_position, dict):
            current_side = current_position.get("side")
            current_qty = int(current_position.get("qty", 0))
        else:
            current_side = getattr(current_position, "side", None) if current_position is not None else None
            current_qty = int(getattr(current_position, "qty", 0)) if current_position is not None else 0
        is_pure_reduction = (
            current_qty > 0
            and str(current_side).upper() in {"BUY", "SELL"}
            and str(order_side).upper() in {"BUY", "SELL"}
            and str(current_side).upper() != str(order_side).upper()
            and int(command.qty) <= current_qty
        )
        if not is_pure_reduction and self.account.free_margin < self.margin_engine.calculate_order_margin(command):
            return None
        self._submitted_at.setdefault(command.client_order_id, now)
        if self.timeout_source is not None:
            self.timeout_source.observe_submission(
                command.client_order_id, command.track_id, now
            )
        price = self.order_book.match_order(command)
        if price <= 0:
            self.order_book.add_pending_order(command)
            self._submitted_at[command.client_order_id] = now
            result = VSSFOrderResult(
                client_order_id=command.client_order_id,
                status="NEW",
                submitted_at=now.isoformat(), observed_at=now.isoformat(),
                remaining_qty=int(command.qty), track_id=command.track_id,
                asset_type=command.asset_type, side=command.side,
                symbol=getattr(command, "symbol", "KOSPI200"),
            )
            self._lifecycle_results[command.client_order_id] = result
            return result
        return self._execute(command, price, now)

    def process_pending_orders(self):
        for command in tuple(self.order_book.pending_orders()):
            filled, _exec_id, _price, _fee, _executed_at, reconciliation_status, _fills = (
                self._execution_snapshot(
                    command.client_order_id, expected_quantity=int(command.qty)
                )
            )
            if reconciliation_status:
                # Ambiguous or overfilled execution history must never trigger another fill.
                continue
            remaining = int(command.qty) - filled
            if remaining < 0:
                continue
            if remaining == 0:
                self.order_book.remove_pending_order(command.client_order_id)
                self._record_order_lifecycle(command, self._now(), "FILLED")
                continue
            price = self.order_book.match_order(command)
            if price > 0:
                self._execute(command, price, self._now(), quantity=remaining)

    def _record_order_lifecycle(self, command, now, status):
        submitted_at = self._submitted_at.get(command.client_order_id)
        if submitted_at is None:
            raise RuntimeError("VSSF_ORDER_SUBMISSION_TIME_REQUIRED")
        filled, exec_id, executed_price, fee, executed_at, reconciliation_status, fills = (
            self._execution_snapshot(
                command.client_order_id, expected_quantity=int(command.qty)
            )
        )
        if reconciliation_status:
            status = "RECONCILIATION_REQUIRED"
        elif filled == int(command.qty) and filled > 0:
            status = "FILLED"
        elif status == "FILLED":
            raise RuntimeError("VSSF_ORDER_FILLED_QUANTITY_MISMATCH")
        else:
            status = "PARTIALLY_FILLED" if filled > 0 else "NEW"
        self._lifecycle_results[command.client_order_id] = VSSFOrderResult(
            client_order_id=command.client_order_id,
            status=status,
            submitted_at=submitted_at.isoformat(),
            observed_at=now.isoformat(),
            remaining_qty=max(0, int(command.qty) - filled),
            exec_id=exec_id,
            executed_qty=filled,
            executed_price=executed_price,
            track_id=command.track_id,
            asset_type=command.asset_type,
            side=command.side,
            symbol=getattr(command, "symbol", "KOSPI200"),
            fee=fee,
            lifecycle_reason=None,
            executed_at=executed_at,
            execution_fills=fills,
        )
        if status == "FILLED":
            self.order_book.remove_pending_order(command.client_order_id)
            if self.timeout_source is not None:
                self.timeout_source.observe(command.client_order_id, now, "FILLED")

    def _execute(self, command, price, now, *, quantity=None):
        submitted_at = self._submitted_at.setdefault(command.client_order_id, now)
        already_filled, _exec_id, _price, _fee, _executed_at, reconciliation_status, _fills = (
            self._execution_snapshot(
                command.client_order_id, expected_quantity=int(command.qty)
            )
        )
        if reconciliation_status:
            raise RuntimeError("VSSF_EXECUTION_HISTORY_RECONCILIATION_REQUIRED")
        remaining = int(command.qty) - already_filled
        execution_quantity = remaining if quantity is None else int(quantity)
        if execution_quantity <= 0 or execution_quantity > remaining:
            raise RuntimeError("VSSF_EXECUTION_REMAINING_QUANTITY_INVALID")

        rep = self.execution_engine.execute_order(
            command, price, execution_quantity, timestamp=now
        )
        self.account.apply_execution(rep)
        self.account.update_tick_price(price, getattr(command, "symbol", None))
        self.metrics["executions_issued"] += 1
        if self.order_book.get_pending_order(command.client_order_id) is None:
            if execution_quantity < remaining:
                self.order_book.add_pending_order(command)
        fill_status = "FILLED" if execution_quantity == remaining else "PARTIALLY_FILLED"
        self._record_order_lifecycle(command, now, fill_status)
        return rep

    def _execution_snapshot(self, client_order_id, expected_quantity=None):
        reports = tuple(
            rep for rep in self.execution_engine.reports
            if rep.client_order_id == client_order_id
        )
        if not reports:
            return 0, None, None, None, None, None, ()
        fills_by_id = {}
        for rep in reports:
            execution_id = str(getattr(rep, "exec_id", "") or "").strip()
            quantity = int(getattr(rep, "executed_qty", 0) or 0)
            price = getattr(rep, "executed_price", None)
            fee = getattr(rep, "fee", 0.0)
            timestamp = getattr(rep, "timestamp", None)
            if (
                not execution_id or quantity <= 0 or price is None
                or Decimal(str(price)) <= 0 or fee is None
                or Decimal(str(fee)) < 0 or not timestamp
            ):
                return 0, None, None, None, None, "RECONCILIATION_REQUIRED", ()
            fingerprint = (
                quantity, Decimal(str(price)), Decimal(str(fee)), str(timestamp),
            )
            prior = fills_by_id.get(execution_id)
            if prior is not None:
                if prior != fingerprint:
                    return 0, None, None, None, None, "RECONCILIATION_REQUIRED", ()
                continue
            fills_by_id[execution_id] = fingerprint

        total_quantity = sum(item[0] for item in fills_by_id.values())
        if expected_quantity is not None and total_quantity > int(expected_quantity):
            return total_quantity, None, None, None, None, "RECONCILIATION_REQUIRED", ()
        fills = tuple(
            VSSFExecutionFill(
                exec_id=execution_id,
                executed_qty=values[0],
                executed_price=values[1],
                fee=values[2],
                timestamp=values[3],
            )
            for execution_id, values in sorted(
                fills_by_id.items(), key=lambda item: (item[1][3], item[0])
            )
        )
        weighted_price = (
            sum((Decimal(str(fill.executed_price)) * fill.executed_qty for fill in fills), Decimal("0"))
            / Decimal(total_quantity)
        )
        total_fee = sum((Decimal(str(fill.fee)) for fill in fills), Decimal("0"))
        latest_timestamp = max(fill.timestamp for fill in fills)
        single_execution_id = fills[0].exec_id if len(fills) == 1 else None
        return (
            total_quantity, single_execution_id, weighted_price,
            total_fee, latest_timestamp, None, fills,
        )

    def query_order(self, client_order_id):
        submitted_at = self._submitted_at.get(client_order_id)
        if submitted_at is None:
            return None
        now = self._now()
        pending = self.order_book.get_pending_order(client_order_id)
        if pending is not None:
            filled, exec_id, executed_price, fee, executed_at, reconciliation_status, execution_fills = self._execution_snapshot(
                client_order_id, expected_quantity=int(pending.qty)
            )
            status = reconciliation_status or (
                "RECONCILIATION_REQUIRED" if filled >= int(pending.qty) and filled > 0
                else "PARTIALLY_FILLED" if filled > 0 else "NEW"
            )
            return VSSFOrderResult(
                client_order_id=client_order_id, status=status,
                submitted_at=submitted_at.isoformat(), observed_at=now.isoformat(),
                remaining_qty=max(0, int(pending.qty) - filled), executed_qty=filled,
                exec_id=exec_id, executed_price=executed_price, fee=fee,
                executed_at=executed_at, execution_fills=execution_fills,
                track_id=pending.track_id,
                asset_type=pending.asset_type, side=pending.side,
                symbol=getattr(pending, "symbol", "KOSPI200"),
            )
        lifecycle = self._lifecycle_results.get(client_order_id)
        if lifecycle is not None and lifecycle.status in {"FILLED", "CANCELLED", "REJECTED", "RECONCILIATION_REQUIRED"}:
            return lifecycle
        for rep in reversed(self.execution_engine.reports):
            if rep.client_order_id == client_order_id:
                return rep
        return None

    def cancel_order(self, client_order_id, *, lifecycle_reason: str = "MANUAL"):
        now = self._now()
        command = self.order_book.remove_pending_order(client_order_id)
        submitted_at = self._submitted_at.get(client_order_id)
        if command is None:
            # A fill may win the race against cancellation. Return the recorded
            # terminal result so callers can reconcile it instead of assuming cancel.
            prior = self._lifecycle_results.get(client_order_id)
            if prior is not None and prior.status in {"FILLED", "CANCELLED", "REJECTED"}:
                return prior
            return None
        if submitted_at is None:
            raise RuntimeError("VSSF_CANCEL_SUBMISSION_TIME_UNAVAILABLE")
        if self.timeout_source is not None:
            self.timeout_source.observe(client_order_id, now, "CANCELLED")
        filled, exec_id, executed_price, fee, executed_at, reconciliation_status, execution_fills = self._execution_snapshot(
            client_order_id, expected_quantity=int(command.qty)
        )
        result = VSSFOrderResult(
            client_order_id=client_order_id,
            status=(
                "RECONCILIATION_REQUIRED" if reconciliation_status
                else "FILLED" if filled == int(command.qty) and filled > 0
                else "CANCELLED"
            ),
            submitted_at=submitted_at.isoformat(), observed_at=now.isoformat(),
            remaining_qty=max(0, int(command.qty) - filled), executed_qty=filled,
            exec_id=exec_id, executed_price=executed_price, fee=fee,
            executed_at=executed_at, execution_fills=execution_fills,
            track_id=command.track_id,
            asset_type=command.asset_type, side=command.side,
            symbol=getattr(command, "symbol", "KOSPI200"),
            lifecycle_reason=(None if filled == int(command.qty) and filled > 0 else lifecycle_reason),
        )
        self._lifecycle_results[client_order_id] = result
        return result

    def process_timeouts(self):
        if self.timeout_source is None:
            raise RuntimeError("TRACK7_ORDER_TIMEOUT_SOURCE_REQUIRED")
        timed_out = []
        now = self._now()
        for command in tuple(self.order_book.pending_orders()):
            if self.timeout_source.is_timed_out(command.client_order_id, now, "NEW"):
                timeout_seconds = getattr(getattr(self.timeout_source, "policy", None), "timeout_seconds", None)
                lifecycle_reason = "TIMEOUT_10M" if Decimal(str(timeout_seconds)) == Decimal("600") else "TIMEOUT_POLICY"
                cancel_result = self.cancel_order(
                    command.client_order_id, lifecycle_reason=lifecycle_reason
                )
                # Cancellation is not considered final until a subsequent order
                # query confirms a terminal state. If the order filled first, the
                # query returns FILLED and preserves the execution.
                confirmed = self.query_order(command.client_order_id)
                if confirmed is None or confirmed.status not in {"CANCELLED", "FILLED", "REJECTED"}:
                    raise RuntimeError("VSSF_CANCEL_TERMINAL_CONFIRMATION_REQUIRED")
                timed_out.append(confirmed)
        return tuple(timed_out)

    def run_settlement(self, final_settlement_price=None):
        self.metrics["settlement_runs"] += 1
        return self.settlement_engine.perform_eod_settlement(final_settlement_price or 350.0)

    def get_account_snapshot(self):
        return self.account.get_canonical_summary()

    def run_reconciliation(self):
        return self.reconciliation_engine.reconcile_state(
            self.get_account_snapshot(), self.execution_engine.reports, self.account.positions
        )
