"""Validation-only option expiry cash settlement for synthetic Virtual runs.

This module deliberately does not claim an authoritative KIS/exchange settlement
price, contract identity, multiplier or brokerage schedule. It applies an
explicit, manifest-bound benchmark to a validation-only Virtual account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import re
from types import SimpleNamespace
from typing import Any, Mapping

from contracts.option_expiry import require_exact_option_expiry
from contracts.position_provenance import PositionLotProvenance
from contracts.types import OptionInstrumentIdentity

STRATEGY_ID = "track8_macro_regime_monthly_strangle"
SYNTHETIC_PREFIX = "SYNTHETIC_CONTRACT:"


@dataclass(frozen=True)
class ValidationOnlyExpirySettlementProfile:
    profile_id: str
    contract_multiplier: Decimal
    commission_per_contract_per_side_krw: Decimal
    currency: str
    rounding: str
    settlement_price_source: str
    settlement_price_by_scenario: Mapping[str, str]
    profile_sha256: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ValidationOnlyExpirySettlementProfile":
        if (
            payload.get("schema_version") != "q25-s8-validation-only-expiry-profile-v1"
            or payload.get("validation_only") is not True
            or payload.get("runtime_eligible") is not False
            or payload.get("production_runtime_eligible") is not False
            or payload.get("allow_kis_api") is not False
            or payload.get("allow_live_orders") is not False
            or payload.get("allow_real_account") is not False
            or payload.get("provenance") != "SYNTHETIC_VALIDATION_BENCHMARK"
        ):
            raise ValueError("S8_EXPIRY_VALIDATION_PROFILE_BOUNDARY_INVALID")
        multiplier = Decimal(str(payload.get("contract_multiplier", "0")))
        commission = Decimal(str(payload.get("commission_per_contract_per_side_krw", "-1")))
        if multiplier != Decimal("250000"):
            raise ValueError("S8_EXPIRY_VALIDATION_STANDARD_MULTIPLIER_MISMATCH")
        if commission <= 0 or payload.get("currency") != "KRW":
            raise ValueError("S8_EXPIRY_VALIDATION_FEE_PROFILE_INVALID")
        if payload.get("rounding") != "ROUND_HALF_UP_TO_WON":
            raise ValueError("S8_EXPIRY_VALIDATION_ROUNDING_POLICY_INVALID")
        if payload.get("settlement_price_source") != "SYNTHETIC_SCENARIO_EXPIRY_FIXTURE":
            raise ValueError("S8_EXPIRY_VALIDATION_SETTLEMENT_SOURCE_INVALID")
        prices = payload.get("settlement_price_by_scenario")
        if not isinstance(prices, dict) or not prices:
            raise ValueError("S8_EXPIRY_VALIDATION_SCENARIO_PRICE_REQUIRED")
        if any(Decimal(str(value)) < 0 for value in prices.values()):
            raise ValueError("S8_EXPIRY_VALIDATION_SETTLEMENT_PRICE_INVALID")
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return cls(
            profile_id=str(payload["profile_id"]),
            contract_multiplier=multiplier,
            commission_per_contract_per_side_krw=commission,
            currency="KRW",
            rounding=str(payload["rounding"]),
            settlement_price_source=str(payload["settlement_price_source"]),
            settlement_price_by_scenario={str(k): str(v) for k, v in prices.items()},
            profile_sha256=digest,
        )


class ValidationOnlyOptionExpiryCashSettlementAdapter:
    """Apply synthetic intrinsic payoff to a bound S8 Virtual group exactly once."""

    def __init__(self, *, manifest: Mapping[str, Any], profile: ValidationOnlyExpirySettlementProfile):
        if (
            manifest.get("schema_version") != "q25-a2-1-s6-syn-evt-manifest-v1"
            or manifest.get("source_type") != "DERIVED_SCENARIO"
            or manifest.get("provenance") != "DERIVED_SCENARIO"
            or manifest.get("synthetic") is not True
            or manifest.get("validation_only") is not True
            or manifest.get("runtime_eligible") is not False
            or manifest.get("production_runtime_eligible") is not False
            or manifest.get("expiry_is_authoritative") is not False
            or manifest.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
            or manifest.get("contract_identity_authority") != "SYNTHETIC_ONLY"
            or manifest.get("strategy_id") != "strategy8_monthly"
        ):
            raise ValueError("S8_EXPIRY_VALIDATION_MANIFEST_BOUNDARY_INVALID")
        self.manifest = dict(manifest)
        self.profile = profile
        self.scenario_id = str(manifest["scenario_id"])
        if self.scenario_id not in profile.settlement_price_by_scenario:
            raise ValueError("S8_EXPIRY_VALIDATION_SCENARIO_PROFILE_MISMATCH")
        self._settlements: dict[str, tuple[str, dict[str, Any]]] = {}

    @staticmethod
    def _round_won(value: Decimal) -> Decimal:
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def settle_group(
        self,
        *,
        bridge: Any,
        group_id: str,
        settlement_id: str,
        settlement_date: str,
        underlying_settlement_price: Decimal | str,
        settlement_source_payload: Mapping[str, Any],
        settlement_source_sha256: str,
    ) -> dict[str, Any]:
        expiry = require_exact_option_expiry(settlement_date)
        price = Decimal(str(underlying_settlement_price))
        if price < 0:
            raise ValueError("S8_EXPIRY_VALIDATION_SETTLEMENT_PRICE_INVALID")
        if not re.fullmatch(r"[0-9a-f]{64}", str(settlement_source_sha256)):
            raise ValueError("S8_EXPIRY_VALIDATION_SOURCE_HASH_REQUIRED")
        expected_source_payload = {
            "scenario_id": self.scenario_id,
            "expiry": expiry,
            "underlying_settlement_price": str(price),
            "source": self.profile.settlement_price_source,
            "profile_sha256": self.profile.profile_sha256,
        }
        if dict(settlement_source_payload) != expected_source_payload:
            raise ValueError("S8_EXPIRY_VALIDATION_SOURCE_PAYLOAD_MISMATCH")
        computed_source_hash = sha256(
            json.dumps(expected_source_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if computed_source_hash != settlement_source_sha256:
            raise ValueError("S8_EXPIRY_VALIDATION_SOURCE_HASH_MISMATCH")
        if not settlement_id.strip():
            raise ValueError("S8_EXPIRY_VALIDATION_SETTLEMENT_ID_REQUIRED")
        fingerprint_payload = {
            "scenario_id": self.scenario_id,
            "group_id": group_id,
            "expiry": expiry,
            "underlying_settlement_price": str(price),
            "settlement_source_sha256": settlement_source_sha256,
            "profile_sha256": self.profile.profile_sha256,
        }
        fingerprint = sha256(json.dumps(fingerprint_payload, sort_keys=True).encode()).hexdigest()
        prior = self._settlements.get(settlement_id)
        if prior is not None:
            if prior[0] != fingerprint:
                raise ValueError("S8_EXPIRY_VALIDATION_DUPLICATE_SETTLEMENT_CONFLICT")
            return prior[1]

        group = bridge.position_groups.get(group_id)
        previous_snapshot = bridge.position_groups.snapshot(group_id)
        if group is None or previous_snapshot is None:
            raise ValueError("S8_EXPIRY_VALIDATION_POSITION_GROUP_REQUIRED")
        if group.strategy_id != STRATEGY_ID:
            raise ValueError("S8_EXPIRY_VALIDATION_STRATEGY_SCOPE_INVALID")

        lots = tuple(
            lot for lot in bridge.position_lot_store.open_lots()
            if lot.run_id == bridge.run_id
            and lot.strategy_id == STRATEGY_ID
            and lot.group_id == group_id
            and lot.remaining_quantity > 0
        )
        if not lots:
            raise ValueError("S8_EXPIRY_VALIDATION_OPEN_LOTS_REQUIRED")

        vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
        account = vssf.account
        entry_records = {
            record.execution_id: record
            for record in bridge.fee_ledger.snapshot(run_id=bridge.run_id)
        }
        group_instruments = {leg.instrument_id for leg in group.legs}
        lot_quantities: dict[str, int] = {}
        for lot in lots:
            lot_quantities[lot.instrument_id] = lot_quantities.get(lot.instrument_id, 0) + int(lot.remaining_quantity)
        for instrument_id in group_instruments:
            account_position = account.positions.get(instrument_id)
            account_qty = int(Decimal(str(account_position.get("qty", 0)))) if account_position else 0
            if account_qty != lot_quantities.get(instrument_id, 0):
                raise ValueError("S8_EXPIRY_VALIDATION_PRE_SETTLEMENT_QUANTITY_MISMATCH")

        prepared: list[dict[str, Any]] = []
        total_entry_fee = Decimal("0")
        total_expiry_fee = Decimal("0")
        gross_expected = Decimal("0")
        for lot in lots:
            identity = lot.instrument_identity
            if not isinstance(identity, OptionInstrumentIdentity):
                raise ValueError("S8_EXPIRY_VALIDATION_OPTION_IDENTITY_REQUIRED")
            if (
                not lot.instrument_id.startswith(SYNTHETIC_PREFIX)
                or identity.instrument_id != lot.instrument_id
                or require_exact_option_expiry(str(identity.expiry)) != expiry
                or identity.option_type not in {"CALL", "PUT"}
                or identity.strike is None
                or Decimal(str(identity.contract_multiplier)) != self.profile.contract_multiplier
                or Decimal(str(lot.contract_multiplier)) != self.profile.contract_multiplier
                or lot.side not in {"BUY", "SELL"}
            ):
                raise ValueError("S8_EXPIRY_VALIDATION_LOT_IDENTITY_OR_MULTIPLIER_INVALID")
            entry = entry_records.get(lot.execution_id)
            if entry is None or entry.instrument_id != lot.instrument_id or entry.executed_quantity < lot.remaining_quantity:
                raise ValueError("S8_EXPIRY_VALIDATION_ENTRY_FILL_PROVENANCE_REQUIRED")
            entry_price = Decimal(str(entry.executed_price))
            strike = Decimal(str(identity.strike))
            intrinsic = (
                max(Decimal("0"), price - strike)
                if identity.option_type == "CALL"
                else max(Decimal("0"), strike - price)
            )
            sign = Decimal("1") if lot.side == "BUY" else Decimal("-1")
            quantity = Decimal(str(lot.remaining_quantity))
            multiplier = self.profile.contract_multiplier
            payoff = self._round_won(intrinsic * quantity * multiplier * sign)
            premium_cashflow = self._round_won(-entry_price * quantity * multiplier * sign)
            gross = payoff + premium_cashflow
            entry_fee = self.profile.commission_per_contract_per_side_krw * quantity
            expiry_fee = self.profile.commission_per_contract_per_side_krw * quantity
            total_entry_fee += entry_fee
            total_expiry_fee += expiry_fee
            gross_expected += gross
            prepared.append({
                "lot": lot,
                "identity": identity,
                "entry_price": entry_price,
                "intrinsic_value_points": intrinsic,
                "signed_cash_payoff_krw": payoff,
                "entry_premium_cashflow_krw": premium_cashflow,
                "gross_realized_pnl_krw": gross,
                "entry_commission_krw": entry_fee,
                "expiry_commission_krw": expiry_fee,
                "settlement_execution_id": f"{settlement_id}:{lot.leg_id}:{lot.execution_id}",
            })

        # Apply only after every lot, source and pre-settlement quantity passed validation.
        from datetime import time
        from zoneinfo import ZoneInfo
        # Keep the validation timestamp deterministic and KST-aware.
        settlement_timestamp = datetime.combine(
            datetime.strptime(expiry, "%Y%m%d").date(),
            time(15, 45),
            tzinfo=ZoneInfo("Asia/Seoul"),
        )
        reports = []
        for item in prepared:
            lot = item["lot"]
            identity = item["identity"]
            close_side = "SELL" if lot.side == "BUY" else "BUY"
            settlement_execution_id = item["settlement_execution_id"]
            report = SimpleNamespace(
                symbol=lot.instrument_id,
                side=close_side,
                executed_qty=int(lot.remaining_quantity),
                executed_price=float(item["intrinsic_value_points"]),
                fee=0.0,
                exec_id=settlement_execution_id,
            )
            account.apply_execution(report)
            close_lot = PositionLotProvenance(
                run_id=lot.run_id,
                instrument_id=lot.instrument_id,
                strategy_id=lot.strategy_id,
                group_id=lot.group_id,
                leg_id=lot.leg_id,
                client_order_id=f"EXPIRY:{settlement_id}:{lot.leg_id}",
                execution_id=settlement_execution_id,
                side=close_side,
                opened_quantity=int(lot.remaining_quantity),
                remaining_quantity=int(lot.remaining_quantity),
                execution_timestamp=settlement_timestamp,
                instrument_identity=identity,
                contract_multiplier=self.profile.contract_multiplier,
                identity_source=lot.identity_source,
                position_role=lot.position_role,
            )
            bridge.position_lot_store.apply_execution(close_lot)
            bridge.provenance[settlement_execution_id] = {
                "instrument_id": lot.instrument_id,
                "group_id": group_id,
                "leg_id": lot.leg_id,
                "settlement_id": settlement_id,
            }
            reports.append(SimpleNamespace(
                execution_id=settlement_execution_id,
                filled_quantity=int(lot.remaining_quantity),
                execution_price=Decimal(str(item["intrinsic_value_points"])),
            ))

        total_fees = self._round_won(total_entry_fee + total_expiry_fee)
        account.balance -= total_fees
        account.update_tick_price(Decimal("0"))
        realized_delta = Decimal(str(account.realized_pnl)) - Decimal(str(previous_snapshot.realized_pnl))
        if realized_delta != self._round_won(gross_expected):
            raise ValueError(
                f"S8_EXPIRY_VALIDATION_REALIZED_PNL_MISMATCH:{realized_delta}:{gross_expected}"
            )
        plan = SimpleNamespace(group_id=group_id, strategy_id=STRATEGY_ID)
        updated_snapshot = bridge._build_terminal_position_group_snapshot(
            plan=plan,
            previous=previous_snapshot,
            realized_delta=realized_delta,
            reports=tuple(reports),
        )
        bridge.position_groups.update_snapshot(updated_snapshot)
        flat = bridge._position_flat_for_plan(plan)
        if not flat or any(leg.quantity != 0 for leg in updated_snapshot.legs):
            raise ValueError("S8_EXPIRY_VALIDATION_FLAT_STATE_RECONCILIATION_FAILED")
        if Decimal(str(account.unrealized_pnl)) != 0 or Decimal(str(updated_snapshot.unrealized_pnl)) != 0:
            raise ValueError("S8_EXPIRY_VALIDATION_UNREALIZED_PNL_NOT_ZERO")

        result = {
            "status": "SETTLED_VALIDATION_ONLY",
            "authority": "NON_AUTHORITATIVE_SYNTHETIC",
            "settlement_id": settlement_id,
            "scenario_id": self.scenario_id,
            "group_id": group_id,
            "expiry": expiry,
            "settlement_date": expiry,
            "underlying_settlement_price": str(price),
            "settlement_source": self.profile.settlement_price_source,
            "settlement_source_sha256": settlement_source_sha256,
            "profile_id": self.profile.profile_id,
            "profile_sha256": self.profile.profile_sha256,
            "currency": self.profile.currency,
            "contract_multiplier": str(self.profile.contract_multiplier),
            "commission_per_contract_per_side_krw": str(self.profile.commission_per_contract_per_side_krw),
            "settled_lots": [{
                "instrument_id": item["lot"].instrument_id,
                "leg_id": item["lot"].leg_id,
                "option_type": item["identity"].option_type,
                "strike": str(item["identity"].strike),
                "side": item["lot"].side,
                "quantity": int(item["lot"].remaining_quantity),
                "entry_price": str(item["entry_price"]),
                "intrinsic_value_points": str(item["intrinsic_value_points"]),
                "signed_cash_payoff_krw": str(item["signed_cash_payoff_krw"]),
                "entry_premium_cashflow_krw": str(item["entry_premium_cashflow_krw"]),
                "gross_realized_pnl_krw": str(item["gross_realized_pnl_krw"]),
                "entry_commission_krw": str(item["entry_commission_krw"]),
                "expiry_commission_krw": str(item["expiry_commission_krw"]),
                "settlement_execution_id": item["settlement_execution_id"],
            } for item in prepared],
            "gross_realized_pnl_krw": str(self._round_won(gross_expected)),
            "entry_commission_krw": str(self._round_won(total_entry_fee)),
            "expiry_commission_krw": str(self._round_won(total_expiry_fee)),
            "total_commission_krw": str(total_fees),
            "net_realized_pnl_krw": str(self._round_won(gross_expected - total_fees)),
            "account_realized_pnl_delta_krw": str(realized_delta),
            "account_unrealized_pnl_after_krw": str(account.unrealized_pnl),
            "group_realized_pnl_after_krw": str(updated_snapshot.realized_pnl),
            "group_unrealized_pnl_after_krw": str(updated_snapshot.unrealized_pnl),
            "position_lots_remaining": len(bridge.position_lot_store.open_lots()),
            "account_positions_remaining": len(account.positions),
            "group_leg_quantities_after": [int(leg.quantity) for leg in updated_snapshot.legs],
            "flat_state_reconciliation": "PASS",
            "realized_pnl_reconciliation": "PASS",
            "commission_basis": "VALIDATION_BENCHMARK_NOT_ACTUAL_BROKER_FEE",
            "production_authority": "NOT_GRANTED",
        }
        self._settlements[settlement_id] = (fingerprint, result)
        return result
