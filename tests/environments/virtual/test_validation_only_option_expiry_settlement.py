from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity
from core.oms.position_group import (
    LegStatus, PositionGroup, PositionGroupLeg, PositionGroupLegPnL,
    PositionGroupRegistry, PositionGroupSnapshot,
)
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
from environments.virtual.validation_only_option_expiry_settlement import (
    ValidationOnlyExpirySettlementProfile,
    ValidationOnlyOptionExpiryCashSettlementAdapter,
)

PROFILE_PATH = Path("config/validation_only/q25_s8_v3/expiry_settlement_profile_v1.json")
PROFILE_PAYLOAD = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
PROFILE = ValidationOnlyExpirySettlementProfile.from_mapping(PROFILE_PAYLOAD)
STRATEGY = "track8_macro_regime_monthly_strangle"
RUN_ID = "S8-EXPIRY-TEST-RUN"
GROUP_ID = "S8-EXPIRY-TEST-GROUP"
EXPIRY = "20261119"


def _make_bridge(*, settlement_price="505", put_strike="500", call_strike="500"):
    account = PaperTradingAccount(25_000_000)
    lot_store = VirtualPositionLotStore()
    fee_ledger = VirtualTrack9FeeLedger()
    group_legs = []
    snapshot_legs = []
    for leg_id, option_type, strike, entry_price in (
        ("call", "CALL", call_strike, "2"),
        ("put", "PUT", put_strike, "3"),
    ):
        instrument_id = f"SYNTHETIC_CONTRACT:TEST:{EXPIRY}:{option_type}:{strike}"
        identity = OptionInstrumentIdentity(
            instrument_id=instrument_id, symbol=instrument_id, expiry=EXPIRY,
            option_type=option_type, strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
            identity_source="SYNTHETIC_VALIDATION_ONLY",
        )
        execution_id = f"ENTRY-{leg_id.upper()}"
        account.apply_execution(SimpleNamespace(
            symbol=instrument_id, side="BUY", executed_qty=1,
            executed_price=float(entry_price), fee=0, exec_id=execution_id,
        ))
        lot_store.apply_execution(PositionLotProvenance(
            run_id=RUN_ID, instrument_id=instrument_id, strategy_id=STRATEGY,
            group_id=GROUP_ID, leg_id=leg_id, client_order_id=f"ORDER-{leg_id}",
            execution_id=execution_id, side="BUY", opened_quantity=1,
            remaining_quantity=1, execution_timestamp=datetime(2026, 11, 2),
            instrument_identity=identity, contract_multiplier=Decimal("250000"),
            identity_source="SYNTHETIC_VALIDATION_ONLY", position_role=PositionRole.NONE,
        ))
        fee_ledger.record(Track9FeeRecord(
            run_id=RUN_ID, strategy_id=STRATEGY, group_id=GROUP_ID, leg_id=leg_id,
            client_order_id=f"ORDER-{leg_id}", execution_id=execution_id,
            instrument_id=instrument_id, fee_amount=Decimal("0"),
            executed_quantity=1, executed_price=Decimal(entry_price),
            executed_at=datetime(2026, 11, 2), source="VSSF:CanonicalExecutionReport.fee",
        ))
        group_legs.append(PositionGroupLeg(
            leg_id, GROUP_ID, instrument_id, "BUY", 1, Decimal("250000"),
            "SYNTHETIC_VALIDATION_ONLY", LegStatus.FILLED,
        ))
        snapshot_legs.append(PositionGroupLegPnL(
            leg_id, GROUP_ID, instrument_id, 1, Decimal("250000"),
            "SYNTHETIC_VALIDATION_ONLY", float(entry_price), float(entry_price),
            0.0, RUN_ID, f"ORDER-{leg_id}", execution_id, (execution_id,),
        ))
    registry = PositionGroupRegistry()
    registry.register(PositionGroup(GROUP_ID, STRATEGY, "MULTI_LEG", tuple(group_legs)))
    registry.update_snapshot(PositionGroupSnapshot(
        GROUP_ID, STRATEGY, True, tuple(snapshot_legs), 0.0, 0.0, 0.0,
    ))
    vssf = SimpleNamespace(account=account)
    bridge = object.__new__(__import__(
        "application.composition.virtual_multi_leg_execution",
        fromlist=["VirtualMultiLegExecutionBridge"],
    ).VirtualMultiLegExecutionBridge)
    bridge.run_id = RUN_ID
    bridge.position_groups = registry
    bridge.position_lot_store = lot_store
    bridge.fee_ledger = fee_ledger
    bridge.provenance = {}
    bridge.bundle = SimpleNamespace(execution=SimpleNamespace(
        _authoritative_execute=SimpleNamespace(__self__=SimpleNamespace(vssf_runtime=vssf))
    ))
    bridge._build_terminal_position_group_snapshot = (
        __import__(
            "application.composition.virtual_multi_leg_execution",
            fromlist=["VirtualMultiLegExecutionBridge"],
        ).VirtualMultiLegExecutionBridge._build_terminal_position_group_snapshot.__get__(bridge)
    )
    bridge._position_flat_for_plan = (
        __import__(
            "application.composition.virtual_multi_leg_execution",
            fromlist=["VirtualMultiLegExecutionBridge"],
        ).VirtualMultiLegExecutionBridge._position_flat_for_plan.__get__(bridge)
    )
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "source_type": "DERIVED_SCENARIO", "provenance": "DERIVED_SCENARIO",
        "synthetic": True, "validation_only": True, "runtime_eligible": False,
        "production_runtime_eligible": False, "expiry_is_authoritative": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "contract_identity_authority": "SYNTHETIC_ONLY",
        "strategy_id": "strategy8_monthly",
        "scenario_id": "Q25_S8_MONTHLY_V3_NORMAL",
    }
    adapter = ValidationOnlyOptionExpiryCashSettlementAdapter(
        manifest=manifest, profile=PROFILE,
    )
    source_payload = {
        "scenario_id": manifest["scenario_id"],
        "expiry": EXPIRY,
        "underlying_settlement_price": str(settlement_price),
        "source": PROFILE.settlement_price_source,
        "profile_sha256": PROFILE.profile_sha256,
    }
    import hashlib
    source_hash = hashlib.sha256(
        json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return bridge, adapter, source_hash, source_payload


def test_synthetic_expiry_settlement_applies_multiplier_commission_and_flat_reconciliation():
    bridge, adapter, source_hash, source_payload = _make_bridge()
    result = adapter.settle_group(
        bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-ONCE",
        settlement_date=EXPIRY, underlying_settlement_price="505",
        settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
    )
    assert result["status"] == "SETTLED_VALIDATION_ONLY"
    assert result["authority"] == "NON_AUTHORITATIVE_SYNTHETIC"
    assert result["contract_multiplier"] == "250000"
    assert result["gross_realized_pnl_krw"] == "0"
    assert result["entry_commission_krw"] == "6000"
    assert result["expiry_commission_krw"] == "6000"
    assert result["net_realized_pnl_krw"] == "-12000"
    assert result["flat_state_reconciliation"] == "PASS"
    assert bridge.position_lot_store.open_lots() == ()
    assert bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions == {}
    assert result["group_leg_quantities_after"] == [0, 0]


def test_synthetic_put_itm_settlement_calculates_put_payoff_and_fees():
    bridge, adapter, source_hash, source_payload = _make_bridge(settlement_price="495")
    result = adapter.settle_group(
        bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-PUT-ITM",
        settlement_date=EXPIRY, underlying_settlement_price="495",
        settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
    )
    assert result["gross_realized_pnl_krw"] == "0"
    assert result["net_realized_pnl_krw"] == "-12000"
    assert [item["intrinsic_value_points"] for item in result["settled_lots"]] == ["0", "5"]


def test_synthetic_atm_expiry_settlement_zeroes_both_option_intrinsic_values():
    bridge, adapter, source_hash, source_payload = _make_bridge(settlement_price="500")
    result = adapter.settle_group(
        bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-ATM",
        settlement_date=EXPIRY, underlying_settlement_price="500",
        settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
    )
    assert [item["intrinsic_value_points"] for item in result["settled_lots"]] == ["0", "0"]
    assert result["gross_realized_pnl_krw"] == "-1250000"


def test_settlement_is_idempotent_and_rejects_same_key_with_different_price():
    bridge, adapter, source_hash, source_payload = _make_bridge()
    args = dict(
        bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-IDEMPOTENT",
        settlement_date=EXPIRY, underlying_settlement_price="505",
        settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
    )
    first = adapter.settle_group(**args)
    balance_after = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.balance
    second = adapter.settle_group(**args)
    assert second == first
    assert bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.balance == balance_after
    changed_payload = {**source_payload, "underlying_settlement_price": "506"}
    changed_hash = __import__("hashlib").sha256(
        json.dumps(changed_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="DUPLICATE_SETTLEMENT_CONFLICT"):
        adapter.settle_group(**{
            **args, "underlying_settlement_price": "506",
            "settlement_source_payload": changed_payload,
            "settlement_source_sha256": changed_hash,
        })


def test_pre_settlement_lot_account_quantity_mismatch_fails_without_mutation():
    bridge, adapter, source_hash, source_payload = _make_bridge()
    account = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account
    account.positions[next(iter(account.positions))]["qty"] = 2
    before = dict((key, dict(value)) for key, value in account.positions.items())
    with pytest.raises(ValueError, match="PRE_SETTLEMENT_QUANTITY_MISMATCH"):
        adapter.settle_group(
            bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-MISMATCH",
            settlement_date=EXPIRY, underlying_settlement_price="505",
            settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
        )
    assert account.positions == before
    assert len(bridge.position_lot_store.open_lots()) == 2


def test_adapter_rejects_wrong_expiry_and_non_validation_manifest():
    bridge, adapter, source_hash, source_payload = _make_bridge()
    identity = bridge.position_lot_store.open_lots()[0].instrument_identity
    with pytest.raises(ValueError, match="SOURCE_PAYLOAD_MISMATCH"):
        adapter.settle_group(
            bridge=bridge, group_id=GROUP_ID, settlement_id="S8-EXPIRY-WRONG-DATE",
            settlement_date="20261120", underlying_settlement_price="505",
            settlement_source_payload=source_payload, settlement_source_sha256=source_hash,
        )
    invalid = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "source_type": "REAL_VTS", "provenance": "REAL_VTS",
        "synthetic": False, "validation_only": False, "runtime_eligible": True,
        "production_runtime_eligible": True, "expiry_is_authoritative": True,
        "identity_source_status": "AUTHORITATIVE", "contract_identity_authority": "KIS",
        "strategy_id": "strategy8_monthly", "scenario_id": "Q25_S8_MONTHLY_V3_NORMAL",
    }
    with pytest.raises(ValueError, match="MANIFEST_BOUNDARY_INVALID"):
        ValidationOnlyOptionExpiryCashSettlementAdapter(manifest=invalid, profile=PROFILE)
