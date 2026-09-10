from copy import deepcopy
class StateRecoveryEngine:
 def __init__(self,account): self.account=account
 def create_snapshot(self,sequence_id,metrics=None): return {"sequence_id":sequence_id,"balance":self.account.balance,"positions":deepcopy(self.account.positions),"metrics":dict(metrics or {})}
 def restore_from_snapshot(self,snapshot,target_metrics=None):
  self.account.balance=snapshot["balance"]; self.account.positions.clear(); self.account.positions.update(deepcopy(snapshot["positions"]));
  if target_metrics is not None: target_metrics.update(snapshot.get("metrics",{})); return True
  return True
