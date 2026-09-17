from datetime import datetime

from contracts.clock import ClockProvider
from environments.virtual.authoritative_vssf.canonical import CanonicalMarketTick, VSSFOrderResult
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
        self.metrics = {"market_ticks": 0, "order_commands": 0, "executions_issued": 0, "settlement_runs": 0}

    @property
    def orderbook(self):
        return self.order_book

    def attach_clock(self, clock: ClockProvider) -> None:
        self.clock = clock

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
        self.account.update_tick_price(tick.underlying_price)
        self.process_pending_orders()

    def process_order(self, command):
        self.metrics["order_commands"] += 1
        now = self._now()
        if self.account.free_margin < self.margin_engine.calculate_order_margin(command):
            return None
        price = self.order_book.match_order(command)
        if price <= 0:
            self.order_book.add_pending_order(command)
            self._submitted_at[command.client_order_id] = now
            return VSSFOrderResult(
                client_order_id=command.client_order_id,
                status="NEW",
                submitted_at=now.isoformat(), observed_at=now.isoformat(),
                remaining_qty=int(command.qty), track_id=command.track_id,
                asset_type=command.asset_type, side=command.side,
                symbol=getattr(command, "symbol", "KOSPI200"),
            )
        return self._execute(command, price, now)

    def process_pending_orders(self):
        for command in tuple(self.order_book.pending_orders()):
            price = self.order_book.match_order(command)
            if price > 0:
                self._execute(command, price, self._now())

    def _execute(self, command, price, now):
        self.order_book.remove_pending_order(command.client_order_id)
        submitted_at = self._submitted_at.setdefault(command.client_order_id, now)
        rep = self.execution_engine.execute_order(command, price, command.qty, timestamp=now)
        self.account.apply_execution(rep)
        self.account.update_tick_price(price)
        self.metrics["executions_issued"] += 1
        return rep

    def query_order(self, client_order_id):
        submitted_at = self._submitted_at.get(client_order_id)
        if submitted_at is None:
            return None
        now = self._now()
        pending = self.order_book.get_pending_order(client_order_id)
        if pending is not None:
            return VSSFOrderResult(
                client_order_id=client_order_id, status="NEW",
                submitted_at=submitted_at.isoformat(), observed_at=now.isoformat(),
                remaining_qty=int(pending.qty), track_id=pending.track_id,
                asset_type=pending.asset_type, side=pending.side,
                symbol=getattr(pending, "symbol", "KOSPI200"),
            )
        for rep in reversed(self.execution_engine.reports):
            if rep.client_order_id == client_order_id:
                return rep
        return None

    def cancel_order(self, client_order_id):
        now = self._now()
        command = self.order_book.remove_pending_order(client_order_id)
        submitted_at = self._submitted_at.get(client_order_id)
        if command is None or submitted_at is None:
            return None
        return VSSFOrderResult(
            client_order_id=client_order_id, status="CANCELLED",
            submitted_at=submitted_at.isoformat(), observed_at=now.isoformat(),
            remaining_qty=int(command.qty), track_id=command.track_id,
            asset_type=command.asset_type, side=command.side,
            symbol=getattr(command, "symbol", "KOSPI200"),
        )

    def run_settlement(self, final_settlement_price=None):
        self.metrics["settlement_runs"] += 1
        return self.settlement_engine.perform_eod_settlement(final_settlement_price or 350.0)

    def get_account_snapshot(self):
        return self.account.get_canonical_summary()

    def run_reconciliation(self):
        return self.reconciliation_engine.reconcile_state(
            self.get_account_snapshot(), self.execution_engine.reports, self.account.positions
        )
