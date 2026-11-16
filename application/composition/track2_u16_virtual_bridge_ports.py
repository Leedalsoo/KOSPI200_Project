from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from contracts.types import MultiLegExecutionPlan
from core.strategy.track2_u16_repair_lifecycle import U16Fill, U16QuotePolicy, U16RepairInput


@dataclass(frozen=True)
class U16BridgeSubmissionEvidence:
    client_order_id: str
    terminal: bool
    reconciled: bool
    status: str
    filled_quantity: int
    remaining_quantity: int
    client_order_ids: tuple[str, ...] = ()


class ValidationOnlyU16VirtualBridgePorts:
    """U16 submission ports backed by the existing validation-only Multi-Leg bridge.

    A caller must supply the authoritative entry plan. This adapter never invents
    instrument identity, side, role, requested price, quote policy, or quantity.
    """

    TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}

    def __init__(self, *, validation_only: bool, bridge: Any,
                 entry_plan_provider: Callable[[str], MultiLegExecutionPlan | None],
                 quote_policy: U16QuotePolicy,
                 repair_price_resolver: Callable[..., Any] | None = None) -> None:
        if validation_only is not True:
            raise ValueError("U16_BRIDGE_VALIDATION_ONLY_REQUIRED")
        if bridge is None or not callable(getattr(bridge, "execute", None)):
            raise ValueError("U16_BRIDGE_EXECUTION_PORT_REQUIRED")
        if getattr(bridge, "freshness_verdict_provider", None) is None:
            raise ValueError("U16_BRIDGE_VALIDATION_FRESHNESS_PROVIDER_REQUIRED")
        if getattr(bridge, "validation_only_track2_identity_validator", None) is None:
            raise ValueError("U16_BRIDGE_SYNTHETIC_IDENTITY_VALIDATOR_REQUIRED")
        if not callable(entry_plan_provider):
            raise ValueError("U16_BRIDGE_ENTRY_PLAN_PROVIDER_REQUIRED")
        if not isinstance(quote_policy, U16QuotePolicy) or not quote_policy.is_resolved():
            raise ValueError("U16_BRIDGE_VALIDATED_QUOTE_AND_RETRY_POLICY_REQUIRED")
        self._bridge = bridge
        self._entry_plan_provider = entry_plan_provider
        self._quote_policy = quote_policy
        self._repair_price_resolver = repair_price_resolver

    def _entry(self, group_id: str, leg_id: str):
        plan = self._entry_plan_provider(group_id)
        if not isinstance(plan, MultiLegExecutionPlan):
            raise ValueError("U16_BRIDGE_AUTHORITATIVE_ENTRY_PLAN_REQUIRED")
        if plan.group_id != group_id or plan.strategy_id != "track2_asymmetric_trap":
            raise ValueError("U16_BRIDGE_ENTRY_PLAN_SCOPE_MISMATCH")
        if str(plan.purpose or "").upper() == "TRAP_CLOSE":
            raise ValueError("U16_BRIDGE_ENTRY_PLAN_REQUIRED")
        matches = [leg for leg in plan.legs if leg.leg_id == leg_id]
        if len(matches) != 1:
            raise ValueError("U16_BRIDGE_ENTRY_LEG_NOT_UNIQUE")
        leg = matches[0]
        identity = self._bridge.identity_for_leg(plan, leg)
        return plan, leg, identity

    def _evidence(self, *, plan: MultiLegExecutionPlan, leg: Any,
                  identity: Any, client_order_id: str, result: Any,
                  close: bool = False) -> U16BridgeSubmissionEvidence:
        reports = tuple(getattr(result, "reports", ()) or ())
        report = next((item for item in reports if item.client_order_id == client_order_id), None)
        if report is None:
            raise ValueError("U16_BRIDGE_EXECUTION_REPORT_NOT_FOUND")
        status = str(getattr(getattr(report, "status", None), "value", report.status)).upper()
        filled = int(getattr(report, "filled_quantity", 0) or 0)
        remaining = int(getattr(report, "remaining_quantity", 0) or 0)
        pending = any(
            pending_plan.group_id == plan.group_id
            and pending_leg.leg_id == leg.leg_id
            and command.instrument_id == identity.instrument_id
            for pending_plan, pending_leg, command in self._bridge.pending_legs.values()
        )
        lots = tuple(
            lot for lot in self._bridge.position_lot_store.open_lots()
            if lot.run_id == self._bridge.run_id
            and lot.strategy_id == plan.strategy_id
            and lot.group_id == plan.group_id
            and lot.instrument_id == identity.instrument_id
            and int(lot.remaining_quantity) > 0
        )
        open_quantity = sum(int(lot.remaining_quantity) for lot in lots)
        account_quantity = self._account_quantity(identity.instrument_id)
        if close:
            reconciled = not pending and open_quantity == 0 and account_quantity == 0
        else:
            all_reports = tuple(self._bridge.groups.get(plan.group_id, ()))
            total_filled = sum(
                int(item.filled_quantity or 0) for item in all_reports
                if item.leg_id == leg.leg_id
            )
            reconciled = (not pending and open_quantity == total_filled
                          and account_quantity == total_filled)
        return U16BridgeSubmissionEvidence(
            client_order_id=client_order_id,
            terminal=status in self.TERMINAL and not pending,
            reconciled=reconciled,
            status=status,
            filled_quantity=filled,
            remaining_quantity=remaining,
        )

    def build_repair_input(
        self, *, group_id: str, leg_id: str, now: datetime,
        quote_policy: U16QuotePolicy,
    ) -> U16RepairInput:
        """Build U16 evidence from the original bridge report, lots, account and quote."""
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("U16_BRIDGE_AWARE_RUNTIME_TIME_REQUIRED")
        if not isinstance(quote_policy, U16QuotePolicy) or quote_policy != self._quote_policy:
            raise ValueError("U16_BRIDGE_EXPLICIT_QUOTE_POLICY_REQUIRED")
        plan, leg, identity = self._entry(group_id, leg_id)
        original_id = self._bridge._client_order_id(plan, leg, identity)
        reports = tuple(self._bridge.groups.get(group_id, ()))
        report = next((item for item in reversed(reports)
                       if item.client_order_id == original_id), None)
        status = str(getattr(getattr(report, "status", None), "value",
                             getattr(report, "status", "UNKNOWN"))).upper()
        terminal_statuses = self.TERMINAL
        terminal = report is not None and status in terminal_statuses
        closed = terminal and status in {"CANCELLED", "REJECTED", "EXPIRED", "FILLED"}

        fills: list[U16Fill] = []
        # Include the original order and every prior U16 attempt for this leg.
        for item in reports:
            if item.leg_id != leg_id or int(getattr(item, "filled_quantity", 0) or 0) <= 0:
                continue
            events = tuple(getattr(item, "execution_fills", ()) or ())
            if events:
                for event in events:
                    execution_id = str(getattr(event, "execution_id", "") or "")
                    quantity = int(getattr(event, "quantity",
                                           getattr(event, "filled_quantity", 0)) or 0)
                    fills.append(U16Fill(execution_id, quantity))
            else:
                fills.append(U16Fill(
                    str(getattr(item, "execution_id", "") or ""),
                    int(item.filled_quantity),
                ))

        lots = tuple(
            lot for lot in self._bridge.position_lot_store.open_lots()
            if lot.run_id == self._bridge.run_id
            and lot.strategy_id == plan.strategy_id
            and lot.group_id == group_id
            and lot.instrument_id == identity.instrument_id
        )
        lot_quantity = sum(int(lot.remaining_quantity) for lot in lots)
        vssf = self._bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
        account_position = vssf.account.positions.get(identity.instrument_id)
        account_decimal = abs(Decimal(str(account_position.get("qty", 0) or 0))) if account_position else Decimal("0")
        account_quantity = int(account_decimal) if account_decimal == account_decimal.to_integral_value() else None
        position_quantity = lot_quantity if account_quantity is not None and lot_quantity == account_quantity else None
        group_lots = self._open_lots(group_id, plan.strategy_id)
        group_by_instrument: dict[str, int] = {}
        for lot in group_lots:
            group_by_instrument[lot.instrument_id] = group_by_instrument.get(lot.instrument_id, 0) + int(lot.remaining_quantity)
        plan_instruments = {
            self._bridge.identity_for_leg(plan, plan_leg).instrument_id
            for plan_leg in plan.legs
        }
        group_position_confirmed = set(group_by_instrument).issubset(plan_instruments)
        for instrument_id in plan_instruments:
            quantity = group_by_instrument.get(instrument_id, 0)
            if self._account_quantity(instrument_id) != quantity:
                group_position_confirmed = False
                break
        group_position_quantity = sum(group_by_instrument.values()) if group_position_confirmed else None

        quote = self._bridge._option_quote_for_instrument_id(identity.instrument_id)
        quote_present = isinstance(quote, dict)
        quote_fresh = False
        quote_spread_within_policy = False
        if quote_present:
            try:
                quote_at = quote.get("timestamp")
                quote_at = quote_at if isinstance(quote_at, datetime) else datetime.fromisoformat(str(quote_at))
                age = (now - quote_at).total_seconds()
                quote_fresh = bool(
                    quote_policy.max_quote_age_seconds is not None
                    and quote_policy.max_quote_age_seconds > 0
                    and quote_at.tzinfo is not None
                    and 0 <= age <= quote_policy.max_quote_age_seconds
                )
                bid, ask = Decimal(str(quote.get("bid"))), Decimal(str(quote.get("ask")))
                quote_spread_within_policy = bool(
                    quote_policy.max_spread is not None
                    and quote_policy.spread_unit == "PRICE"
                    and bid > 0 and ask >= bid
                    and ask - bid <= Decimal(str(quote_policy.max_spread))
                )
            except (TypeError, ValueError, InvalidOperation):
                quote_fresh = quote_spread_within_policy = False

        return U16RepairInput(
            group_id=group_id, leg_id=leg_id, target_quantity=int(leg.quantity),
            original_order_terminal=terminal,
            original_order_cancelled_or_closed=closed,
            original_order_status=status,
            fills=tuple(fills), position_quantity=position_quantity, now=now,
            quote_policy=quote_policy, quote_present=quote_present,
            quote_fresh=quote_fresh,
            quote_spread_within_policy=quote_spread_within_policy,
            group_position_quantity=group_position_quantity,
            group_position_confirmed=group_position_confirmed,
        )

    def _account_quantity(self, instrument_id: str) -> int | None:
        vssf = self._bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
        position = vssf.account.positions.get(instrument_id)
        quantity = abs(Decimal(str(position.get("qty", 0) or 0))) if position else Decimal("0")
        if quantity != quantity.to_integral_value():
            return None
        return int(quantity)

    def _open_lots(self, group_id: str, strategy_id: str) -> tuple[Any, ...]:
        return tuple(
            lot for lot in self._bridge.position_lot_store.open_lots()
            if lot.run_id == self._bridge.run_id
            and lot.strategy_id == strategy_id and lot.group_id == group_id
            and int(lot.remaining_quantity) > 0
        )

    def submit_repair(self, group_id: str, leg_id: str, missing_quantity: int,
                      client_order_id: str, now: datetime) -> U16BridgeSubmissionEvidence:
        if int(missing_quantity) <= 0 or not client_order_id:
            raise ValueError("U16_BRIDGE_REPAIR_QUANTITY_OR_ID_INVALID")
        group_plan, original_leg, identity = self._entry(group_id, leg_id)
        if missing_quantity > original_leg.quantity:
            raise ValueError("U16_BRIDGE_REPAIR_EXCEEDS_ORIGINAL_LEG_TARGET")
        original_id = self._bridge._client_order_id(group_plan, original_leg, identity)
        original_report = next((item for item in self._bridge.groups.get(group_id, ())
                                if item.client_order_id == original_id), None)
        original_status = str(getattr(getattr(original_report, "status", None), "value",
                                      getattr(original_report, "status", ""))).upper()
        if original_report is None or original_status not in self.TERMINAL:
            raise ValueError("U16_BRIDGE_ORIGINAL_ORDER_NOT_TERMINAL")
        if any(pending_plan.group_id == group_id
               for pending_plan, _pending_leg, _command in self._bridge.pending_legs.values()):
            raise ValueError("U16_BRIDGE_REPAIR_GROUP_ORDERS_PENDING")
        all_reports = tuple(self._bridge.groups.get(group_id, ()))
        confirmed_fills = sum(int(item.filled_quantity or 0) for item in all_reports
                              if item.leg_id == leg_id)
        lots = tuple(lot for lot in self._open_lots(group_id, group_plan.strategy_id)
                     if lot.instrument_id == identity.instrument_id)
        lot_quantity = sum(int(lot.remaining_quantity) for lot in lots)
        account_quantity = self._account_quantity(identity.instrument_id)
        if account_quantity is None or lot_quantity != confirmed_fills or account_quantity != confirmed_fills:
            raise ValueError("U16_BRIDGE_REPAIR_FILL_POSITION_NOT_RECONCILED")
        if int(missing_quantity) != int(original_leg.quantity) - confirmed_fills:
            raise ValueError("U16_BRIDGE_REPAIR_MISSING_QUANTITY_MISMATCH")
        if not callable(self._repair_price_resolver):
            raise ValueError("U16_BRIDGE_REPAIR_PRICE_RESOLVER_REQUIRED")
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("U16_BRIDGE_AWARE_REPAIR_TIME_REQUIRED")
        quote = self._bridge._option_quote_for_instrument_id(identity.instrument_id)
        if not isinstance(quote, dict):
            raise ValueError("U16_BRIDGE_REPAIR_CURRENT_QUOTE_REQUIRED")
        try:
            quote_at = quote.get("timestamp")
            quote_at = quote_at if isinstance(quote_at, datetime) else datetime.fromisoformat(str(quote_at))
            age_seconds = (now - quote_at).total_seconds()
            bid, ask = Decimal(str(quote.get("bid"))), Decimal(str(quote.get("ask")))
            if (quote_at.tzinfo is None or age_seconds < 0
                    or age_seconds > int(self._quote_policy.max_quote_age_seconds)
                    or bid <= 0 or ask < bid
                    or ask - bid > Decimal(str(self._quote_policy.max_spread))):
                raise ValueError("U16_BRIDGE_REPAIR_QUOTE_POLICY_REJECTED")
            requested_price = Decimal(str(self._repair_price_resolver(
                group_plan, original_leg, identity, quote, self._quote_policy, now,
            )))
        except Exception as exc:
            raise ValueError("U16_BRIDGE_REPAIR_PRICE_RESOLUTION_FAILED") from exc
        if not requested_price.is_finite() or requested_price <= 0:
            raise ValueError("U16_BRIDGE_REPAIR_LIMIT_PRICE_INVALID")
        repair_leg = replace(original_leg, quantity=int(missing_quantity),
                             requested_price=requested_price)
        repair_plan = replace(
            group_plan, legs=(repair_leg,), attempt_id=client_order_id, purpose="TRAP_REPAIR"
        )
        expected_id = self._bridge._client_order_id(repair_plan, repair_leg, identity)
        result = self._bridge.execute(repair_plan, group_plan=group_plan)
        return self._evidence(plan=group_plan, leg=repair_leg, identity=identity,
                              client_order_id=expected_id, result=result)

    def reconcile_repair(self, group_id: str, leg_id: str, client_order_id: str) -> U16BridgeSubmissionEvidence:
        plan, leg, identity = self._entry(group_id, leg_id)
        report = next((item for item in self._bridge.groups.get(group_id, ())
                       if item.client_order_id == client_order_id and item.leg_id == leg_id), None)
        if report is None:
            raise ValueError("U16_BRIDGE_REPAIR_REPORT_NOT_FOUND")
        return self._evidence(plan=plan, leg=leg, identity=identity,
                              client_order_id=client_order_id,
                              result=type("Result", (), {"reports": (report,)})())

    def cancel_repair_and_reconcile(
        self, group_id: str, leg_id: str, client_order_id: str,
        *, reason: str = "U16_QUOTE_EXPIRED",
    ) -> U16BridgeSubmissionEvidence:
        if client_order_id in self._bridge.pending_legs:
            self._bridge.cancel_pending_order(client_order_id, reason=reason)
        return self.reconcile_repair(group_id, leg_id, client_order_id)

    def reconcile_group_flatten(
        self, group_id: str, aggregate_client_order_id: str,
        client_order_ids: tuple[str, ...],
    ) -> U16BridgeSubmissionEvidence:
        entry_plan = self._entry_plan_provider(group_id)
        if not isinstance(entry_plan, MultiLegExecutionPlan) or entry_plan.group_id != group_id:
            raise ValueError("U16_BRIDGE_AUTHORITATIVE_ENTRY_PLAN_REQUIRED")
        ids = tuple(str(item) for item in client_order_ids)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("U16_BRIDGE_GROUP_FLATTEN_ORDER_IDS_INVALID")
        reports_by_id = {
            item.client_order_id: item
            for item in self._bridge.groups.get(group_id, ())
            if item.client_order_id in ids
        }
        if set(reports_by_id) != set(ids):
            raise ValueError("U16_BRIDGE_GROUP_FLATTEN_REPORTS_INCOMPLETE")
        statuses = [str(getattr(getattr(reports_by_id[item], "status", None), "value",
                                 getattr(reports_by_id[item], "status", ""))).upper()
                    for item in ids]
        pending = any(pending_plan.group_id == group_id
                      for pending_plan, _pending_leg, _command in self._bridge.pending_legs.values())
        lots_flat = not self._open_lots(group_id, entry_plan.strategy_id)
        identities = [self._bridge.identity_for_leg(entry_plan, leg) for leg in entry_plan.legs]
        account_flat = all(self._account_quantity(identity.instrument_id) == 0
                           for identity in identities)
        terminal = all(status in self.TERMINAL for status in statuses) and not pending
        reconciled = terminal and lots_flat and account_flat
        return U16BridgeSubmissionEvidence(
            client_order_id=aggregate_client_order_id, terminal=terminal,
            reconciled=reconciled,
            status="GROUP_FLAT" if reconciled else "GROUP_FLATTEN_TERMINAL" if terminal else "GROUP_FLATTEN_PENDING",
            filled_quantity=sum(int(reports_by_id[item].filled_quantity or 0) for item in ids),
            remaining_quantity=sum(int(reports_by_id[item].remaining_quantity or 0) for item in ids),
            client_order_ids=ids,
        )

    def submit_flatten(self, group_id: str, leg_id: str, position_quantity: int, client_order_id: str) -> U16BridgeSubmissionEvidence:
        """Liquidate every confirmed open leg in the group, never only the trigger leg."""
        if int(position_quantity) <= 0 or not client_order_id:
            raise ValueError("U16_BRIDGE_FLATTEN_QUANTITY_OR_ID_INVALID")
        entry_plan = self._entry_plan_provider(group_id)
        if not isinstance(entry_plan, MultiLegExecutionPlan) or entry_plan.group_id != group_id:
            raise ValueError("U16_BRIDGE_AUTHORITATIVE_ENTRY_PLAN_REQUIRED")
        _plan, trigger_leg, trigger_identity = self._entry(group_id, leg_id)
        group_lots = self._open_lots(group_id, entry_plan.strategy_id)
        if not group_lots:
            raise ValueError("U16_BRIDGE_FLATTEN_OPEN_GROUP_LOTS_REQUIRED")
        group_quantity = sum(int(lot.remaining_quantity) for lot in group_lots)
        if group_quantity != int(position_quantity):
            raise ValueError("U16_BRIDGE_FLATTEN_GROUP_QUANTITY_MISMATCH")
        if any(pending_plan.group_id == group_id
               for pending_plan, _pending_leg, _command in self._bridge.pending_legs.values()):
            raise ValueError("U16_BRIDGE_FLATTEN_PENDING_ORDERS_UNRESOLVED")
        by_instrument: dict[str, int] = {}
        for lot in group_lots:
            by_instrument[lot.instrument_id] = by_instrument.get(lot.instrument_id, 0) + int(lot.remaining_quantity)
        for instrument_id, lot_quantity in by_instrument.items():
            if self._account_quantity(instrument_id) != lot_quantity:
                raise ValueError("U16_BRIDGE_FLATTEN_GROUP_POSITION_NOT_RECONCILED")

        close_plan = self._bridge.build_close_plan_from_open_lots(
            strategy_id=entry_plan.strategy_id,
            purpose="TRAP_CLOSE",
            asset_type="OPTION",
        )
        if close_plan.group_id != group_id or len(close_plan.legs) != len(by_instrument):
            raise ValueError("U16_BRIDGE_FLATTEN_GROUP_SCOPE_NOT_UNIQUE")
        close_instruments = {
            self._bridge.identity_for_leg(close_plan, leg).instrument_id
            for leg in close_plan.legs
        }
        if close_instruments != set(by_instrument):
            raise ValueError("U16_BRIDGE_FLATTEN_GROUP_INSTRUMENT_SET_MISMATCH")
        close_plan = replace(close_plan, attempt_id=client_order_id)
        close_ids = tuple(
            self._bridge._client_order_id(
                close_plan, leg, self._bridge.identity_for_leg(close_plan, leg)
            ) for leg in close_plan.legs
        )
        block = getattr(self._bridge, "block_track2_entry_progress", None)
        if callable(block):
            block(group_id, "U16_GROUP_FLATTEN_SUBMITTED")
        result = self._bridge.execute(close_plan, group_plan=entry_plan)
        reports = tuple(getattr(result, "reports", ()) or ())
        by_id = {item.client_order_id: item for item in reports}
        if any(client_id not in by_id for client_id in close_ids):
            raise ValueError("U16_BRIDGE_GROUP_FLATTEN_REPORTS_INCOMPLETE")
        statuses = [str(getattr(getattr(by_id[item], "status", None), "value",
                                getattr(by_id[item], "status", ""))).upper()
                    for item in close_ids]
        pending = any(pending_plan.group_id == group_id
                      for pending_plan, _pending_leg, _command in self._bridge.pending_legs.values())
        remaining_lots = self._open_lots(group_id, entry_plan.strategy_id)
        account_flat = all(self._account_quantity(instrument_id) == 0 for instrument_id in by_instrument)
        terminal = all(status in self.TERMINAL for status in statuses) and not pending
        reconciled = terminal and not remaining_lots and account_flat
        aggregate_id = "u16-group-flat-" + __import__("hashlib").sha256(
            "|".join((group_id, client_order_id, *close_ids)).encode("utf-8")
        ).hexdigest()[:24]
        return U16BridgeSubmissionEvidence(
            client_order_id=aggregate_id, terminal=terminal, reconciled=reconciled,
            status="GROUP_FLAT" if reconciled else "GROUP_FLATTEN_TERMINAL" if terminal else "GROUP_FLATTEN_PENDING",
            filled_quantity=sum(int(by_id[item].filled_quantity or 0) for item in close_ids),
            remaining_quantity=sum(int(by_id[item].remaining_quantity or 0) for item in close_ids),
            client_order_ids=close_ids,
        )
