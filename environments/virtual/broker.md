[Child Page] virtual_broker.py
```python
from contracts.broker import BrokerAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class VirtualBroker(BrokerAdapter):
    """VSSF-derived broker boundary; no KIS/Paper/Live dependency."""

    def __init__(self, execution_engine: VirtualExecutionEngine):
        self.execution_engine = execution_engine

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self.execution_engine.execute(command)

    def cancel(self, order_id: str) -> ExecutionReport:
        return self.execution_engine.cancel(order_id)

    def query(self, order_id: str) -> ExecutionReport | None:
        return self.execution_engine.query(order_id)
```
## Contract 정합화
    - BrokerAdapter 표준 Protocol을 구현한다.
    - 입력은 canonical BrokerOrderCommand로 제한한다.
    - 실행 결과는 canonical ExecutionReport로 반환한다.
    - Virtual Broker가 KIS/Paper/Live API를 직접 참조하지 않는다.
    - 실제 VSSF 주문·margin·ledger 정책은 이 adapter 경계 아래의 Virtual Execution/VSSF migration 대상으로 보존한다.