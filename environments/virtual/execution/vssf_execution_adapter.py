from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from contracts.types import BrokerOrderCommand, DataQuality, ExecutionReport


class VSSFCommandContextProvider(Protocol):
    """Standard 주문으로부터 실제 VSSF 주문 생성에 필요한 권위 데이터를 공급한다."""

    def build_command(self, order: BrokerOrderCommand) -> object: ...


class VSSFRuntime(Protocol):
    """실제 VSSF 전체 주문→Risk→OrderBook→Execution 경로."""

    def process_order(self, command: object) -> object: ...


@dataclass(frozen=True)
class VSSFExecutionAdapter:
    """Standard BrokerOrderCommand를 실제 VSSF Runtime 경계로 연결한다."""

    command_context: VSSFCommandContextProvider
    vssf_runtime: VSSFRuntime

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        vssf_command = self.command_context.build_command(order)
        report = self.vssf_runtime.process_order(vssf_command)
        if report is None:
            raise RuntimeError("VSSF_ORDER_NOT_EXECUTED")
        return ExecutionReport(
            client_order_id=report.client_order_id,
            broker_order_id=None,
            execution_id=report.exec_id,
            status="FILLED",
            filled_quantity=int(report.executed_qty),
            remaining_quantity=0,
            execution_price=report.executed_price,
            execution_timestamp=datetime.fromisoformat(report.timestamp),
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="vssf_authoritative_execution",
            ),
        )
