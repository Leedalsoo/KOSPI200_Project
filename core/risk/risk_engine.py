"""Standard Core pre-trade RiskEngine and RiskGate."""
import dataclasses
import copy
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol

from contracts.risk import RiskApprovalToken, RiskEvaluationResult
from core.risk.risk_config import RiskConfig
from core.risk.risk_input import RiskAccountInput, RiskPositionInput
from core.risk.risk_sensor import RiskSensor, RiskSensorSnapshot

logger = logging.getLogger(__name__)

class RiskOrderCommand(Protocol):
    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: Any
    tag_id: str
    def get_instrument_key(self) -> str: ...

class MarginCalculator(Protocol):
    def calculate_order_margin(self, command: RiskOrderCommand) -> float: ...

def _replace_command_qty(command: RiskOrderCommand, qty: int) -> RiskOrderCommand:
    if dataclasses.is_dataclass(command):
        return dataclasses.replace(command, qty=qty)
    cloned = copy.copy(command)
    try:
        setattr(cloned, "qty", qty)
    except Exception as exc:
        raise TypeError("RISK_REDUCED_COMMAND_NOT_MUTABLE") from exc
    return cloned


class RiskEngine:
    def __init__(self, config: Optional[RiskConfig] = None, margin_engine: Optional[MarginCalculator] = None, risk_sensor: Optional[RiskSensor] = None):
        self.config = config or RiskConfig()
        if margin_engine is None:
            raise ValueError("RISK_MARGIN_DEPENDENCY_REQUIRED")
        self.margin_engine = margin_engine
        self.sensor = risk_sensor or RiskSensor(self.config)
        self._is_kill_switch_active = False
        self._daily_realized_loss = Decimal("0")

    def trigger_kill_switch(self, reason: str = "MANUAL_PANIC_STOP") -> None:
        self._is_kill_switch_active = True
        logger.critical("[RiskEngine] KILL SWITCH ACTIVATED: %s", reason)

    def reset_kill_switch(self) -> None:
        was_active = self._is_kill_switch_active
        self._is_kill_switch_active = False
        if was_active:
            logger.warning("[RiskEngine] KILL SWITCH RESET")

    def is_kill_switch_active(self) -> bool:
        return self._is_kill_switch_active

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def record_realized_loss(self, loss_amount: float | Decimal) -> None:
        amount = self._decimal(loss_amount)
        if amount < 0:
            self._daily_realized_loss += abs(amount)

    @staticmethod
    def _order_side(command: RiskOrderCommand) -> str:
        return command.side.value if hasattr(command.side, "value") else str(command.side)

    def calculate_expected_position(self, command: RiskOrderCommand, positions: Optional[RiskPositionInput] = None) -> dict[str, Any]:
        positions_map: Mapping[str, Any] = positions.positions if positions is not None else {}
        instrument_key = command.get_instrument_key()
        current = positions_map.get(instrument_key)
        if current is None and len(positions_map) == 1:
            current = next(iter(positions_map.values()))
        curr_qty = int(getattr(current, "qty", 0)) if current is not None else 0
        curr_side = getattr(current, "side", None) if current is not None else None
        order_side = self._order_side(command)
        if curr_qty == 0 or not curr_side:
            return {"instrument_key": instrument_key, "side": order_side, "qty": command.qty}
        if curr_side == order_side:
            return {"instrument_key": instrument_key, "side": curr_side, "qty": curr_qty + command.qty}
        if command.qty < curr_qty:
            return {"instrument_key": instrument_key, "side": curr_side, "qty": curr_qty - command.qty}
        if command.qty == curr_qty:
            return {"instrument_key": instrument_key, "side": "FLAT", "qty": 0}
        return {"instrument_key": instrument_key, "side": order_side, "qty": command.qty - curr_qty}

    def evaluate_order(self, command: RiskOrderCommand, account: RiskAccountInput, positions: Optional[RiskPositionInput] = None, sensor_snapshot: Optional[RiskSensorSnapshot] = None, allow_reduction: bool = False) -> RiskEvaluationResult:
        original_qty = command.qty
        if self._is_kill_switch_active:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, "REJECTED_BY_KILL_SWITCH")
        if command.qty <= 0:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"INVALID_ORDER_QTY: {command.qty}")
        if command.qty > self.config.max_order_qty:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_ORDER_QTY: {command.qty} > {self.config.max_order_qty}")
        realized_pnl = self._decimal(account.realized_pnl)
        total_loss = self._daily_realized_loss + abs(min(Decimal("0"), realized_pnl))
        max_daily_loss = self.config.max_daily_loss_krw
        if total_loss >= max_daily_loss:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_DAILY_LOSS: {total_loss:,.0f} >= {self.config.max_daily_loss_krw:,.0f} KRW")
        effective_cmd = command
        expected = self.calculate_expected_position(effective_cmd, positions)
        if expected["qty"] > self.config.max_position_per_instrument:
            current = positions.positions.get(expected["instrument_key"]) if positions is not None else None
            current_qty = int(getattr(current, "qty", 0)) if current is not None else 0
            if current is None and positions is not None and len(positions.positions) == 1:
                current = next(iter(positions.positions.values())); current_qty = int(getattr(current, "qty", 0))
            remaining_capacity = self.config.max_position_per_instrument - current_qty
            if allow_reduction and 0 < remaining_capacity < effective_cmd.qty:
                effective_cmd = _replace_command_qty(effective_cmd, remaining_capacity)
            else:
                return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_INSTRUMENT_LIMIT: {expected['qty']} > {self.config.max_position_per_instrument}")
        required_margin = self._decimal(self.margin_engine.calculate_order_margin(effective_cmd))
        used_margin = self._decimal(account.used_margin)
        total_balance = self._decimal(account.total_balance)
        free_margin = self._decimal(account.free_margin)
        estimated_ratio = (used_margin + required_margin) / total_balance if total_balance > 0 else Decimal("1")
        if required_margin > free_margin:
            unit_margin = required_margin / effective_cmd.qty if effective_cmd.qty > 0 else Decimal("0")
            max_affordable_qty = int(free_margin / unit_margin) if unit_margin > 0 else 0
            if allow_reduction and 0 < max_affordable_qty < effective_cmd.qty:
                effective_cmd = _replace_command_qty(effective_cmd, max_affordable_qty)
                required_margin = self._decimal(self.margin_engine.calculate_order_margin(effective_cmd))
                estimated_ratio = (used_margin + required_margin) / total_balance if total_balance > 0 else Decimal("1")
            else:
                return RiskEvaluationResult(False, "DENY", original_qty, 0, f"INSUFFICIENT_FREE_MARGIN: req={required_margin:,.0f} > free={float(account.free_margin):,.0f} KRW", required_margin, estimated_ratio)
        if estimated_ratio > self.config.max_margin_utilization_ratio:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_MARGIN_RATIO: {estimated_ratio:.2%} > {self.config.max_margin_utilization_ratio:.2%}", required_margin, estimated_ratio)
        if sensor_snapshot and sensor_snapshot.is_margin_diet_required and effective_cmd.tag_id != "RISK_HEDGE":
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"MARGIN_DIET_ACTIVE: Blocked new entry under {sensor_snapshot.reason}", required_margin, estimated_ratio)
        is_reduced = effective_cmd.qty < original_qty
        decision = "REDUCE" if is_reduced else "ALLOW"
        token = RiskApprovalToken(uuid.uuid4(), time.time_ns(), f"SIG-RISK-APPROVED-{effective_cmd.track_id}-{effective_cmd.client_order_id}")
        return RiskEvaluationResult(True, decision, original_qty, effective_cmd.qty, None, required_margin, estimated_ratio, token, effective_cmd if is_reduced else None)

class RiskGate:
    def __init__(self, risk_engine: RiskEngine):
        self.engine = risk_engine
        self.last_evaluation_result: Optional[RiskEvaluationResult] = None
    def admit_order(self, command: RiskOrderCommand, account: RiskAccountInput, positions: Optional[RiskPositionInput] = None, sensor_snapshot: Optional[RiskSensorSnapshot] = None, allow_reduction: bool = False) -> tuple[bool, Optional[RiskApprovalToken], Optional[str]]:
        result = self.engine.evaluate_order(command, account, positions, sensor_snapshot, allow_reduction=allow_reduction)
        self.last_evaluation_result = result
        if result.is_approved and result.token is not None:
            return True, result.token, None
        return False, None, result.rejection_reason
