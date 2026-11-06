"""Runtime-owned multi-leg execution bridge for the Virtual environment."""
from __future__ import annotations
from dataclasses import dataclass, replace
from hashlib import sha256
from decimal import Decimal
from typing import Any, Callable

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from contracts.types import BrokerOrderCommand, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from contracts.market_data_freshness import FreshnessVerdict, admits_freshness_verdict_for_identity, permits_risk_increasing_order
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
from application.composition.strategy5_risk_diagnostic_jsonl import Strategy5RiskDiagnosticJsonl
from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext, route_from_runtime_authoritative_sources, account_snapshot_to_risk_input,
)
from core.runtime.reference_execution_pipeline import CanonicalRiskCommandAdapter
from core.risk.risk_position import position_manager_to_risk_input
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
    # True only when the authoritative execution-created PositionLotStore has no
    # remaining lot for this strategy on any instrument touched by this plan.
    position_flat: bool = False


class _AckAdapter:
    def __init__(self, broker: Any) -> None:
        self.broker = broker
        self.last_report = None

    def submit(self, command: BrokerOrderCommand, **kwargs: Any):
        try:
            report = self.broker.submit(command)
        except Exception:
            # A transport exception does not prove the broker rejected the order.
            # Reconcile by the deterministic client order ID before classifying it.
            report = None
            query = getattr(self.broker, "query", None)
            if callable(query):
                try:
                    report = query(command.client_order_id)
                except Exception:
                    report = None
            if report is None:
                report = ExecutionReport(
                    client_order_id=command.client_order_id,
                    broker_order_id=None,
                    execution_id=None,
                    status="UNKNOWN",
                    filled_quantity=0,
                    remaining_quantity=int(getattr(command, "quantity", 0) or 0),
                    execution_price=None,
                    execution_timestamp=None,
                    rejected_reason="VIRTUAL_ORDER_STATUS_RECONCILIATION_REQUIRED",
                    group_id=getattr(command, "group_id", None),
                    leg_id=getattr(command, "leg_id", None),
                )
        self.last_report = report
        from contracts.types import BrokerOrderResponse
        if report is None:
            return BrokerOrderResponse(command.client_order_id, False, message="VIRTUAL_ORDER_NOT_EXECUTED")
        status = str(getattr(report, "status", "")).strip().upper()
        if status in {"REJECTED", "FAILED", "CANCELLED", "EXPIRED", "UNKNOWN", "RECONCILIATION_REQUIRED"}:
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

    def __init__(self, *, bundle: Any, run_id: str, option_master: IOptionContractMaster | None = None, futures_identity_source: FuturesIdentitySourcePort | None = None, option_expiry_source: Any | None = None, risk_config: RiskConfig | None = None, risk_guard_status_source: RiskGuardStatusSource | None = None, execution_result_callback: Callable[[MultiLegExecutionPlan, MultiLegExecutionResult], None] | None = None, freshness_verdict_provider: Callable[..., FreshnessVerdict | None] | None = None, validation_order_gate: Callable[[MultiLegExecutionPlan, list[tuple]], None] | None = None) -> None:
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
        self._strategy5_risk_diagnostic = Strategy5RiskDiagnosticJsonl()
        self.risk_diagnostic_status: dict[str, str | None] = {
            "status": "NOT_ATTEMPTED", "error": None, "artifact_path": None,
        }
        self.command_context = CanonicalVSSFCommandContextProvider()
        self.groups: dict[str, list[ExecutionReport]] = {}
        self.position_groups = PositionGroupRegistry()
        # Strategy 8 submits CALL then PUT as separate plans under one entry group.
        # Retain the group-level plan so PositionGroup/PnL reconciliation sees both legs.
        self._group_plans: dict[str, MultiLegExecutionPlan] = {}
        if not run_id.strip():
            raise ValueError("MULTI_LEG_RUN_ID_REQUIRED")
        self.run_id = run_id
        self.execution_result_callback = execution_result_callback
        self.freshness_verdict_provider = freshness_verdict_provider
        self.validation_order_gate = validation_order_gate
        self.position_lot_store = VirtualPositionLotStore()
        self.fee_ledger = VirtualTrack9FeeLedger()
        self.option_position_attribution = Track9OptionPositionAttributionReadModel(self.position_lot_store)
        self.insurance_position = Track9InsurancePositionReadModel(self.position_lot_store)
        self.provenance: dict[str, dict[str, str]] = {}
        self.execution_legs: dict[str, dict[str, object]] = {}
        self.leg_positions: dict[str, Any] = {}
        self.pending_legs: dict[str, tuple[MultiLegExecutionPlan, Any, BrokerOrderCommand]] = {}
        self._applied_execution_fingerprints: dict[str, tuple] = {}

    def _record_strategy5_risk_preflight_diagnostic(self, **payload: Any) -> None:
        """Record diagnostic evidence without allowing storage failures to affect trading."""
        try:
            artifact = self._strategy5_risk_diagnostic.append_preflight(**payload)
            self.risk_diagnostic_status = {
                "status": "RECORDED", "error": None, "artifact_path": str(artifact),
            }
        except Exception as exc:
            self.risk_diagnostic_status = {
                "status": "FAILED", "error": type(exc).__name__, "artifact_path": None,
            }

    @staticmethod
    def _preflight_rejection_reason(evaluation, admitted: bool, aggregate_rejection: str | None) -> str:
        """Keep the originating leg rejection visible while retaining group fail-closed semantics."""
        if aggregate_rejection:
            return aggregate_rejection
        if not admitted and evaluation.rejection_reason:
            return str(evaluation.rejection_reason)
        return "GROUP_RISK_PREFLIGHT_REJECTED"
    def _position_flat_for_plan(self, plan: MultiLegExecutionPlan) -> bool:
        """Conservatively verify flatness across the complete entry group."""
        group = self.position_groups.all().get(plan.group_id)
        if group is not None:
            instrument_ids = {leg.instrument_id for leg in group.legs}
        else:
            try:
                instrument_ids = {
                    self.identity_for_leg(plan, leg).instrument_id for leg in plan.legs
                }
            except (ValueError, TypeError, AttributeError):
                return False
        if not instrument_ids:
            return False
        if any(
            lot.run_id == self.run_id
            and lot.strategy_id == plan.strategy_id
            and lot.group_id == plan.group_id
            and lot.instrument_id in instrument_ids
            and lot.remaining_quantity > 0
            for lot in self.position_lot_store.open_lots()
        ):
            return False
        vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
        return not any(
            Decimal(str(position.get("qty", 0))) > 0
            for instrument_id, position in vssf.account.positions.items()
            if instrument_id in instrument_ids
        )

    def _position_flat_for_result(self, plan: MultiLegExecutionPlan) -> bool:
        """Return flatness for the closed leg scope; S8 keeps full-group semantics."""
        purpose = str(plan.purpose or "").strip().upper()
        if plan.strategy_id == "track6_daily_tail_insurance" and (
            purpose == "DAILY_TAIL_INSURANCE_FORCE_CLOSE"
            or purpose in {"DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT", "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL"}
        ):
            try:
                instrument_ids = {self.identity_for_leg(plan, leg).instrument_id for leg in plan.legs}
            except (ValueError, TypeError, AttributeError):
                return False
            if not instrument_ids:
                return False
            if any(
                lot.run_id == self.run_id and lot.strategy_id == plan.strategy_id
                and lot.group_id == plan.group_id and lot.instrument_id in instrument_ids
                and lot.remaining_quantity > 0
                for lot in self.position_lot_store.open_lots()
            ):
                return False
            vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
            return not any(
                Decimal(str(position.get("qty", 0))) > 0
                for instrument_id, position in vssf.account.positions.items()
                if instrument_id in instrument_ids
            )
        return self._position_flat_for_plan(plan)

    def _is_terminal_execution_plan(self, plan: MultiLegExecutionPlan) -> bool:
        purpose = str(plan.purpose or "").strip().upper()
        if plan.strategy_id == "track6_daily_tail_insurance":
            return purpose == "DAILY_TAIL_INSURANCE_FORCE_CLOSE" or purpose in {
                "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT",
                "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL",
            }
        if plan.strategy_id != "track8_macro_regime_monthly_strangle":
            return False
        return any(token in purpose for token in ("CLOSE", "EXPIRY", "SETTLEMENT", "LIQUIDATION"))

    def _build_terminal_position_group_snapshot(
        self, *, plan: MultiLegExecutionPlan,
        previous: PositionGroupSnapshot, realized_delta: Decimal,
        reports: tuple[ExecutionReport, ...],
    ) -> PositionGroupSnapshot:
        """Accumulate close realized PnL while retaining entry-leg provenance."""
        vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
        account_positions = vssf.account.positions
        open_lots = tuple(
            lot for lot in self.position_lot_store.open_lots()
            if lot.run_id == self.run_id
            and lot.strategy_id == plan.strategy_id
            and lot.group_id == plan.group_id
        )
        lot_quantities: dict[str, int] = {}
        for lot in open_lots:
            lot_quantities[lot.instrument_id] = (
                lot_quantities.get(lot.instrument_id, 0) + int(lot.remaining_quantity)
            )

        close_prices: dict[str, Decimal] = {}
        for report in reports:
            if report.filled_quantity <= 0 or report.execution_price is None:
                continue
            provenance = self.provenance.get(report.execution_id or "", {})
            instrument_id = provenance.get("instrument_id")
            if instrument_id:
                close_prices[instrument_id] = Decimal(str(report.execution_price))

        refreshed_legs = []
        for leg in previous.legs:
            open_quantity = lot_quantities.get(leg.instrument_id, 0)
            position = account_positions.get(leg.instrument_id)
            account_quantity = int(Decimal(str(position.get("qty", 0)))) if position else 0
            if account_quantity != open_quantity:
                raise ValueError(
                    f"POSITION_GROUP_TERMINAL_LOT_ACCOUNT_QUANTITY_MISMATCH:"
                    f"{leg.instrument_id}:{open_quantity}:{account_quantity}"
                )
            if position is None:
                quantity = 0
                unrealized = Decimal("0")
                current_price = close_prices.get(
                    leg.instrument_id, Decimal(str(leg.current_price))
                )
            else:
                mark_value = position.get("mark_price")
                if mark_value is None:
                    raise ValueError(
                        f"POSITION_GROUP_TERMINAL_MARK_PRICE_REQUIRED:{leg.instrument_id}"
                    )
                quantity = Decimal(str(position.get("qty", 0)))
                side = str(position.get("side", "")).strip().upper()
                if side not in {"BUY", "SELL"}:
                    raise ValueError(
                        f"POSITION_GROUP_TERMINAL_SIDE_INVALID:{leg.instrument_id}"
                    )
                average_price = Decimal(str(position.get("avg_price")))
                current_price = Decimal(str(mark_value))
                multiplier = Decimal(str(leg.contract_multiplier))
                delta = current_price - average_price if side == "BUY" else average_price - current_price
                unrealized = delta * quantity * multiplier
            refreshed_legs.append(
                replace(
                    leg,
                    quantity=int(quantity),
                    current_price=float(current_price),
                    unrealized_pnl=float(unrealized),
                )
            )

        realized_pnl = Decimal(str(previous.realized_pnl)) + realized_delta
        unrealized_pnl = sum(
            (Decimal(str(leg.unrealized_pnl)) for leg in refreshed_legs),
            Decimal("0"),
        )
        return replace(
            previous,
            legs=tuple(refreshed_legs),
            realized_pnl=float(realized_pnl),
            unrealized_pnl=float(unrealized_pnl),
            total_pnl=float(realized_pnl + unrealized_pnl),
        )

    def refresh_position_group_marks(self) -> int:
        """Refresh open-leg MTM snapshots from the current VSSF account marks."""
        vssf = self.bundle.execution._authoritative_execute.__self__.vssf_runtime
        account_positions = vssf.account.positions
        pending_updates: list[PositionGroupSnapshot] = []

        for group_id in self.position_groups.all():
            snapshot = self.position_groups.snapshot(group_id)
            if snapshot is None:
                continue

            refreshed_legs = []
            for leg in snapshot.legs:
                position = account_positions.get(leg.instrument_id)
                if position is None:
                    refreshed_legs.append(replace(leg, quantity=0, unrealized_pnl=0.0))
                    continue

                mark_value = position.get("mark_price")
                if mark_value is None:
                    raise ValueError(
                        f"POSITION_GROUP_MTM_MARK_PRICE_REQUIRED:{leg.instrument_id}"
                    )
                quantity = Decimal(str(position.get("qty", 0)))
                if quantity <= 0:
                    raise ValueError(
                        f"POSITION_GROUP_MTM_POSITIVE_QUANTITY_REQUIRED:{leg.instrument_id}"
                    )
                side = str(position.get("side", "")).strip().upper()
                if side not in {"BUY", "SELL"}:
                    raise ValueError(
                        f"POSITION_GROUP_MTM_SIDE_INVALID:{leg.instrument_id}"
                    )
                average_price = Decimal(str(position.get("avg_price")))
                mark_price = Decimal(str(mark_value))
                multiplier = Decimal(str(leg.contract_multiplier))
                if multiplier <= 0:
                    raise ValueError(
                        f"POSITION_GROUP_MTM_MULTIPLIER_INVALID:{leg.instrument_id}"
                    )
                price_delta = (
                    mark_price - average_price
                    if side == "BUY"
                    else average_price - mark_price
                )
                unrealized = price_delta * quantity * multiplier
                refreshed_legs.append(
                    replace(
                        leg,
                        quantity=int(quantity),
                        avg_price=float(average_price),
                        current_price=float(mark_price),
                        unrealized_pnl=float(unrealized),
                    )
                )

            unrealized_pnl = sum(
                (Decimal(str(leg.unrealized_pnl)) for leg in refreshed_legs),
                Decimal("0"),
            )
            realized_pnl = Decimal(str(snapshot.realized_pnl))
            pending_updates.append(
                replace(
                    snapshot,
                    legs=tuple(refreshed_legs),
                    unrealized_pnl=float(unrealized_pnl),
                    total_pnl=float(realized_pnl + unrealized_pnl),
                )
            )

        # Validate every group before publishing any snapshot update.
        for snapshot in pending_updates:
            self.position_groups.update_snapshot(snapshot)
        return len(pending_updates)

    def build_close_plan_from_open_lots(
        self, *, strategy_id: str, purpose: str,
        asset_type: str | None = None, leg_id_prefix: str | None = None,
        option_type: str | None = None, strike: Decimal | None = None,
        expiry: str | None = None,
    ) -> MultiLegExecutionPlan:
        """Build a close plan from authoritative lots, optionally scoped to an asset class."""
        from collections import defaultdict
        from contracts.types import ExecutionLeg

        candidate_lots = tuple(
            lot for lot in self.position_lot_store.open_lots()
            if lot.run_id == self.run_id and lot.strategy_id == strategy_id and lot.remaining_quantity > 0
        )
        if asset_type is not None:
            requested_type = asset_type.strip().upper()
            if requested_type not in {"OPTION", "FUTURES"}:
                raise ValueError(f"UNSUPPORTED_CLOSE_ASSET_TYPE:{asset_type}")
            selected = []
            for lot in candidate_lots:
                identity = lot.instrument_identity
                if identity is None:
                    raise ValueError(f"AUTHORITATIVE_INSTRUMENT_IDENTITY_REQUIRED:{strategy_id}:{lot.instrument_id}")
                if isinstance(identity, OptionInstrumentIdentity):
                    kind = "OPTION"
                elif isinstance(identity, FuturesInstrumentIdentity):
                    kind = "FUTURES"
                else:
                    raise ValueError(f"AUTHORITATIVE_INSTRUMENT_IDENTITY_TYPE_REQUIRED:{strategy_id}:{lot.instrument_id}")
                if kind == requested_type:
                    selected.append(lot)
            lots = tuple(selected)
        else:
            lots = candidate_lots
        if option_type is not None or strike is not None or expiry is not None:
            requested_option_type = option_type.strip().upper() if option_type is not None else None
            requested_strike = Decimal(str(strike)) if strike is not None else None
            requested_expiry = require_exact_option_expiry(expiry) if expiry is not None else None
            selected = []
            for lot in lots:
                identity = lot.instrument_identity
                if not isinstance(identity, OptionInstrumentIdentity):
                    continue
                if requested_option_type is not None and identity.option_type != requested_option_type:
                    continue
                if requested_strike is not None and (identity.strike is None or Decimal(str(identity.strike)) != requested_strike):
                    continue
                if requested_expiry is not None and identity.expiry != requested_expiry:
                    continue
                selected.append(lot)
            lots = tuple(selected)
        if not lots:
            raise ValueError(f"AUTHORITATIVE_OPEN_LOTS_REQUIRED:{strategy_id}:{asset_type or 'ALL'}")
        group_ids = {lot.group_id for lot in lots}
        if len(group_ids) != 1:
            raise ValueError(f"AMBIGUOUS_OPEN_POSITION_GROUPS:{strategy_id}:{len(group_ids)}")

        aggregated = defaultdict(int)
        identities = {}
        roles = {}
        sides = {}
        for lot in lots:
            identity = lot.instrument_identity
            if identity is None or not identity.instrument_id:
                raise ValueError(f"AUTHORITATIVE_INSTRUMENT_IDENTITY_REQUIRED:{strategy_id}:{lot.instrument_id}")
            if identity.instrument_id != lot.instrument_id:
                raise ValueError(f"POSITION_LOT_IDENTITY_MISMATCH:{strategy_id}:{lot.instrument_id}")
            if isinstance(identity, OptionInstrumentIdentity):
                if identity.option_type not in {"CALL", "PUT"} or identity.strike is None or not identity.expiry:
                    raise ValueError(f"AUTHORITATIVE_OPTION_IDENTITY_REQUIRED:{strategy_id}:{lot.instrument_id}")
                identity_kind = "OPTION"
                expiry = identity.expiry
                option_type = identity.option_type
                strike = str(identity.strike)
            elif isinstance(identity, FuturesInstrumentIdentity):
                identity_kind = "FUTURES"
                expiry = ""
                option_type = None
                strike = ""
            else:
                raise ValueError(f"AUTHORITATIVE_INSTRUMENT_IDENTITY_TYPE_REQUIRED:{strategy_id}:{lot.instrument_id}")
            key = (identity_kind, identity.instrument_id, expiry, option_type, strike, str(lot.position_role), lot.side)
            aggregated[key] += int(lot.remaining_quantity)
            identities[key] = identity
            roles[key] = str(lot.position_role)
            sides[key] = lot.side

        legs = []
        for key in sorted(aggregated, key=lambda item: tuple(str(part) for part in item)):
            identity = identities[key]
            digest = sha256("|".join(str(part) for part in key).encode("utf-8")).hexdigest()[:12]
            close_side = "SELL" if sides[key] == "BUY" else "BUY"
            leg_id = f"{leg_id_prefix}-{digest}" if leg_id_prefix else f"close-{digest}"
            legs.append(ExecutionLeg(
                leg_id=leg_id, side=close_side, quantity=aggregated[key],
                option_type=getattr(identity, "option_type", None),
                strike=getattr(identity, "strike", None),
                position_role=roles[key], instrument_identity=identity,
            ))
        return MultiLegExecutionPlan(
            group_id=next(iter(group_ids)), strategy_id=strategy_id,
            purpose=purpose, legs=tuple(legs),
        )

    def identity_for_leg(self, plan: MultiLegExecutionPlan, leg) -> OptionInstrumentIdentity | FuturesInstrumentIdentity:
        stored_identity = getattr(leg, "instrument_identity", None)
        if stored_identity is not None:
            if not stored_identity.instrument_id:
                raise ValueError("MULTI_LEG_STORED_INSTRUMENT_IDENTITY_INVALID")
            if isinstance(stored_identity, OptionInstrumentIdentity):
                if stored_identity.option_type not in {"CALL", "PUT"} or stored_identity.strike is None or not stored_identity.expiry:
                    raise ValueError("MULTI_LEG_STORED_OPTION_IDENTITY_INVALID")
            elif not isinstance(stored_identity, FuturesInstrumentIdentity):
                raise ValueError("MULTI_LEG_STORED_INSTRUMENT_IDENTITY_TYPE_INVALID")
            return stored_identity
        if leg.option_type is None and plan.strategy_id in {"Strategy_3_StatArb", "track5_gap_divergence"}:
            return require_futures_identity(self.futures_identity_source)
        if leg.option_type not in {"CALL", "PUT"} or leg.strike is None:
            raise ValueError("MULTI_LEG_OPTION_IDENTITY_REQUIRED")
        if self.option_master is None:
            raise ValueError("MULTI_LEG_OPTION_MASTER_REQUIRED")
        current_tick = getattr(self.bundle.market, "last_tick", None)
        authoritative_expiry = ""
        raw_tick_expiry = str(getattr(current_tick, "expiry", "") or "").strip()
        if raw_tick_expiry:
            try:
                authoritative_expiry = require_exact_option_expiry(raw_tick_expiry)
            except CanonicalOptionExpiryError:
                authoritative_expiry = ""
        if not authoritative_expiry and self.option_expiry_source is not None and current_tick is not None:
            observed_symbol = str(getattr(current_tick, "symbol", "") or "").strip()
            if observed_symbol:
                resolved_expiry = self.option_expiry_source.resolve_expiry(observed_symbol)
                if resolved_expiry is not None:
                    try:
                        authoritative_expiry = require_exact_option_expiry(resolved_expiry)
                    except CanonicalOptionExpiryError:
                        authoritative_expiry = ""
        # Quotes are not an authoritative contract-master source; never infer expiry from them.
        if not authoritative_expiry:
            raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_EXPIRY_REQUIRED")
        if self.validation_order_gate is not None:
            # Validation-only S6 may use only identities materialized from the
            # manifest-adapted dataset. Do not call SyntheticOptionContractMaster's
            # fallback generator for contracts absent from the dataset.
            identity = next((
                candidate for candidate in self.option_master.list_contract_identities()
                if str(candidate.expiry).replace("-", "")[:8] == authoritative_expiry.replace("-", "")[:8]
                and str(candidate.option_type).upper() == str(leg.option_type).upper()
                and candidate.strike is not None
                and Decimal(str(candidate.strike)) == Decimal(str(leg.strike))
                and str(getattr(candidate, "shrn_iscd", "")).startswith("SYNTHETIC_CONTRACT:")
            ), None)
        else:
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

    @staticmethod
    def _client_order_id(plan: MultiLegExecutionPlan, leg: Any, identity: Any) -> str:
        intent_parts = (
            plan.group_id, plan.strategy_id, leg.leg_id, identity.instrument_id,
            str(leg.side).upper(), str(int(leg.quantity)), str(leg.position_role),
        )
        if getattr(plan, "attempt_id", None):
            intent_parts += (str(plan.attempt_id),)
        intent = "|".join(intent_parts)
        digest = sha256(intent.encode("utf-8")).hexdigest()[:12]
        return f"{plan.group_id}-{leg.leg_id}-{digest}"

    @staticmethod
    def _execution_fill_reports(report: ExecutionReport) -> tuple[ExecutionReport, ...]:
        fills = tuple(getattr(report, "execution_fills", ()) or ())
        if not fills:
            if report.filled_quantity <= 0:
                return ()
            if not report.execution_id or report.execution_timestamp is None:
                raise RuntimeError("MULTI_LEG_POSITION_PROVENANCE_EXECUTION_REQUIRED")
            if report.fee is None or report.execution_price is None:
                raise RuntimeError("MULTI_LEG_FEE_PROVENANCE_EXECUTION_REQUIRED")
            return (report,)

        if any(
            not fill.execution_id or fill.filled_quantity <= 0
            or fill.execution_price is None or fill.execution_price <= 0
            or fill.execution_timestamp is None or fill.fee is None or fill.fee < 0
            for fill in fills
        ):
            raise RuntimeError("MULTI_LEG_EXECUTION_FILL_EVENT_INVALID")
        execution_ids = [fill.execution_id for fill in fills]
        if len(execution_ids) != len(set(execution_ids)):
            raise RuntimeError("MULTI_LEG_EXECUTION_FILL_ID_DUPLICATE")
        if sum(fill.filled_quantity for fill in fills) != report.filled_quantity:
            raise RuntimeError("MULTI_LEG_EXECUTION_FILL_TOTAL_MISMATCH")
        return tuple(
            replace(
                report,
                execution_id=fill.execution_id,
                filled_quantity=fill.filled_quantity,
                execution_price=fill.execution_price,
                execution_timestamp=fill.execution_timestamp,
                fee=fill.fee,
                execution_fills=(),
            )
            for fill in fills
        )

    def _apply_reconciled_execution(
        self, *, plan: MultiLegExecutionPlan, leg: Any, identity: Any,
        broker_command: BrokerOrderCommand, report: ExecutionReport,
    ) -> None:
        fill_reports = self._execution_fill_reports(report)
        if not fill_reports:
            self.provenance[report.client_order_id] = {
                "strategy_id": plan.strategy_id, "group_id": plan.group_id,
                "leg_id": leg.leg_id, "client_order_id": report.client_order_id,
                "execution_id": "", "instrument_id": identity.instrument_id,
                "symbol": identity.symbol, "expiry": getattr(identity, "expiry", "") or "",
                "option_type": getattr(identity, "option_type", "") or "",
                "strike": str(getattr(identity, "strike", "") or ""),
                "contract_multiplier": str(identity.contract_multiplier),
                "identity_source": identity.identity_source or "",
            }
            return

        from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
        from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter
        leg_position = self.leg_positions.get(identity.instrument_id)
        if leg_position is None:
            leg_position = VirtualPositionAggregate(instrument_id=identity.instrument_id)
            self.leg_positions[identity.instrument_id] = leg_position

        for fill_report in fill_reports:
            execution_id = fill_report.execution_id
            self.execution_legs[execution_id] = {
                "strategy_id": plan.strategy_id, "side": leg.side,
                "position_role": leg.position_role,
                "asset_type": "OPTION" if isinstance(identity, OptionInstrumentIdentity) else "FUTURES",
                "option_type": getattr(identity, "option_type", None),
                "contract_multiplier": identity.contract_multiplier,
            }
            self.provenance[execution_id] = {
                "strategy_id": plan.strategy_id, "group_id": plan.group_id,
                "leg_id": leg.leg_id, "client_order_id": fill_report.client_order_id,
                "execution_id": execution_id, "instrument_id": identity.instrument_id,
                "symbol": identity.symbol, "expiry": getattr(identity, "expiry", "") or "",
                "option_type": getattr(identity, "option_type", "") or "",
                "strike": str(getattr(identity, "strike", "") or ""),
                "contract_multiplier": str(identity.contract_multiplier),
                "identity_source": identity.identity_source or "",
            }
            fingerprint = (
                fill_report.client_order_id, identity.instrument_id, leg.side,
                fill_report.filled_quantity, fill_report.execution_price,
                fill_report.execution_timestamp, fill_report.fee,
                fill_report.group_id, fill_report.leg_id,
            )
            prior_fingerprint = self._applied_execution_fingerprints.get(execution_id)
            if prior_fingerprint is not None:
                if prior_fingerprint != fingerprint:
                    raise RuntimeError("MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED")
                continue

            lot = PositionLotProvenance(
                run_id=self.run_id, instrument_id=identity.instrument_id,
                strategy_id=plan.strategy_id, group_id=plan.group_id,
                leg_id=leg.leg_id, client_order_id=fill_report.client_order_id,
                execution_id=execution_id, side=leg.side,
                opened_quantity=fill_report.filled_quantity,
                remaining_quantity=fill_report.filled_quantity,
                execution_timestamp=fill_report.execution_timestamp,
                instrument_identity=identity,
                contract_multiplier=identity.contract_multiplier,
                identity_source=identity.identity_source or "",
                position_role=PositionRole(leg.position_role),
            )
            self.position_lot_store.apply_execution(lot)
            self.fee_ledger.record(
                Track9FeeRecord(
                    run_id=self.run_id, strategy_id=plan.strategy_id,
                    group_id=plan.group_id, leg_id=leg.leg_id,
                    client_order_id=fill_report.client_order_id,
                    execution_id=execution_id, instrument_id=identity.instrument_id,
                    fee_amount=fill_report.fee,
                    executed_quantity=fill_report.filled_quantity,
                    executed_price=fill_report.execution_price,
                    executed_at=fill_report.execution_timestamp,
                    source="VSSF:CanonicalExecutionReport.fee",
                )
            )
            VirtualPositionFillAdapter(leg_position).apply(broker_command, fill_report)
            self._applied_execution_fingerprints[execution_id] = fingerprint

    def execute(
        self,
        plan: MultiLegExecutionPlan,
        *,
        price: Decimal | None = None,
        group_plan: MultiLegExecutionPlan | None = None,
        reconciled_reports: dict[str, ExecutionReport] | None = None,
        reconciled_commands: dict[str, BrokerOrderCommand] | None = None,
    ) -> MultiLegExecutionResult:
        if group_plan is None:
            group_plan = plan
            if ((plan.strategy_id == "track8_macro_regime_monthly_strangle"
                    and plan.purpose in {"MONTHLY_STRANGLE_ENTRY_CALL", "MONTHLY_STRANGLE_ENTRY_PUT"})
                    or (plan.strategy_id == "track6_daily_tail_insurance"
                        and plan.purpose == "DAILY_TAIL_INSURANCE_ENTRY")):
                prior_group_plan = self._group_plans.get(plan.group_id)
                if prior_group_plan is not None:
                    merged_legs = {leg.leg_id: leg for leg in prior_group_plan.legs}
                    merged_legs.update({leg.leg_id: leg for leg in plan.legs})
                    group_plan = replace(plan, legs=tuple(merged_legs.values()))
                self._group_plans[plan.group_id] = group_plan
        reconciled_reports = dict(reconciled_reports or {})
        reconciled_commands = dict(reconciled_commands or {})
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

        # Resolve and validate every required leg before risk admission or submission.
        # A missing quote/identity on any leg blocks the whole group.
        prepared = []
        seen_leg_ids: set[str] = set()
        account_input = account_snapshot_to_risk_input(account)
        position_input = position_manager_to_risk_input(position)
        for leg in plan.legs:
            if not leg.leg_id or leg.leg_id in seen_leg_ids:
                raise ValueError("MULTI_LEG_UNIQUE_LEG_ID_REQUIRED")
            seen_leg_ids.add(leg.leg_id)
            if leg.side not in {"BUY", "SELL"} or int(leg.quantity) <= 0:
                raise ValueError("MULTI_LEG_SIDE_AND_POSITIVE_QUANTITY_REQUIRED")
            identity = self.identity_for_leg(plan, leg)
            client_order_id = self._client_order_id(plan, leg, identity)
            prior_intent = next((report for report in self.groups.get(group_plan.group_id, ())
                                 if report.client_order_id == client_order_id), None)
            if prior_intent is not None and client_order_id not in reconciled_reports:
                # Existing pending intents are observational unless an authoritative
                # broker query supplied a newer report for reconciliation.
                reports.append(prior_intent)
                continue
            if client_order_id in reconciled_commands:
                broker_command = reconciled_commands[client_order_id]
                canonical = self.command_context.build_command(broker_command)
                prepared.append((leg, identity, client_order_id, broker_command, canonical, Decimal("0"), Decimal("0")))
                continue
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
                if str(identity.instrument_id).startswith("SYNTHETIC_CONTRACT:"):
                    quote = getattr(self.bundle.market, "option_quotes_by_instrument_id", {}).get(identity.instrument_id)
                    if (not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO"
                            or str(quote.get("instrument_id", "")) != identity.instrument_id
                            or str(quote.get("option_type", "")).upper() != identity.option_type
                            or Decimal(str(quote.get("strike", "0"))) != Decimal(str(identity.strike))
                            or str(quote.get("expiry", "")).replace("-", "")[:8] != identity.expiry.replace("-", "")[:8]):
                        quote = None
                else:
                    quote_key = next((key for key in option_quotes if isinstance(key, tuple) and len(key) == 3
                        and str(key[0]).upper() == identity.option_type
                        and float(key[1]) == float(identity.strike)
                        and str(key[2]).replace("-", "")[:8] == identity.expiry.replace("-", "")[:8]), None)
                    quote = option_quotes.get(quote_key)
                authoritative = self.option_master.get_contract_identity(identity.instrument_id)
                if authoritative is None or authoritative.contract_multiplier is None:
                    raise ValueError("MULTI_LEG_AUTHORITATIVE_OPTION_MULTIPLIER_REQUIRED")
                if quote is None:
                    if client_order_id not in reconciled_reports:
                        raise ValueError("MULTI_LEG_GROUP_PREFLIGHT_QUOTE_REQUIRED")
                    # A previously accepted order is reconciled by client ID even
                    # when its latest quote is absent; no new order is submitted.
                    bid = ask = Decimal("0")
                    execution_reference = Decimal(str(leg.requested_price or "0"))
                else:
                    quote_multiplier = quote.get("contract_multiplier")
                    if quote_multiplier is None or Decimal(str(quote_multiplier)) != Decimal(str(authoritative.contract_multiplier)):
                        raise ValueError("MULTI_LEG_OPTION_CONTRACT_MULTIPLIER_MISMATCH")
                    bid = Decimal(str(quote.get("bid", "0")))
                    ask = Decimal(str(quote.get("ask", "0")))
                    execution_reference = ask if leg.side == "BUY" else bid
                    if bid <= 0 or ask <= 0 or ask < bid or execution_reference <= 0:
                        raise ValueError("MULTI_LEG_OPTION_QUOTE_INVALID")
            requested_price = Decimal(str(leg.requested_price)) if leg.requested_price is not None else execution_reference
            broker_command = BrokerOrderCommand(
                client_order_id=client_order_id, instrument_id=identity.instrument_id,
                side=leg.side, quantity=leg.quantity, order_type="LIMIT",
                broker_symbol=identity.symbol, instrument_identity=identity,
                asset_type="FUTURES" if is_futures else "OPTION", requested_price=requested_price,
                strategy_id=plan.strategy_id, order_purpose=plan.purpose or "MULTI_LEG",
                track_id=plan.strategy_id, tag_id=leg.leg_id, group_id=plan.group_id,
                leg_id=leg.leg_id, position_role=leg.position_role,
            )
            canonical = self.command_context.build_command(broker_command)
            if quote is not None:
                vssf.order_book.update_bid_ask(float(bid), float(ask), identity.instrument_id)
            prepared.append((leg, identity, client_order_id, broker_command, canonical, bid, ask))

        new_prepared = [item for item in prepared if item[2] not in reconciled_reports]
        if self.validation_order_gate is not None and new_prepared:
            try:
                self.validation_order_gate(plan, new_prepared)
            except ValueError as exc:
                # Validation-only policy denials are explicit group rejections, not
                # runtime crashes. No Risk/OMS/Router/Broker call is made for any leg.
                reason = str(exc)
                for leg, _identity, client_order_id, _command, _canonical, _bid, _ask in prepared:
                    reports.append(ExecutionReport(
                        client_order_id=client_order_id, broker_order_id=None, execution_id=None,
                        status="REJECTED", filled_quantity=0, remaining_quantity=int(leg.quantity),
                        execution_price=None, execution_timestamp=None, rejected_reason=reason,
                        group_id=plan.group_id, leg_id=leg.leg_id,
                    ))
                merged_reports = self._merge_group_reports(group_plan, reports)
                self.groups[group_plan.group_id] = list(merged_reports)
                result = MultiLegExecutionResult(
                    group_id=plan.group_id, strategy_id=plan.strategy_id,
                    planned_legs=len(group_plan.legs), approved_legs=0, routed_legs=0,
                    filled_legs=0, reports=merged_reports, group_complete=False,
                    pending_legs=0, position_flat=self._position_flat_for_result(group_plan),
                )
                if self.execution_result_callback is not None:
                    self.execution_result_callback(plan, result)
                return result

        # Preflight all legs against one account/position snapshot. No router call is
        # allowed until every leg and aggregate group margin have passed.
        evaluations = []
        for leg, identity, client_order_id, broker_command, canonical, _bid, _ask in prepared:
            if client_order_id in reconciled_reports:
                continue
            adapted = CanonicalRiskCommandAdapter.from_command(canonical)
            admitted, _token, _reason = self.risk_gate.admit_order(adapted, account_input, position_input)
            evaluation = self.risk_gate.last_evaluation_result
            if evaluation is None:
                raise RuntimeError("MULTI_LEG_RISK_RESULT_UNAVAILABLE")
            evaluations.append((leg, identity, client_order_id, broker_command, canonical, evaluation, admitted))
        failed = any(not admitted for *_rest, admitted in evaluations)
        total_required_margin = sum((evaluation.required_margin or Decimal("0") for *_, evaluation, _admitted in evaluations), Decimal("0"))
        config = self.risk_gate.engine.config
        total_balance = Decimal(str(account_input.total_balance))
        used_margin = Decimal(str(account_input.used_margin))
        free_margin = Decimal(str(account_input.free_margin))
        group_margin_ratio = (used_margin + total_required_margin) / total_balance if total_balance > 0 else Decimal("1")
        # Resolve freshness for every leg before any leg can reach the router.
        # Missing provider/evidence is a group-level rejection, never a partial submit.
        freshness_verdict_by_leg: dict[str, FreshnessVerdict] = {}
        freshness_rejection: str | None = None
        for leg, identity, _client_order_id, broker_command, _canonical, _evaluation, _admitted in evaluations:
            try:
                verdict = (
                    self.freshness_verdict_provider(plan, leg, identity, broker_command)
                    if self.freshness_verdict_provider is not None else None
                )
            except Exception as exc:
                verdict = None
                freshness_rejection = freshness_rejection or f"MARKET_DATA_FRESHNESS_PROVIDER_ERROR:{type(exc).__name__}"
            expected_symbol = str(broker_command.broker_symbol or broker_command.instrument_id or "").strip()
            if not admits_freshness_verdict_for_identity(
                verdict, expected_instrument_id=broker_command.instrument_id,
                expected_symbol=expected_symbol,
            ):
                if freshness_rejection is None:
                    if verdict is None or not permits_risk_increasing_order(verdict):
                        freshness_rejection = "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED" if verdict is None else f"MARKET_DATA_FRESHNESS_{verdict.status.value}:{verdict.reason}"
                    elif verdict.instrument_id != broker_command.instrument_id or verdict.symbol != expected_symbol:
                        freshness_rejection = "MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH"
                    else:
                        freshness_rejection = "MARKET_DATA_FRESHNESS_EVIDENCE_REQUIRED"
            else:
                freshness_verdict_by_leg[leg.leg_id] = verdict

        aggregate_rejection = freshness_rejection
        if aggregate_rejection is None and total_required_margin > free_margin:
            aggregate_rejection = "GROUP_INSUFFICIENT_FREE_MARGIN"
        elif aggregate_rejection is None and group_margin_ratio > Decimal(str(config.max_margin_utilization_ratio)):
            aggregate_rejection = "GROUP_MAX_MARGIN_UTILIZATION_EXCEEDED"

        # Strategy 5 diagnostics are best-effort and must never change Risk/order flow.
        if plan.strategy_id == "track5_gap_divergence":
            self._record_strategy5_risk_preflight_diagnostic(
                run_id=self.run_id,
                strategy_id=plan.strategy_id,
                group_id=plan.group_id,
                evaluations=[{
                    "leg_id": leg.leg_id,
                    "client_order_id": client_order_id,
                    "instrument_id": identity.instrument_id,
                    "side": str(leg.side),
                    "quantity": int(leg.quantity),
                    "admitted": bool(admitted),
                    "risk_decision": str(evaluation.decision),
                    "risk_approved": bool(evaluation.is_approved),
                    "rejection_reason": evaluation.rejection_reason,
                    "required_margin": str(evaluation.required_margin),
                    "estimated_margin_ratio": str(evaluation.estimated_margin_ratio),
                } for leg, identity, client_order_id, _command, _canonical, evaluation, admitted in evaluations],
                total_required_margin=total_required_margin,
                total_balance=total_balance,
                used_margin=used_margin,
                free_margin=free_margin,
                max_margin_utilization_ratio=config.max_margin_utilization_ratio,
                group_margin_ratio=group_margin_ratio,
                aggregate_rejection=aggregate_rejection,
                leg_rejected=failed,
            )
        if failed or aggregate_rejection:
            for leg, _identity, client_order_id, _command, _canonical, evaluation, admitted in evaluations:
                reason = self._preflight_rejection_reason(evaluation, admitted, aggregate_rejection)
                final_evaluation = replace(evaluation, is_approved=False, decision="DENY", rejection_reason=reason)
                self.risk_approval_read_model.record(RiskApprovalRecord(plan.strategy_id, plan.group_id, leg.leg_id, client_order_id, final_evaluation))
                reports.append(ExecutionReport(client_order_id, None, None, "REJECTED", 0, leg.quantity, None, None,
                    rejected_reason=reason, group_id=plan.group_id, leg_id=leg.leg_id))
            merged_reports = self._merge_group_reports(group_plan, reports)
            group_legs_list = []
            for group_leg in group_plan.legs:
                identity = self.identity_for_leg(group_plan, group_leg)
                filled_qty = sum(r.filled_quantity for r in merged_reports if r.leg_id == group_leg.leg_id)
                status = (LegStatus.FILLED if filled_qty >= group_leg.quantity else
                          LegStatus.PARTIALLY_FILLED if filled_qty > 0 else
                          LegStatus.REJECTED if any(r.leg_id == group_leg.leg_id and r.status == "REJECTED" for r in merged_reports) else
                          LegStatus.PENDING)
                group_legs_list.append(PositionGroupLeg(group_leg.leg_id, plan.group_id, identity.instrument_id,
                    group_leg.side, group_leg.quantity, identity.contract_multiplier,
                    identity.identity_source or "", status))
            group = PositionGroup(plan.group_id, plan.strategy_id, "MULTI_LEG", tuple(group_legs_list))
            if plan.group_id not in self.position_groups.all(): self.position_groups.register(group)
            else: self.position_groups.replace(group)
            self.groups[plan.group_id] = list(merged_reports)
            result = MultiLegExecutionResult(plan.group_id, plan.strategy_id, len(plan.legs), 0, 0, 0,
                tuple(reports), False, 0, self._position_flat_for_result(group_plan))
            if self.execution_result_callback is not None: self.execution_result_callback(plan, result)
            return result

        for leg, identity, client_order_id, broker_command, canonical, preflight_evaluation, _admitted in evaluations:
            freshness_verdict = freshness_verdict_by_leg[leg.leg_id]
            result = route_from_runtime_authoritative_sources(
                canonical, risk_gate=self.risk_gate,
                context=RiskRouterContext(account_snapshot=account, position_source=position,
                    order_router=self.router, broker_command=broker_command),
                freshness_verdict=freshness_verdict,
            )
            if result.rejection_reason and result.rejection_reason.startswith("MARKET_DATA_FRESHNESS_"):
                risk_evaluation = replace(
                    preflight_evaluation, is_approved=False, decision="DENY",
                    rejection_reason=result.rejection_reason,
                )
            else:
                risk_evaluation = self.risk_gate.last_evaluation_result
                if risk_evaluation is None:
                    raise RuntimeError("MULTI_LEG_RISK_RESULT_UNAVAILABLE")
            self.risk_approval_read_model.record(RiskApprovalRecord(plan.strategy_id, plan.group_id, leg.leg_id, client_order_id, risk_evaluation))
            if not result.routed:
                if result.rejection_reason and result.rejection_reason.startswith("MARKET_DATA_FRESHNESS_"):
                    reports.append(ExecutionReport(
                        client_order_id=client_order_id, broker_order_id=None, execution_id=None,
                        status="REJECTED", filled_quantity=0, remaining_quantity=leg.quantity,
                        execution_price=None, execution_timestamp=None,
                        rejected_reason=result.rejection_reason, group_id=plan.group_id, leg_id=leg.leg_id,
                    ))
                    continue
                raw = self.ack.last_report
                raw_status = str(getattr(raw, "status", "")).strip().upper() if raw is not None else ""
                if raw_status in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
                    reports.append(ExecutionReport(
                        client_order_id=client_order_id,
                        broker_order_id=getattr(raw, "broker_order_id", None),
                        execution_id=getattr(raw, "execution_id", None),
                        status=raw_status,
                        filled_quantity=int(getattr(raw, "filled_quantity", 0) or 0),
                        remaining_quantity=int(getattr(raw, "remaining_quantity", leg.quantity) or 0),
                        execution_price=getattr(raw, "execution_price", None),
                        execution_timestamp=getattr(raw, "execution_timestamp", None),
                        fee=getattr(raw, "fee", None),
                        source_freshness=getattr(raw, "source_freshness", None),
                        rejected_reason=getattr(raw, "rejected_reason", None) or "VIRTUAL_ORDER_STATUS_RECONCILIATION_REQUIRED",
                        submitted_at=getattr(raw, "submitted_at", None),
                        lifecycle_reason=getattr(raw, "lifecycle_reason", None),
                        group_id=plan.group_id,
                        leg_id=leg.leg_id,
                    ))
                else:
                    reports.append(ExecutionReport(client_order_id, None, None, "REJECTED", 0, leg.quantity, None, None,
                        rejected_reason=getattr(risk_evaluation, "rejection_reason", None) or "RISK_REJECTED_AFTER_PREFLIGHT",
                        group_id=plan.group_id, leg_id=leg.leg_id))
                continue
            approved += 1
            routed += 1
            raw = self.ack.last_report
            if raw is None:
                reports.append(ExecutionReport(client_order_id, None, None, "UNKNOWN", 0, leg.quantity, None, None,
                    rejected_reason="VIRTUAL_EXECUTION_REPORT_UNAVAILABLE", group_id=plan.group_id, leg_id=leg.leg_id))
                continue
            report = ExecutionReport(
                client_order_id=raw.client_order_id,
                broker_order_id=getattr(raw, "broker_order_id", None) or (f"VIRTUAL-{raw.execution_id}" if raw.execution_id else None),
                execution_id=raw.execution_id, status=str(raw.status).upper(),
                filled_quantity=int(raw.filled_quantity), remaining_quantity=int(raw.remaining_quantity),
                execution_price=raw.execution_price, execution_timestamp=raw.execution_timestamp,
                fee=(Decimal(str(raw.fee)) if getattr(raw, "fee", None) is not None else None),
                source_freshness=getattr(raw, "source_freshness", None),
                rejected_reason=getattr(raw, "rejected_reason", None),
                submitted_at=getattr(raw, "submitted_at", None),
                lifecycle_reason=getattr(raw, "lifecycle_reason", None),
                execution_fills=tuple(getattr(raw, "execution_fills", ()) or ()),
                group_id=plan.group_id, leg_id=leg.leg_id,
            )
            reports.append(report)
            if report.status in {"NEW", "PARTIALLY_FILLED", "UNKNOWN", "RECONCILIATION_REQUIRED"} and report.remaining_quantity > 0:
                self.pending_legs[client_order_id] = (group_plan, leg, broker_command)
            else:
                self.pending_legs.pop(client_order_id, None)
            if report.status == "FILLED" and report.filled_quantity <= 0:
                raise RuntimeError("MULTI_LEG_FILLED_QUANTITY_REQUIRED")
            self._apply_reconciled_execution(
                plan=plan, leg=leg, identity=identity,
                broker_command=broker_command, report=report,
            )
            if report.filled_quantity > 0:
                filled += report.filled_quantity

        for leg, identity, client_order_id, broker_command, _canonical, _bid, _ask in prepared:
            raw = reconciled_reports.get(client_order_id)
            if raw is None:
                continue
            report = replace(
                raw, group_id=plan.group_id, leg_id=leg.leg_id,
                client_order_id=client_order_id,
            )
            if report.status == "FILLED" and report.filled_quantity <= 0:
                raise RuntimeError("MULTI_LEG_FILLED_QUANTITY_REQUIRED")
            reports.append(report)
            self._apply_reconciled_execution(
                plan=plan, leg=leg, identity=identity,
                broker_command=broker_command, report=report,
            )
            if report.status in {"NEW", "PARTIALLY_FILLED", "UNKNOWN", "RECONCILIATION_REQUIRED"} and report.remaining_quantity > 0:
                self.pending_legs[client_order_id] = (group_plan, leg, broker_command)
            else:
                self.pending_legs.pop(client_order_id, None)
            if report.filled_quantity > 0:
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
                    if sum(r.filled_quantity for r in merged_reports if r.leg_id == leg.leg_id) >= leg.quantity
                    else LegStatus.PARTIALLY_FILLED
                    if sum(r.filled_quantity for r in merged_reports if r.leg_id == leg.leg_id) > 0
                    else LegStatus.PENDING
                    if (
                        any(r.leg_id == leg.leg_id and r.status in {"NEW", "PARTIALLY_FILLED"} for r in merged_reports)
                        or self._client_order_id(group_plan, leg, self.identity_for_leg(group_plan, leg)) in self.pending_legs
                    )
                    else LegStatus.REJECTED
                ),
            ) for leg in group_plan.legs
        )
        terminal_execution = self._is_terminal_execution_plan(plan)
        existing_group = self.position_groups.all().get(group_plan.group_id)
        if terminal_execution and existing_group is None:
            raise ValueError("POSITION_GROUP_TERMINAL_ENTRY_GROUP_REQUIRED")
        group = existing_group if terminal_execution else PositionGroup(
            group_plan.group_id, group_plan.strategy_id, "MULTI_LEG", group_legs
        )
        if plan.group_id not in self.position_groups.all():
            self.position_groups.register(group)
        else:
            self.position_groups.replace(group)
        if terminal_execution:
            self.position_groups.replace(existing_group)
        current_futures = float(getattr(self.bundle.market, "futures_price", price))
        option_quotes = getattr(self.bundle.market, "option_quotes", {})
        option_quotes_by_id = getattr(self.bundle.market, "option_quotes_by_instrument_id", {})
        pnl_legs = []
        for leg in group_plan.legs:
            leg_reports = [r for r in merged_reports if r.leg_id == leg.leg_id and r.filled_quantity > 0 and r.execution_price is not None]
            if not leg_reports:
                continue
            rep = leg_reports[-1]
            total_leg_fill = sum(r.filled_quantity for r in leg_reports)
            weighted_fill_value = sum((Decimal(str(r.execution_price)) * r.filled_quantity for r in leg_reports), Decimal("0"))
            average_fill_price = weighted_fill_value / Decimal(total_leg_fill)
            execution_ids = tuple(dict.fromkeys(
                fill.execution_id
                for item in leg_reports
                for fill in (tuple(getattr(item, "execution_fills", ()) or ()) or ())
                if fill.execution_id
            )) or tuple(dict.fromkeys(
                item.execution_id for item in leg_reports if item.execution_id
            ))
            identity = self.identity_for_leg(group_plan, leg)
            if isinstance(identity, FuturesInstrumentIdentity):
                current = current_futures
            else:
                if str(identity.instrument_id).startswith("SYNTHETIC_CONTRACT:"):
                    quote = option_quotes_by_id.get(identity.instrument_id)
                    if not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
                        quote = None
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
                    leg.leg_id, group_plan.group_id, identity.instrument_id, total_leg_fill,
                    multiplier, identity.identity_source or "",
                    float(average_fill_price), current, float(leg_unrealized),
                    self.run_id, rep.client_order_id,
                    rep.execution_id or (execution_ids[0] if len(execution_ids) == 1 else ""),
                    execution_ids,
                )
            )
        if terminal_execution:
            # Execution changes positions immediately; refresh the remaining account
            # marks before comparing the terminal group snapshot with account PnL.
            for entry_leg in existing_group.legs:
                instrument_id = entry_leg.instrument_id
                if instrument_id not in vssf.account.positions:
                    continue
                identity = self.option_master.get_contract_identity(instrument_id)
                if identity is None:
                    raise ValueError(f"POSITION_GROUP_TERMINAL_OPTION_IDENTITY_REQUIRED:{instrument_id}")
                if str(instrument_id).startswith("SYNTHETIC_CONTRACT:"):
                    quote = option_quotes_by_id.get(instrument_id)
                    if not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
                        quote = None
                else:
                    quote_key = next((
                        key for key in option_quotes
                        if isinstance(key, tuple) and len(key) == 3
                        and str(key[0]).upper() == str(identity.option_type).upper()
                        and Decimal(str(key[1])) == Decimal(str(identity.strike))
                        and str(key[2]).replace("-", "")[:8] == str(identity.expiry).replace("-", "")[:8]
                    ), None)
                    quote = option_quotes.get(quote_key) if quote_key is not None else None
                if not isinstance(quote, dict) or quote.get("last") is None:
                    raise ValueError(f"POSITION_GROUP_TERMINAL_ACCOUNT_MARK_REQUIRED:{instrument_id}")
                vssf.account.update_tick_price(
                    quote["last"], instrument_id=instrument_id
                )
        realized_after = Decimal(str(vssf.account.realized_pnl))
        realized_pnl = realized_after - realized_before
        unrealized_pnl = sum(Decimal(str(x.unrealized_pnl)) for x in pnl_legs)
        total_pnl = realized_pnl + unrealized_pnl
        if terminal_execution:
            previous_snapshot = self.position_groups.snapshot(group_plan.group_id)
            if previous_snapshot is None:
                raise ValueError("POSITION_GROUP_TERMINAL_ENTRY_SNAPSHOT_REQUIRED")
            snapshot = self._build_terminal_position_group_snapshot(
                plan=plan, previous=previous_snapshot,
                realized_delta=realized_pnl, reports=tuple(reports),
            )
        else:
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
            group_complete=(all(
                sum(r.filled_quantity for r in merged_reports if r.leg_id == leg.leg_id) >= leg.quantity
                for leg in group_plan.legs
            )),
            pending_legs=pending_legs + sum(
                1 for leg in group_plan.legs
                if self._client_order_id(group_plan, leg, self.identity_for_leg(group_plan, leg)) in self.pending_legs
                and not any(r.leg_id == leg.leg_id and r.status == "FILLED" for r in merged_reports)
            ),
            position_flat=self._position_flat_for_result(group_plan),
        )
        if self.execution_result_callback is not None:
            self.execution_result_callback(plan, result)
        return result

    def cancel_pending_order(self, client_order_id: str) -> MultiLegExecutionResult:
        pending = self.pending_legs.get(client_order_id)
        if pending is None:
            raise ValueError("VIRTUAL_PENDING_ORDER_NOT_FOUND")
        group_plan, leg, broker_command = pending
        cancel = getattr(self.ack.broker, "cancel", None)
        query = getattr(self.ack.broker, "query", None)
        if not callable(cancel) or not callable(query):
            raise RuntimeError("VIRTUAL_CANCEL_QUERY_PORT_REQUIRED")
        cancel(client_order_id)
        confirmed = query(client_order_id)
        status = str(getattr(confirmed, "status", "")).upper() if confirmed is not None else ""
        if status not in {"CANCELLED", "FILLED", "REJECTED"}:
            raise RuntimeError("VIRTUAL_CANCEL_TERMINAL_RECONCILIATION_REQUIRED")
        single_plan = MultiLegExecutionPlan(
            group_id=group_plan.group_id, strategy_id=group_plan.strategy_id,
            purpose=group_plan.purpose, legs=(leg,), attempt_id=group_plan.attempt_id,
        )
        result = self.execute(
            single_plan, group_plan=group_plan,
            reconciled_reports={client_order_id: confirmed},
            reconciled_commands={client_order_id: broker_command},
        )
        return result

    def process_pending_quotes(self) -> tuple[MultiLegExecutionResult, ...]:
        """Reconcile already-routed VSSF orders after each Virtual market event."""
        completed: list[MultiLegExecutionResult] = []
        query = getattr(self.ack.broker, "query", None)
        if not callable(query):
            return ()
        for client_order_id, (group_plan, leg, broker_command) in tuple(self.pending_legs.items()):
            try:
                latest = query(client_order_id)
            except Exception:
                # Query failure is not evidence of cancellation or rejection.
                continue
            if latest is None:
                continue
            prior = next(
                (
                    report for report in self.groups.get(group_plan.group_id, ())
                    if report.client_order_id == client_order_id
                ),
                None,
            )
            if prior is not None and (
                str(getattr(prior.status, "value", prior.status)).upper()
                == str(getattr(latest.status, "value", latest.status)).upper()
                and int(prior.filled_quantity) == int(latest.filled_quantity)
                and int(prior.remaining_quantity) == int(latest.remaining_quantity)
                and prior.execution_id == latest.execution_id
                and prior.execution_price == latest.execution_price
                and prior.fee == latest.fee
                and prior.submitted_at == latest.submitted_at
                and prior.lifecycle_reason == latest.lifecycle_reason
                and tuple(getattr(prior, "execution_fills", ()) or ())
                == tuple(getattr(latest, "execution_fills", ()) or ())
            ):
                continue
            single_plan = MultiLegExecutionPlan(
                group_id=group_plan.group_id,
                strategy_id=group_plan.strategy_id,
                purpose=group_plan.purpose,
                legs=(leg,),
                attempt_id=group_plan.attempt_id,
            )
            result = self.execute(
                single_plan,
                group_plan=group_plan,
                reconciled_reports={client_order_id: latest},
                reconciled_commands={client_order_id: broker_command},
            )
            completed.append(result)
        return tuple(completed)

    def _merge_group_reports(
        self, group_plan: MultiLegExecutionPlan, new_reports: Sequence[ExecutionReport]
    ) -> tuple[ExecutionReport, ...]:
        """Keep the latest report for every leg, including fills completed after deferral."""
        existing = list(self.groups.get(group_plan.group_id, ()))
        for report in new_reports:
            if not report.leg_id:
                continue
            if report.execution_id and getattr(report, "client_order_id", None):
                match = next((i for i, prior in enumerate(existing)
                              if prior.leg_id == report.leg_id
                              and prior.execution_id == report.execution_id
                              and getattr(prior, "client_order_id", None) == report.client_order_id), None)
                if match is None:
                    existing.append(report)
                else:
                    existing[match] = report
            else:
                client_order_id = getattr(report, "client_order_id", None)
                if client_order_id:
                    match = next((i for i, prior in enumerate(existing)
                                  if prior.leg_id == report.leg_id
                                  and getattr(prior, "client_order_id", None) == client_order_id), None)
                    if match is None:
                        existing.append(report)
                    else:
                        existing[match] = report
                else:
                    # Compatibility with legacy reports that have only leg identity.
                    existing = [prior for prior in existing if prior.leg_id != report.leg_id]
                    existing.append(report)
        order = {leg.leg_id: i for i, leg in enumerate(group_plan.legs)}
        return tuple(sorted(existing, key=lambda report: (order.get(report.leg_id, len(order)),
                         str(getattr(report, "execution_timestamp", "") or ""),
                         str(getattr(report, "execution_id", "") or ""))))

    def group_reports(self, group_id: str) -> tuple[ExecutionReport, ...]:
        return tuple(self.groups.get(group_id, ()))

    def risk_approvals(self, group_id: str) -> tuple[RiskApprovalRecord, ...]:
        return self.risk_approval_read_model.for_group(group_id)
