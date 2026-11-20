from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PartialFillObservation:
    client_order_id: str
    leg_id: str
    schedule: tuple[int, ...]
    intermediate_status: str
    intermediate_remaining_quantity: int
    final_status: str
    final_filled_quantity: int
    final_remaining_quantity: int


class ValidationOnlyS8PartialFillEngine:
    """Deterministic, instance-local VSSF partial-fill injector for S8 synthetic tests."""

    def __init__(self, profile: dict[str, Any]) -> None:
        if (
            profile.get("validation_only") is not True
            or profile.get("runtime_eligible") is not False
            or profile.get("production_runtime_eligible") is not False
            or profile.get("allow_kis_api") is not False
            or profile.get("allow_real_vts") is not False
            or profile.get("allow_live_orders") is not False
            or profile.get("allow_real_account") is not False
            or profile.get("allow_external_orders") is not False
            or profile.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO"
        ):
            raise ValueError("S8_PARTIAL_FILL_ENGINE_VALIDATION_ONLY_PROFILE_REQUIRED")
        if Decimal(str(profile.get("fee_per_fill_krw", "-1"))) != 0:
            raise ValueError("S8_PARTIAL_FILL_ENGINE_FEE_UNSUPPORTED")
        self.quantity = int(profile["entry_quantity_per_leg"])
        self.schedule = tuple(int(value) for value in profile["execution_fill_schedule"])
        self.price_offsets = tuple(Decimal(str(value)) for value in profile["fill_price_offsets"])
        if self.quantity <= 1 or not self.schedule or sum(self.schedule) != self.quantity:
            raise ValueError("S8_PARTIAL_FILL_ENGINE_SCHEDULE_INVALID")
        if len(self.price_offsets) != len(self.schedule) or any(value < 0 for value in self.price_offsets):
            raise ValueError("S8_PARTIAL_FILL_ENGINE_PRICE_SCHEDULE_INVALID")
        self.observations: list[PartialFillObservation] = []
        self._seen_order_ids: set[str] = set()

    def install(self, vssf_runtime: Any) -> Callable[[], None]:
        original = getattr(vssf_runtime, "_execute", None)
        if not callable(original):
            raise ValueError("S8_PARTIAL_FILL_ENGINE_VSSF_RUNTIME_REQUIRED")

        def execute(command: Any, price: Any, now: Any, *, quantity: int | None = None):
            client_order_id = str(getattr(command, "client_order_id", ""))
            leg_id = str(getattr(command, "leg_id", "")).lower()
            side_value = getattr(command, "side", "")
            side = str(getattr(side_value, "value", side_value)).upper()
            strategy_id = str(getattr(command, "strategy_id", ""))
            order_quantity = int(getattr(command, "qty", 0))
            if (
                strategy_id != "track8_macro_regime_monthly_strangle"
                or side != "BUY"
                or leg_id not in {"call", "put"}
                or order_quantity != self.quantity
                or client_order_id in self._seen_order_ids
            ):
                return original(command, price, now, quantity=quantity)

            self._seen_order_ids.add(client_order_id)
            intermediate = None
            final = None
            for index, fill_quantity in enumerate(self.schedule):
                fill_price = Decimal(str(price)) + self.price_offsets[index]
                final = original(
                    command,
                    float(fill_price),
                    now,
                    quantity=fill_quantity,
                )
                lifecycle = getattr(vssf_runtime, "_lifecycle_results", {}).get(client_order_id)
                if index == 0:
                    intermediate = lifecycle
            if intermediate is None or final is None:
                raise RuntimeError("S8_PARTIAL_FILL_ENGINE_NO_EXECUTION")
            lifecycle = getattr(vssf_runtime, "_lifecycle_results", {}).get(client_order_id)
            if lifecycle is None:
                raise RuntimeError("S8_PARTIAL_FILL_ENGINE_FINAL_LIFECYCLE_MISSING")
            self.observations.append(
                PartialFillObservation(
                    client_order_id=client_order_id,
                    leg_id=leg_id,
                    schedule=self.schedule,
                    intermediate_status=str(intermediate.status),
                    intermediate_remaining_quantity=int(intermediate.remaining_qty),
                    final_status=str(lifecycle.status),
                    final_filled_quantity=int(lifecycle.executed_qty),
                    final_remaining_quantity=int(lifecycle.remaining_qty),
                )
            )
            return final

        vssf_runtime._execute = execute

        def restore() -> None:
            vssf_runtime._execute = original

        return restore
