from dataclasses import dataclass

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from environments.live.contracts import LiveSafetyPolicy
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
from environments.live.idempotency import IdempotencyRegistry, OrderIdentity
from environments.live.broker.kis_order_payload import KisDomesticFuturesOrderPayloadAdapter
from environments.live.broker.kis_order_transport import KISDomesticFuturesOrderTransport


@dataclass
class LiveBrokerAdapter:
    transport: object
    gate: object
    policy: LiveSafetyPolicy
    idempotency: IdempotencyRegistry
    futures_command_adapter: KisFuturesBrokerCommandAdapter | None = None
    connected: bool = False

    def connect(self) -> bool:
        self.connected = bool(self.transport.authenticate())
        return self.connected

    def submit(self, command: BrokerOrderCommand, identity: OrderIdentity, account_age_seconds: float) -> BrokerOrderResponse:
        if not self.connected:
            raise RuntimeError("live broker is disconnected")
        if not self.idempotency.reserve(identity):
            raise RuntimeError("duplicate client order identity")

        gate = self.gate.evaluate(command.quantity, account_age_seconds)
        if not gate.allowed:
            raise RuntimeError(gate.reason)

        broker_command = command
        if command.asset_type == "FUTURES":
            if self.futures_command_adapter is None:
                raise RuntimeError("FUTURES_COMMAND_ADAPTER_REQUIRED")
            broker_command = self.futures_command_adapter.to_broker_command(command)

        return self.transport.submit(broker_command)
