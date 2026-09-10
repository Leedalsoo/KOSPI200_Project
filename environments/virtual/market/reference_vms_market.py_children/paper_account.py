from datetime import datetime
from decimal import Decimal
from environments.virtual.authoritative_vssf.position_manager import PositionManager
from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine
from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine
from shared.contracts.canonical import CanonicalAccountSummary

class PaperTradingAccount:
 def __init__(self,initial_capital=25000000.0):
  capital=Decimal(str(initial_capital)); self.balance=capital; self.realized_pnl=Decimal("0"); self.unrealized_pnl=Decimal("0"); self.position_mgr=PositionManager(); self.pnl_engine=PnLEngine(); self.margin_engine=MarginEngine(initial_capital); self.ledger_engine=LedgerEngine(); self.free_margin=capital; self.used_margin=Decimal("0")
 @property
 def positions(self): return self.position_mgr.positions
 def get_canonical_summary(self):
  total=self.balance+self.realized_pnl+self.unrealized_pnl
  return CanonicalAccountSummary("ACC-VSSF-001",total,self.realized_pnl,self.unrealized_pnl,self.used_margin,self.free_margin,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),positions={k:dict(v) for k,v in self.positions.items()})
 def update_tick_price(self,price):
  self.unrealized_pnl=self.pnl_engine.calculate_unrealized(self.positions,price)
  self.used_margin=self.margin_engine.calculate_used_margin(self.positions)
  equity=self.balance+self.realized_pnl+self.unrealized_pnl
  self.free_margin=self.margin_engine.calculate_free_margin(equity,self.used_margin)
 def apply_execution(self,rep):
  pnl=self.position_mgr.update_position(rep.symbol,rep.side.value if hasattr(rep.side,'value') else str(rep.side),rep.executed_qty,rep.executed_price); self.pnl_engine.add_realized(pnl); self.realized_pnl=self.pnl_engine.realized_pnl; self.balance-=Decimal(str(rep.fee)); self.ledger_engine.transactions.append({"exec_id":rep.exec_id})
