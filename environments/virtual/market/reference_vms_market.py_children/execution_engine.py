from datetime import datetime
from environments.virtual.authoritative_vssf.canonical import CanonicalExecutionReport
class ExecutionEngine:
 def __init__(self): self.reports=[]; self._seq=0
 def execute_order(self,command,price,qty):
  self._seq+=1; rep=CanonicalExecutionReport(f"EXEC-{self._seq:06d}",command.client_order_id,command.track_id,command.asset_type,command.side,int(qty),float(price),0.0,0.0,datetime.now().isoformat(),symbol=getattr(command,'symbol','KOSPI200')); self.reports.append(rep); return rep
