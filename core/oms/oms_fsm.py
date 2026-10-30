from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OptionInstrumentIdentity


class OrderStateTransitionError(ValueError):
    """Raised when an order state transition is unsafe or invalid."""


@dataclass(frozen=True)
class OrderState:
    client_order_id: str
    status: str
    broker_order_id: str | None = None
    order_quantity: int = 0
    filled_quantity: int = 0
    broker_order_command: BrokerOrderCommand | None = None
    average_execution_price: Decimal | None = None


@dataclass(frozen=True)
class ExecutionCorrelation:
    """OMS-owned state required to correlate a broker execution notice."""

    client_order_id: str
    broker_order_id: str
    order_quantity: int
    prior_filled_quantity: int
    prior_average_price: Decimal | None = None


class OrderStateMachine:
    """OMS-owned order state and broker/client correlation boundary."""

    def __init__(self, persistence_store=None) -> None:
        self._states: dict[str, OrderState] = {}
        self._broker_to_client: dict[str, str] = {}
        self._persistence_store = persistence_store

    def set_persistence_store(self, store) -> None:
        if store is None:
            raise ValueError("SETTLEMENT_STORE_REQUIRED")
        self._persistence_store = store

    @staticmethod
    def _command_record(command: BrokerOrderCommand | None) -> dict | None:
        if command is None:
            return None
        identity = command.instrument_identity
        identity_record = None
        if isinstance(identity, OptionInstrumentIdentity):
            identity_record = {"kind": "option", "fields": {
                "instrument_id": identity.instrument_id, "symbol": identity.symbol,
                "expiry": identity.expiry, "option_type": identity.option_type,
                "strike": str(identity.strike) if identity.strike is not None else None,
                "contract_multiplier": str(identity.contract_multiplier) if identity.contract_multiplier is not None else None,
                "identity_source": identity.identity_source,
            }}
        elif isinstance(identity, FuturesInstrumentIdentity):
            identity_record = {"kind": "futures", "fields": {
                "instrument_id": identity.instrument_id, "symbol": identity.symbol,
                "product_type": identity.product_type.value,
                "contract_multiplier": str(identity.contract_multiplier),
                "identity_source": identity.identity_source,
            }}
        elif identity is not None:
            raise OrderStateTransitionError("UNSUPPORTED_INSTRUMENT_IDENTITY_FOR_PERSISTENCE")
        record = asdict(command)
        record["requested_price"] = str(command.requested_price) if command.requested_price is not None else None
        record["instrument_identity"] = identity_record
        return record

    @staticmethod
    def _command_from_record(record: dict | None) -> BrokerOrderCommand | None:
        if record is None:
            return None
        values = dict(record)
        values["requested_price"] = Decimal(values["requested_price"]) if values.get("requested_price") is not None else None
        identity = values.get("instrument_identity")
        if identity:
            fields = dict(identity["fields"])
            if identity["kind"] == "option":
                fields["strike"] = Decimal(fields["strike"]) if fields.get("strike") is not None else None
                fields["contract_multiplier"] = Decimal(fields["contract_multiplier"]) if fields.get("contract_multiplier") is not None else None
                values["instrument_identity"] = OptionInstrumentIdentity(**fields)
            elif identity["kind"] == "futures":
                fields["product_type"] = FuturesProductType(fields["product_type"])
                fields["contract_multiplier"] = Decimal(fields["contract_multiplier"])
                values["instrument_identity"] = FuturesInstrumentIdentity(**fields)
            else:
                raise OrderStateTransitionError("PERSISTED_INSTRUMENT_IDENTITY_KIND_INVALID")
        else:
            values["instrument_identity"] = None
        return BrokerOrderCommand(**values)

    @classmethod
    def state_to_record(cls, state: OrderState) -> dict:
        return {
            "client_order_id": state.client_order_id,
            "status": state.status,
            "broker_order_id": state.broker_order_id,
            "order_quantity": state.order_quantity,
            "filled_quantity": state.filled_quantity,
            "average_execution_price": str(state.average_execution_price) if state.average_execution_price is not None else None,
            "broker_order_command": cls._command_record(state.broker_order_command),
        }

    @classmethod
    def state_from_record(cls, record: dict) -> OrderState:
        return OrderState(
            client_order_id=str(record["client_order_id"]),
            status=str(record["status"]),
            broker_order_id=record.get("broker_order_id"),
            order_quantity=int(record["order_quantity"]),
            filled_quantity=int(record["filled_quantity"]),
            broker_order_command=cls._command_from_record(record.get("broker_order_command")),
            average_execution_price=Decimal(record["average_execution_price"]) if record.get("average_execution_price") is not None else None,
        )

    def restore_from_store(self) -> None:
        if self._persistence_store is None:
            raise OrderStateTransitionError("SETTLEMENT_STORE_REQUIRED")
        states = [self.state_from_record(row) for row in self._persistence_store.load_order_state_payloads()]
        broker_to_client: dict[str, str] = {}
        for state in states:
            if state.broker_order_id:
                previous = broker_to_client.get(state.broker_order_id)
                if previous is not None and previous != state.client_order_id:
                    raise OrderStateTransitionError("PERSISTED_BROKER_ORDER_CORRELATION_CONFLICT")
                broker_to_client[state.broker_order_id] = state.client_order_id
        self._states = {state.client_order_id: state for state in states}
        self._broker_to_client = broker_to_client

    def replace_state(self, state: OrderState, *, persist: bool = False) -> OrderState:
        if persist and self._persistence_store is not None:
            self._persistence_store.save_order_state(state.client_order_id, self.state_to_record(state))
        if state.broker_order_id:
            previous = self._broker_to_client.get(state.broker_order_id)
            if previous is not None and previous != state.client_order_id:
                raise OrderStateTransitionError("BROKER_ORDER_ID_ALREADY_CORRELATED")
            self._broker_to_client[state.broker_order_id] = state.client_order_id
        self._states[state.client_order_id] = state
        return state

    def persist_all_states(self) -> None:
        if self._persistence_store is None:
            raise OrderStateTransitionError("SETTLEMENT_STORE_REQUIRED")
        for state in self._states.values():
            self._persist_state(state)

    def _persist_state(self, state: OrderState) -> None:
        if self._persistence_store is not None:
            self._persistence_store.save_order_state(state.client_order_id, self.state_to_record(state))

    def apply_intent(self, intent) -> OrderState:
        client_order_id = str(intent.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        quantity = int(intent.quantity)
        if quantity <= 0:
            raise OrderStateTransitionError("ORDER_QUANTITY_INVALID")
        if client_order_id in self._states:
            raise OrderStateTransitionError("ORDER_INTENT_ALREADY_REGISTERED")
        state = OrderState(client_order_id, "SUBMITTED", order_quantity=quantity)
        self._persist_state(state)
        self._states[client_order_id] = state
        return state

    def register_broker_order_command(self, command: BrokerOrderCommand) -> OrderState:
        client_order_id = str(command.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("BROKER_COMMAND_AFTER_INVALID_STATE")
        if command.quantity != current.order_quantity:
            raise OrderStateTransitionError("BROKER_COMMAND_QUANTITY_MISMATCH")
        if command.instrument_identity is not None and command.instrument_id != command.instrument_identity.instrument_id:
            raise OrderStateTransitionError("BROKER_COMMAND_INSTRUMENT_ID_MISMATCH")
        state = OrderState(
            client_order_id=current.client_order_id,
            status=current.status,
            broker_order_id=current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=command,
            average_execution_price=current.average_execution_price,
        )
        self._persist_state(state)
        self._states[client_order_id] = state
        return state

    def apply_ack(self, event: OrderAckEvent) -> OrderState:
        client_order_id = str(event.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("ACK_AFTER_TERMINAL_STATE")
        if event.accepted and not event.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK")
        if event.accepted:
            broker_order_id = str(event.broker_order_id).strip()
            previous_client = self._broker_to_client.get(broker_order_id)
            if previous_client is not None and previous_client != client_order_id:
                raise OrderStateTransitionError("BROKER_ORDER_ID_ALREADY_CORRELATED")
            self._broker_to_client[broker_order_id] = client_order_id
        state = OrderState(
            client_order_id=client_order_id,
            status="ACKED" if event.accepted else "REJECTED",
            broker_order_id=event.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=current.broker_order_command,
            average_execution_price=current.average_execution_price,
        )
        self._persist_state(state)
        self._states[client_order_id] = state
        return state

    def resolve_execution_correlation(self, broker_order_id: str) -> ExecutionCorrelation:
        broker_id = str(broker_order_id).strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None:
            raise OrderStateTransitionError("CORRELATED_ORDER_STATE_MISSING")
        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_CORRELATION_STATE_INVALID")
        return ExecutionCorrelation(
            client_order_id=state.client_order_id,
            broker_order_id=broker_id,
            order_quantity=state.order_quantity,
            prior_filled_quantity=state.filled_quantity,
            prior_average_price=state.average_execution_price,
        )

    def get_broker_order_command(self, broker_order_id: str | None) -> BrokerOrderCommand:
        broker_id = str(broker_order_id or "").strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None or state.broker_order_command is None:
            raise OrderStateTransitionError("BROKER_ORDER_COMMAND_NOT_REGISTERED")
        if state.broker_order_id != broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        return state.broker_order_command

    def preview_execution(self, report: ExecutionReport) -> OrderState:
        """Calculate an execution transition on an isolated OMS projection."""
        projected = object.__new__(OrderStateMachine)
        projected._states = self._states.copy()
        projected._broker_to_client = self._broker_to_client.copy()
        projected._persistence_store = None
        return projected.apply_execution(report)

    def apply_execution(self, report: ExecutionReport) -> OrderState:
        if self._persistence_store is not None:
            raise OrderStateTransitionError("EXECUTION_SETTLEMENT_BRIDGE_REQUIRED")
        client_order_id = str(report.client_order_id).strip()
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = current.filled_quantity + report.filled_quantity
        if cumulative > current.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != current.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and current.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        average_execution_price = current.average_execution_price
        if report.execution_price is not None and report.execution_price > 0:
            if current.filled_quantity == 0 or average_execution_price is None:
                average_execution_price = report.execution_price
            else:
                average_execution_price = (average_execution_price * Decimal(current.filled_quantity) + report.execution_price * Decimal(report.filled_quantity)) / Decimal(cumulative)
        state = OrderState(
            client_order_id=client_order_id,
            status=report.status,
            broker_order_id=report.broker_order_id or current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=cumulative,
            broker_order_command=current.broker_order_command,
            average_execution_price=average_execution_price,
        )
        self._persist_state(state)
        self._states[client_order_id] = state
        return state

    def command_for(self, client_order_id: str) -> BrokerOrderCommand:
        state = self._states.get(str(client_order_id).strip())
        if state is None or state.broker_order_command is None:
            raise OrderStateTransitionError("BROKER_ORDER_COMMAND_NOT_REGISTERED")
        return state.broker_order_command

    def pending_client_order_ids(self, strategy_id: str) -> tuple[str, ...]:
        target = str(strategy_id).strip()
        if not target:
            raise OrderStateTransitionError("STRATEGY_ID_REQUIRED")
        pending = []
        for state in self._states.values():
            command = state.broker_order_command
            if command is None or str(command.strategy_id or "").strip() != target:
                continue
            if state.status in {"SUBMITTED", "ACKED", "PARTIALLY_FILLED"}:
                pending.append(state.client_order_id)
        return tuple(sorted(pending))

    def apply_cancel(self, report: ExecutionReport) -> OrderState:
        client_order_id = str(report.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("CANCEL_AFTER_INVALID_STATE")
        if report.status != "CANCELLED":
            raise OrderStateTransitionError("CANCEL_REPORT_REQUIRED")
        state = OrderState(
            client_order_id=current.client_order_id,
            status="CANCELLED",
            broker_order_id=report.broker_order_id or current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=current.broker_order_command,
            average_execution_price=current.average_execution_price,
        )
        self._persist_state(state)
        self._states[client_order_id] = state
        return state

    def get(self, client_order_id: str) -> OrderState | None:
        return self._states.get(client_order_id)


__all__ = (
    "ExecutionCorrelation",
    "OrderState",
    "OrderStateMachine",
    "OrderStateTransitionError",
)
