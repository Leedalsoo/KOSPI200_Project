from dataclasses import dataclass
from typing import Protocol

from contracts.types import BrokerOrderCommand


class VSSFCommandContextProvider(Protocol):
    pass
    """Standard 주문으로부터 실제 VSSF 주문 생성에 필요한 권위 데이터를 공급한다."""

    def build_command(self, order: BrokerOrderCommand) -> object: ...


class VSSFRuntime(Protocol):
    pass
    """실제 VSSF 전체 주문→Risk→OrderBook→Execution 경로."""

    def process_order(self, command: object) -> object: ...


@dataclass(frozen=True)
class VSSFExecutionAdapter:
    pass
    """Standard BrokerOrderCommand를 실제 VSSF Runtime 경계로 연결한다."""

    command_context: VSSFCommandContextProvider
    vssf_runtime: VSSFRuntime

    def execute(self, order: BrokerOrderCommand) -> object:
        pass
        vssf_command = self.command_context.build_command(order)
        return self.vssf_runtime.process_order(vssf_command)



# 현재 Standard BrokerOrderCommand는 client_order_id, instrument_id, side, quantity, order_type, broker_symbol, session_id만 가진다.

# 따라서 price, track_id, asset_type, option_type, strike, expiry를 adapter에서 임의 생성하지 않는다.

# 특히 다음은 금지한다.











# 원격 Exp_Detail_1에서 실제 CanonicalOrderCommand 생성부를 확인했다.

# option_program/runtime/program_runtime.py의 OptionProgramRuntime.process_tick()에서 DecisionArbiter가 승인한 CanonicalStrategySignal을 기반으로 CanonicalOrderCommand를 직접 생성한다.

# VMS CanonicalMarketTick
