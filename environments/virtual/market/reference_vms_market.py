"""Reference VMS boundary package placeholder.

The concrete Runtime source is migrated under this environment-owned package.
Standard contracts remain outside this package.
"""

# Reference Exp_Detail_1 VMS Runtime 최소 import closure를 OptionProject Virtual
# Environment 경계에 이식한다. Standard contracts는 projection adapter를 통해서만 연결한다.

# Compatibility re-export. Canonical DTO ownership is shared.contracts.canonical.
from shared.contracts.canonical import (
    CanonicalAccountSummary, CanonicalAssetType, CanonicalExecutionReport,
    CanonicalMarketTick, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

__all__ = [
    "CanonicalAccountSummary", "CanonicalAssetType", "CanonicalExecutionReport",
    "CanonicalMarketTick", "CanonicalOptionType", "CanonicalOrderCommand", "CanonicalOrderSide",
]


class PositionManager:
    def __init__(self):
        self.positions = {}

    def update_position(self, symbol, side, qty, price, **kwargs):
        p = self.positions.get(symbol, {"qty": 0, "avg_price": 0.0, "side": side})
        if p["qty"] == 0 or p["side"] == side:
            total = p["qty"] + qty
            p["avg_price"] = (p["avg_price"] * p["qty"] + price * qty) / total
            p["qty"] = total
            p["side"] = side
            self.positions[symbol] = p
            return 0.0
        close = min(p["qty"], qty)
        pnl = (price - p["avg_price"]) * close * 250000.0 * (1 if p["side"] == "BUY" else -1)
        p["qty"] -= close
        if p["qty"]:
            self.positions[symbol] = p
        else:
            self.positions.pop(symbol, None)
        return pnl


from decimal import Decimal


class PnLEngine:
    def __init__(self):
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def calculate_unrealized(self, positions, current_price, multiplier=Decimal("250000")):
        current = self._decimal(current_price)
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            avg_price = self._decimal(position["avg_price"])
            quantity = self._decimal(position["qty"])
            side = str(position["side"])
            if side == "BUY":
                price_delta = current - avg_price
            elif side == "SELL":
                price_delta = avg_price - current
            else:
                raise ValueError("PNL_POSITION_SIDE_INVALID")
            total += price_delta * quantity * unit_multiplier
        self.unrealized_pnl = total
        return total

    def add_realized(self, amount):
        self.realized_pnl += self._decimal(amount)
        return self.realized_pnl


from decimal import Decimal

MULTIPLIER = Decimal("250000")


class MarginEngine:
    def __init__(self, initial_capital=25000000.0):
        self.initial_capital = Decimal(str(initial_capital))

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def calculate_order_margin(self, command):
        return self._decimal(command.price) * self._decimal(command.qty) * MULTIPLIER

    def calculate_used_margin(self, positions, multiplier=MULTIPLIER):
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            total += (
                self._decimal(position["avg_price"])
                * self._decimal(position["qty"])
                * unit_multiplier
            )
        return total

    def calculate_free_margin(self, total_equity, used_margin):
        return max(Decimal("0"), self._decimal(total_equity) - self._decimal(used_margin))


class LedgerEngine:
    def __init__(self):
        self.transactions = []

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def record_settlement(self, settlement_type, realized_pnl, unrealized_pnl, balance_after, **kwargs):
        row = {
            "type": "SETTLEMENT",
            "settlement_type": settlement_type,
            "realized_pnl": self._decimal(realized_pnl),
            "unrealized_pnl": self._decimal(unrealized_pnl),
            "balance_after": self._decimal(balance_after),
        }
        self.transactions.append(row)
        return row


from datetime import datetime
from decimal import Decimal
from environments.virtual.authoritative_vssf.position_manager import PositionManager as _AuthoritativePositionManager
from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine as _AuthoritativePnLEngine
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine as _AuthoritativeMarginEngine
from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine as _AuthoritativeLedgerEngine
from shared.contracts.canonical import CanonicalAccountSummary


class PaperTradingAccount:
    def __init__(self, initial_capital=25000000.0):
        capital = Decimal(str(initial_capital))
        self.balance = capital
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")
        self.position_mgr = PositionManager()
        self.pnl_engine = PnLEngine()
        self.margin_engine = MarginEngine(initial_capital)
        self.ledger_engine = LedgerEngine()
        self.free_margin = capital
        self.used_margin = Decimal("0")

    @property
    def positions(self):
        return self.position_mgr.positions

    def get_canonical_summary(self):
        total = self.balance + self.realized_pnl + self.unrealized_pnl
        return CanonicalAccountSummary(
            "ACC-VSSF-001", total, self.realized_pnl, self.unrealized_pnl,
            self.used_margin, self.free_margin, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            positions={k: dict(v) for k, v in self.positions.items()},
        )

    def update_tick_price(self, price):
        self.unrealized_pnl = self.pnl_engine.calculate_unrealized(self.positions, price)
        self.used_margin = self.margin_engine.calculate_used_margin(self.positions)
        equity = self.balance + self.realized_pnl + self.unrealized_pnl
        self.free_margin = self.margin_engine.calculate_free_margin(equity, self.used_margin)

    def apply_execution(self, rep):
        pnl = self.position_mgr.update_position(
            rep.symbol,
            rep.side.value if hasattr(rep.side, 'value') else str(rep.side),
            rep.executed_qty,
            rep.executed_price,
        )
        self.pnl_engine.add_realized(pnl)
        self.realized_pnl = self.pnl_engine.realized_pnl
        self.balance -= Decimal(str(rep.fee))
        self.ledger_engine.transactions.append({"exec_id": rep.exec_id})


class OrderBook:
    def __init__(self):
        self.bid = 0.0
        self.ask = 0.0
        self.orders = {}

    def update_bid_ask(self, bid, ask):
        self.bid = float(bid)
        self.ask = float(ask)

    def match_order(self, command):
        return self.ask if str(getattr(command.side, 'value', command.side)) == 'BUY' else self.bid

    def cancel_order(self, client_order_id):
        return self.orders.pop(client_order_id, None) is not None


from datetime import datetime
from environments.virtual.authoritative_vssf.canonical import CanonicalExecutionReport


class ExecutionEngine:
    def __init__(self):
        self.reports = []
        self._seq = 0

    def execute_order(self, command, price, qty):
        self._seq += 1
        rep = CanonicalExecutionReport(
            f"EXEC-{self._seq:06d}", command.client_order_id, command.track_id,
            command.asset_type, command.side, int(qty), float(price), 0.0, 0.0,
            datetime.now().isoformat(), symbol=getattr(command, 'symbol', 'KOSPI200'),
        )
        self.reports.append(rep)
        return rep


class SettlementEngine:
    def __init__(self, account):
        self.account = account

    def perform_eod_settlement(self, final_settlement_price):
        self.account.update_tick_price(final_settlement_price)
        return self.account.ledger_engine.record_settlement(
            "EOD", self.account.realized_pnl, self.account.unrealized_pnl, self.account.balance,
        )


class AuthoritativeReconciliationEngine:
    def __init__(self, initial_capital=25000000.0, **kwargs):
        self.initial_capital = initial_capital

    def reconcile_state(self, account_snapshot, execution_history, current_positions):
        return {"ok": True, "execution_count": len(execution_history), "position_count": len(current_positions), "discrepancies": []}


from copy import deepcopy


class StateRecoveryEngine:
    def __init__(self, account):
        self.account = account

    def create_snapshot(self, sequence_id, metrics=None):
        return {"sequence_id": sequence_id, "balance": self.account.balance, "positions": deepcopy(self.account.positions), "metrics": dict(metrics or {})}

    def restore_from_snapshot(self, snapshot, target_metrics=None):
        self.account.balance = snapshot["balance"]
        self.account.positions.clear()
        self.account.positions.update(deepcopy(snapshot["positions"]))
        if target_metrics is not None:
            target_metrics.update(snapshot.get("metrics", {}))
        return True


from environments.virtual.authoritative_vssf.canonical import CanonicalMarketTick
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount as _AuthoritativePaperAccount
from environments.virtual.authoritative_vssf.execution_engine import ExecutionEngine as _AuthoritativeExecutionEngine
from environments.virtual.authoritative_vssf.order_book import OrderBook as _AuthoritativeOrderBook
from environments.virtual.authoritative_vssf.reconciliation import AuthoritativeReconciliationEngine as _AuthoritativeReconciliation
from environments.virtual.authoritative_vssf.settlement_engine import SettlementEngine as _AuthoritativeSettlement
from environments.virtual.authoritative_vssf.state_recovery import StateRecoveryEngine as _AuthoritativeRecovery


class VirtualSecuritiesFirmRuntime:
    def __init__(self, initial_capital=25000000.0):
        self.account = PaperTradingAccount(initial_capital)
        self.execution_engine = ExecutionEngine()
        self.order_book = OrderBook()
        self.reconciliation_engine = AuthoritativeReconciliationEngine(initial_capital)
        self.settlement_engine = SettlementEngine(self.account)
        self.recovery_engine = StateRecoveryEngine(self.account)
        self.margin_engine = self.account.margin_engine
        self.metrics = {"market_ticks": 0, "order_commands": 0, "executions_issued": 0, "settlement_runs": 0}

    @property
    def orderbook(self):
        return self.order_book

    def process_market_data(self, tick):
        self.metrics["market_ticks"] += 1
        self.order_book.update_bid_ask(tick.bid_price, tick.ask_price)
        self.account.update_tick_price(tick.underlying_price)

    def process_order(self, command):
        self.metrics["order_commands"] += 1
        if self.account.free_margin < self.margin_engine.calculate_order_margin(command):
            return None
        price = self.order_book.match_order(command)
        if price <= 0:
            return None
        rep = self.execution_engine.execute_order(command, price, command.qty)
        self.account.apply_execution(rep)
        self.account.update_tick_price(price)
        self.metrics["executions_issued"] += 1
        return rep

    def run_settlement(self, final_settlement_price=None):
        self.metrics["settlement_runs"] += 1
        return self.settlement_engine.perform_eod_settlement(final_settlement_price or 350.0)

    def get_account_snapshot(self):
        return self.account.get_canonical_summary()

    def run_reconciliation(self):
        return self.reconciliation_engine.reconcile_state(
            self.get_account_snapshot(), self.execution_engine.reports, self.account.positions,
        )
