class SettlementEngine:
 def __init__(self,account): self.account=account
 def perform_eod_settlement(self,final_settlement_price):
  self.account.update_tick_price(final_settlement_price); return self.account.ledger_engine.record_settlement("EOD",self.account.realized_pnl,self.account.unrealized_pnl,self.account.balance)
