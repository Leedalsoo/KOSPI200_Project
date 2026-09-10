from environments.virtual.authoritative_vssf.canonical import CanonicalMarketTick
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from environments.virtual.authoritative_vssf.execution_engine import ExecutionEngine
from environments.virtual.authoritative_vssf.order_book import OrderBook
from environments.virtual.authoritative_vssf.reconciliation import AuthoritativeReconciliationEngine
from environments.virtual.authoritative_vssf.settlement_engine import SettlementEngine
from environments.virtual.authoritative_vssf.state_recovery import StateRecoveryEngine
class VirtualSecuritiesFirmRuntime:
 def __init__(self,initial_capital=25000000.0):
  self.account=PaperTradingAccount(initial_capital); self.execution_engine=ExecutionEngine(); self.order_book=OrderBook(); self.reconciliation_engine=AuthoritativeReconciliationEngine(initial_capital); self.settlement_engine=SettlementEngine(self.account); self.recovery_engine=StateRecoveryEngine(self.account); self.margin_engine=self.account.margin_engine; self.metrics={"market_ticks":0,"order_commands":0,"executions_issued":0,"settlement_runs":0}
 @property
 def orderbook(self): return self.order_book
 def process_market_data(self,tick): self.metrics["market_ticks"]+=1; self.order_book.update_bid_ask(tick.bid_price,tick.ask_price); self.account.update_tick_price(tick.underlying_price)
 def process_order(self,command):
  self.metrics["order_commands"]+=1
  if self.account.free_margin < self.margin_engine.calculate_order_margin(command): return None
  price=self.order_book.match_order(command)
  if price<=0: return None
  rep=self.execution_engine.execute_order(command,price,command.qty); self.account.apply_execution(rep); self.account.update_tick_price(price); self.metrics["executions_issued"]+=1; return rep
 def run_settlement(self,final_settlement_price=None): self.metrics["settlement_runs"]+=1; return self.settlement_engine.perform_eod_settlement(final_settlement_price or 350.0)
 def get_account_snapshot(self): return self.account.get_canonical_summary()
 def run_reconciliation(self): return self.reconciliation_engine.reconcile_state(self.get_account_snapshot(),self.execution_engine.reports,self.account.positions)
