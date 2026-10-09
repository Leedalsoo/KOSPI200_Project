"""Runtime-owned multi-leg execution bridge for the Virtual environment."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from contracts.types import BrokerOrderCommand, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from contracts.futures_identity_source_port import FuturesIdentitySourcePort, FuturesInstrumentIdentity, require_futures_identity
from contracts.risk_guard import RiskGuardStatusSource
from core.option.option_master import IOptionContractMaster
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.oms.position_group import PositionGroup, PositionGroupLeg, PositionGroupLegPnL, PositionGroupRegistry, PositionGroupSnapshot, LegStatus
from core.oms.order_router import StandardOrderRouter
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_approval_read_model import RiskApprovalReadModel, RiskApprovalRecord
from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext, route_from_runtime_authoritative_sources,
)
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from contracts.position_provenance import PositionRole, PositionLotProvenance
from contracts.track9_fee_ledger import Track9FeeRecord
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from contracts.track9_position_read_models import (
    Track9OptionPositionAttributionReadModel, Track9InsurancePositionReadModel,
)


@dataclass(frozen=True)
class MultiLegExecutionResult:
    group_id: str
    strategy_id: str
    planned_legs: int
    approved_legs: int
    routed_legs: int
    filled_legs: int
    reports: tuple[ExecutionReport, ...]
    group_complete: bool
    pending_legs: int = 0


class _AckAdapter:
    def __init__(self, broker: Any) -> None:
        self.broker = broker
        self.last_report = None

    def submit(self, command: BrokerOrderCommand, **kwargs: Any):
        report = self.broker.submit(command)
        self.last_report = report
        if report is None:
            from contracts.types import BrokerOrderResponse
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        from contracts.types import BrokerOrderResponse
        status = str(getattr(report, "status", "")).strip().upper()
        if status in {"REJECTED", "FAILED", "CANCELLED", "EXPIRED"}:
            return BrokerOrderResponse(
                command.client_order_id,
                False,
                broker_code=status,
                message=str(getattr(report, "rejected_reason", None) or status),
            )
        broker_order_id = getattr(report, "broker_order_id", None)
        if not broker_order_id:
            execution_id = getattr(report, "execution_id", None)
            broker_order_id = (
                f"VIRTUAL-{execution_id}"
                if execution_id
                else f"VIRTUAL-ORDER-{command.client_order_id}"
            )
        return BrokerOrderResponse(command.client_order_id, True, broker_order_id=str(broker_order_id))


class VirtualMultiLegExecutionBridge:
    """Preserve group/leg identity while routing every leg through Risk -> OMS -> VSSF."""

    def __init__(self, *, bundle: Any, run_id: str, option_master: IOptionContractMaster | None = None, futures_identity_source: FuturesIdentitySourcePort | None = None, option_expiry_source: Any | None = None, risk_config: RiskConfig | None = None, risk_guard_status_source: RiskGuardStatusSource | None = None, execution_result_callback: Callable[[MultiLegExecutionPlan, MultiLegExecutionResult], None] | None = None) -> None:
        self.bundle = bundle
        self.option_master = option_master or getattr(bundle, "option_master", None)
        self.futures_identity_source = futures_identity_source
        self.option_expiry_source = option_expiry_source
        self.fsm = OrderStateMachine()
        self.ack = _AckAdapter(bundle.broker)
        self.router = StandardOrderRouter(order_state_machine=self.fsm, broker_adapter=self.ack)
        vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
        self.risk_gate = RiskGate(RiskEngine(risk_config or RiskConfig(), margin_engine=vssf.margin_engine), risk_guard_status_source=risk_guard_status_source)
        self.risk_approval_read_model = RiskApprovalReadModel()
        self.command_context = CanonicalVSSFCommandContextProvider()
        self.groups: dict[str, list[ExecutionReport]] = {}
        self.position_groups = PositionGroupRegistry()
        if not run_id.strip():
            raise ValueError("MULTI_LEG_RUN_ID_REQUIRED")
        self.run_id = run_id
        self.execution_result_callback = execution_result_callback
        self.position_lot_store = VirtualPositionLotStore()
        self.fee_ledger = VirtualTrack9FeeLedger()
        self.option_position_attribution = Track9OptionPositionAttributionReadModel(self.position_lot_store)
        self.insurance_position = Track9InsurancePositionReadModel(self.position_lot_store)
        self.provenance: dict[str, dict[str, str]] = {}
        self.execution_legs: dict[str, dict[str, object]] = {}
        self.leg_positions: dict[str, Any] = {}
        self.pending_legs: dict[str, tuple[MultiLegExecutionPlan, Any]] = {}

    def identity_for_leg(self, plan: MultiLegExecutionPlan, leg) -> OptionInstrumentIdentity | FuturesInstrumentIdentity:
        if leg.option_type is None and plan.strategy_id in {"Strategy_3_StatArb", "track5_gap_divergence"}:
            return require_futures_identity(self.futures_identity_source)
        if leg.option_type not in {"CALL", "PUT"} or leg.strike is None:
            raise ValueError("MULTI_LEG_OPTION_IDENTITY_REQUIRED")
        if self.option_master is None:
            raise ValueError("MULTI_LEG_OPTION_MASTER_REQUIRED")
        current_tick = getattr(self.bundle.market, "last_tick", None)
        authoritative_expiry = str(getattr(current_tick, "expiry", "") or "").replace("-", "")[:8]
        if len(authoritative_expiry) != 8 and self.option_expiry_source is not None and current_tick is not None:
            observed_symbol = str(getattr(current_tick, "symbol", "") or "").strip()
            if observed_symbol:
                resolved_expiry = self.option_expiry_source.resolve_expiry(observed_symbol)
                if resolved_expiry is not None:
                    authoritative_expiry = str(resolved_expiry).replace("-", "")[:8]
        option_quotes = getattr(self.bundle.market, "option_quotes", {})
        # Multi-leg identity is authoritative independently of quote availability.
        # A missing quote for one leg must not block submission of another leg.
        # The broker/VSSF owns NEW/PENDING -> FILLED lifecycle for the missing leg.
        if len(authoritative_expiry) != 8:
            matching_expiries = sorted({
                str(key[2]).replace("-", "")[:8]
                for key in option_quotes
                if isinstance(key, tuple) and len(key) == 3
                and str(key[0]).upper() == str(leg.option_type).upper()
                and float(key[1]) == float(leg.strike)
            })
            if len(matching_expiries) != 1:
                raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_EXPIRY_REQUIRED")
            authoritative_expiry = matching_expiries[0]
        identity = self.option_master.find_contract_identity(
            authoritative_expiry, leg.option_type, Decimal(str(leg.strike))
        )
        if identity is None or not identity.shrn_iscd:
            raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_IDENTITY_NOT_FOUND")
        return OptionInstrumentIdentity(
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            expiry=identity.expiry.replace("-", "")[:8],
            option_type=identity.option_type,
            strike=identity.strike,
            contract_multiplier=Decimal(str(identity.contract_multiplier)),
            identity_source="OPTION_MASTER",
        )

    def execute(
        self,
        plan: MultiLegExecutionPlan,
        *,
        price: Decimal | None = None,
        group_plan: MultiLegExecutionPlan | None = None,
    ) -> MultiLegExecutionResult:
        group_plan = group_plan or plan
        if group_plan.group_id != plan.group_id or group_plan.strategy_id != plan.strategy_id:
            raise ValueError("MULTI_LEG_GROUP_PLAN_MISMATCH")
        if not plan.legs:
            raise ValueError("MULTI_LEG_PLAN_EMPTY")
        reports: list[ExecutionReport] = []
        approved = routed = filled = 0
        pending_legs = 0
        account = self.bundle.account.snapshot()
        position = self.bundle.position
        vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
        realized_before = Decimal(str(vssf.account.realized_pnl))

        for leg in plan.legs:
            identity = self.identity_for_leg(plan, leg)
            client_order_id = f"{plan.group_id}-{leg.leg_id}"
            is_futures = isinstance(identity, FuturesInstrumentIdentity)
            quote = None
            if is_futures:
                futures_price = Decimal(str(getattr(self.bundle.market, "futures_price", "0")))
                if futures_price <= 0:
                    raise ValueError("MULTI_LEG_AUTHORITATIVE_FUTURES_QUOTE_REQUIRED")
                bid = ask = futures_price
                execution_reference = futures_price
            else:
                option_quotes = getattr(self.bundle.market, "option_quotes", {})
                quote_key = next(
                    (
                        key
                        for key in option_quotes
                        if isinstance(key, tuple)
                        and len(key) == 3
                        and str(key[0]).upper() == identity.option_type
                        and float(key[1]) == float(identity.strike)
                        and str(key[2]).replace("-", "")[:8]
                        == identity.expiry.replace("-", "")[:8]
                    ),
                    None,
                )
                quote = option_quotes.get(quote_key)
                authoritative = self.option_master.get_contract_identity(identity.instrument_id)
                if authoritative is None or authoritative.contract_multiplier is None:
                    raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_MULTIPLIER_REQUIRED")
                if quote is None:
                    # A missing quote on this leg does not invalidate the logical
                    # strategy group. Keep the leg as a deferred order intent and
                    # submit it only when an authoritative quote becomes available.
                    self.pending_legs[client_order_id] = (plan, leg)
                    pending_legs += 1
                    continue
                else:
                    quote_multiplier = quote.get("contract_multiplier")
                    if quote_multiplier is None or Decimal(str(quote_multiplier)) != Decimal(str(authoritative.contract_multiplier)):
                        raise ValueError("MULTI_LEG_OPTION_CONTRACT_MULTIPLIER_MISMATCH")
                    bid = Decimal(str(quote.get("bid", "0")))
                    ask = Decimal(str(quote.get("ask", "0")))
                    execution_reference = ask if leg.side == "BUY" else bid
                    if execution_reference <= 0:
                        raise ValueError("MULTI_LEG_OPTION_QUOTE_INVALID")
            if leg.requested_price is not None:
                requested_price = Decimal(str(leg.requested_price))
            else:
                requested_price = execution_reference
            broker_command = BrokerOrderCommand(
                client_order_id=client_order_id,
                instrument_id=identity.instrument_id,
                side=leg.side,
                quantity=leg.quantity,
                order_type="LIMIT",
                broker_symbol=identity.symbol,
                instrument_identity=identity,
                asset_type="FUTURES" if is_futures else "OPTION",
                requested_price=requested_price,
                strategy_id=plan.strategy_id,
                order_purpose=plan.purpose or "MULTI_LEG",
                track_id=plan.strategy_id,
                tag_id=leg.leg_id,
                group_id=plan.group_id,
                leg_id=leg.leg_id,
                position_role=leg.position_role,
            )
            canonical = self.command_context.build_command(broker_command)
            if quote is not None:
                vssf.order_book.update_bid_ask(float(bid), float(ask), identity.instrument_id)
            result = route_from_runtime_authoritative_sources(
                canonical,
                risk_gate=self.risk_gate,
                context=RiskRouterContext(
                    account_snapshot=account,
                    position_source=position,
                    order_router=self.router,
                    broker_command=broker_command,
                ),
            )
            risk_evaluation = self.risk_gate.last_evaluation_result
            if risk_evaluation is None:
                raise RuntimeError("MULTI_LEG_RISK_RESULT_UNAVAILABLE")
            self.risk_approval_read_model.record(
                RiskApprovalRecord(
                    plan.strategy_id, plan.group_id, leg.leg_id, client_order_id, risk_evaluation
                )
            )
            if not result.routed:
                continue
            approved += 1
            routed += 1
            raw = self.ack.last_report
            if raw is None:
                continue
            report = ExecutionReport(
                client_order_id=raw.client_order_id,
                broker_order_id=f"VIRTUAL-{raw.execution_id}",
                execution_id=raw.execution_id,
                status=raw.status,
                filled_quantity=raw.filled_quantity,
                remaining_quantity=raw.remaining_quantity,
                execution_price=raw.execution_price,
                execution_timestamp=raw.execution_timestamp,
                fee=(Decimal(str(raw.fee)) if getattr(raw, "fee", None) is not None else None),
                source_freshness=getattr(raw, "source_freshness", None),
                rejected_reason=getattr(raw, "rejected_reason", None),
                group_id=plan.group_id,
                leg_id=leg.leg_id,
            )
            reports.append(report)
            if report.execution_id:
                self.execution_legs[report.execution_id] = {
                    "strategy_id": plan.strategy_id,
                    "side": leg.side,
                    "position_role": leg.position_role,
                    "asset_type": "OPTION" if isinstance(identity, OptionInstrumentIdentity) else "FUTURES",
                    "option_type": getattr(identity, "option_type", None),
                    "contract_multiplier": identity.contract_multiplier,
                }
            if report.status == "FILLED" and report.filled_quantity > 0:
                if not report.execution_id or report.execution_timestamp is None:
                    raise RuntimeError("MULTI_LEG_POSITION_PROVENANCE_EXECUTION_REQUIRED")
                role = PositionRole(leg.position_role)
                lot = PositionLotProvenance(
                    run_id=self.run_id,
                    instrument_id=identity.instrument_id,
                    strategy_id=plan.strategy_id,
                    group_id=plan.group_id,
                    leg_id=leg.leg_id,
                    client_order_id=client_order_id,
                    execution_id=report.execution_id,
                    side=leg.side,
                    opened_quantity=report.filled_quantity,
                    remaining_quantity=report.filled_quantity,
                    execution_timestamp=report.execution_timestamp,
                    instrument_identity=identity,
                    contract_multiplier=identity.contract_multiplier,
                    identity_source=identity.identity_source or "",
                    position_role=role,
                )
                self.position_lot_store.apply_execution(lot)
                if report.fee is None or report.execution_price is None:
                    raise RuntimeError("MULTI_LEG_FEE_PROVENANCE_EXECUTION_REQUIRED")
                self.fee_ledger.record(
                    Track9FeeRecord(
                        run_id=self.run_id,
                        strategy_id=plan.strategy_id,
                        group_id=plan.group_id,
                        leg_id=leg.leg_id,
                        client_order_id=client_order_id,
                        execution_id=report.execution_id,
                        instrument_id=identity.instrument_id,
                        fee_amount=report.fee,
                        executed_quantity=report.filled_quantity,
                        executed_price=report.execution_price,
                        executed_at=report.execution_timestamp,
                        source="VSSF:CanonicalExecutionReport.fee",
                    )
                )
            # Only an actual positive-quantity fill may mutate position state.
            # Rejected/no-fill broker reports are still retained for audit, but
            # must not be passed to the fill adapter (which correctly rejects qty=0).
            if report.status == "FILLED" and report.filled_quantity <= 0:
                raise RuntimeError("MULTI_LEG_FILLED_QUANTITY_REQUIRED")
            if report.filled_quantity > 0:
                from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
                from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter
                leg_position = self.leg_positions.get(identity.instrument_id)
                if leg_position is None:
                    leg_position = VirtualPositionAggregate(instrument_id=identity.instrument_id)
                    self.leg_positions[identity.instrument_id] = leg_position
                VirtualPositionFillAdapter(leg_position).apply(broker_command, report)
            self.provenance[report.execution_id or client_order_id] = {
                "strategy_id": plan.strategy_id, "group_id": plan.group_id,
                "leg_id": leg.leg_id, "client_order_id": client_order_id,
                "execution_id": report.execution_id or "",
                "instrument_id": identity.instrument_id, "symbol": identity.symbol,
                "expiry": getattr(identity, "expiry", "") or "", "option_type": getattr(identity, "option_type", "") or "",
                "strike": str(getattr(identity, "strike", "") or ""),
                "contract_multiplier": str(identity.contract_multiplier),
                "identity_source": identity.identity_source or "",
            }
            if report.status == "FILLED":
                filled += report.filled_quantity

        merged_reports = self._merge_group_reports(group_plan, reports)
        self.groups[group_plan.group_id] = list(merged_reports)
        group_legs = tuple(
            PositionGroupLeg(
                leg_id=leg.leg_id, group_id=group_plan.group_id,
                instrument_id=self.identity_for_leg(group_plan, leg).instrument_id,
                side=leg.side, quantity=leg.quantity,
                contract_multiplier=self.identity_for_leg(group_plan, leg).contract_multiplier,
                identity_source=self.identity_for_leg(group_plan, leg).identity_source or "",
                status=(
                    LegStatus.FILLED
                    if any(r.leg_id == leg.leg_id and r.status == "FILLED" for r in merged_reports)
                    else LegStatus.PENDING
                    if (
                        any(r.leg_id == leg.leg_id and r.status in {"NEW", "PARTIALLY_FILLED"} for r in merged_reports)
                        or f"{group_plan.group_id}-{leg.leg_id}" in self.pending_legs
                    )
                    else LegStatus.REJECTED
                ),
            ) for leg in group_plan.legs
        )
        group = PositionGroup(group_plan.group_id, group_plan.strategy_id, "MULTI_LEG", group_legs)
        if plan.group_id not in self.position_groups.all():
            self.position_groups.register(group)
        else:
            self.position_groups.replace(group)
        current_futures = float(getattr(self.bundle.market, "futures_price", price))
        option_quotes = getattr(self.bundle.market, "option_quotes", {})
        pnl_legs = []
        for leg in group_plan.legs:
            rep = next((r for r in merged_reports if r.leg_id == leg.leg_id), None)
            if rep is None or rep.execution_price is None or rep.filled_quantity <= 0:
                continue
            identity = self.identity_for_leg(group_plan, leg)
            if isinstance(identity, FuturesInstrumentIdentity):
                current = current_futures
            else:
                quote = next(
                    (
                        value
                        for key, value in option_quotes.items()
                        if isinstance(key, tuple)
                        and len(key) == 3
                        and str(key[0]).upper() == identity.option_type
                        and float(key[1]) == float(identity.strike)
                        and str(key[2]).replace("-", "")[:8]
                        == identity.expiry.replace("-", "")[:8]
                    ),
                    None,
                )
                if quote is None or quote.get("last") is None:
                    raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_MARK_NOT_FOUND")
                current = float(quote["last"])
            position_state = self.leg_positions.get(identity.instrument_id)
            if position_state is None:
                raise ValueError("MULTI_LEG_POSITION_STATE_REQUIRED")
            position_snapshot = position_state.snapshot().get(identity.instrument_id)
            if isinstance(identity, FuturesInstrumentIdentity):
                multiplier = identity.contract_multiplier
            else:
                if position_snapshot is None:
                    # A closing fill may flatten the position before realized PnL is calculated.
                    # The execution identity remains authoritative for the multiplier.
                    multiplier = identity.contract_multiplier
                else:
                    if position_snapshot.contract_multiplier is None:
                        raise ValueError("MULTI_LEG_POSITION_CONTRACT_MULTIPLIER_REQUIRED")
                    multiplier = position_snapshot.contract_multiplier
                    if position_snapshot.identity_source != identity.identity_source:
                        raise ValueError("MULTI_LEG_POSITION_IDENTITY_PROVENANCE_MISMATCH")
            # The execution-time mark is not realized PnL.  For the leg read model
            # retain only an MTM projection when the authoritative VSSF position is open.
            position_snapshot = vssf.account.positions.get(identity.instrument_id)
            if position_snapshot is None:
                leg_unrealized = Decimal("0")
            else:
                avg_price = Decimal(str(position_snapshot["avg_price"]))
                quantity = Decimal(str(position_snapshot["qty"]))
                side = str(position_snapshot["side"])
                mark = Decimal(str(current))
                leg_unrealized = (
                    (mark - avg_price) if side == "BUY" else (avg_price - mark)
                ) * quantity * multiplier
            pnl_legs.append(
                PositionGroupLegPnL(
                    leg.leg_id, group_plan.group_id, identity.instrument_id, rep.filled_quantity,
                    multiplier, identity.identity_source or "",
                    float(rep.execution_price), current, float(leg_unrealized),
                    self.run_id, rep.client_order_id, rep.execution_id or ""
                )
            )
        realized_after = Decimal(str(vssf.account.realized_pnl))
        realized_pnl = realized_after - realized_before
        unrealized_pnl = sum(Decimal(str(x.unrealized_pnl)) for x in pnl_legs)
        total_pnl = realized_pnl + unrealized_pnl
        snapshot = PositionGroupSnapshot(
            group_plan.group_id, group_plan.strategy_id, group.is_complete, tuple(pnl_legs),
            float(realized_pnl), float(unrealized_pnl), float(total_pnl)
        )
        self.position_groups.update_snapshot(snapshot)
        result = MultiLegExecutionResult(
            group_id=group_plan.group_id,
            strategy_id=group_plan.strategy_id,
            planned_legs=len(group_plan.legs),
            approved_legs=approved,
            routed_legs=routed,
            filled_legs=filled,
            reports=tuple(reports),
            group_complete=(len(merged_reports) == len(group_plan.legs) and all(r.status == "FILLED" for r in merged_reports)),
            pending_legs=pending_legs + sum(
                1 for leg in group_plan.legs
                if f"{group_plan.group_id}-{leg.leg_id}" in self.pending_legs
                and not any(r.leg_id == leg.leg_id and r.status == "FILLED" for r in merged_reports)
            ),
        )
        if self.execution_result_callback is not None:
            self.execution_result_callback(plan, result)
        return result

    def process_pending_quotes(self) -> tuple[MultiLegExecutionResult, ...]:
        """Submit deferred legs independently when authoritative quote appears."""
        completed: list[MultiLegExecutionResult] = []
        for client_order_id, (plan, leg) in tuple(self.pending_legs.items()):
            identity = self.identity_for_leg(plan, leg)
            option_quotes = getattr(self.bundle.market, "option_quotes", {})
            quote_key = next(
                (
                    key for key in option_quotes
                    if isinstance(key, tuple) and len(key) == 3
                    and str(key[0]).upper() == str(identity.option_type).upper()
                    and float(key[1]) == float(identity.strike)
                    and str(key[2]).replace("-", "")[:8] == identity.expiry.replace("-", "")[:8]
                ),
                None,
            )
            if quote_key is None or option_quotes.get(quote_key) is None:
                continue
            single_plan = MultiLegExecutionPlan(
                group_id=plan.group_id,
                strategy_id=plan.strategy_id,
                purpose=plan.purpose,
                legs=(leg,),
            )
            result = self.execute(single_plan, group_plan=plan)
            if result.routed_legs <= 0 and result.filled_legs <= 0:
                continue
            self.pending_legs.pop(client_order_id, None)
            completed.append(result)
        return tuple(completed)

    def _merge_group_reports(
        self, group_plan: MultiLegExecutionPlan, new_reports: Sequence[ExecutionReport]
    ) -> tuple[ExecutionReport, ...]:
        """Keep the latest report for every leg, including fills completed after deferral."""
        by_leg = {
            report.leg_id: report
            for report in self.groups.get(group_plan.group_id, ())
            if report.leg_id
        }
        for report in new_reports:
            if report.leg_id:
                by_leg[report.leg_id] = report
        ordered = [
            by_leg[leg.leg_id]
            for leg in group_plan.legs
            if leg.leg_id in by_leg
        ]
        return tuple(ordered)

    def group_reports(self, group_id: str) -> tuple[ExecutionReport, ...]:
        return tuple(self.groups.get(group_id, ()))

    def risk_approvals(self, group_id: str) -> tuple[RiskApprovalRecord, ...]:
        return self.risk_approval_read_model.for_group(group_id)
