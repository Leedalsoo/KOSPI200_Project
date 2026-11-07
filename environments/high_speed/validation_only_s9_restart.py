from __future__ import annotations
from datetime import datetime
from decimal import Decimal
import hashlib, json
from pathlib import Path
from typing import Any

from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity
from core.oms.position_group import (
    LegStatus, PositionGroup, PositionGroupLeg, PositionGroupLegPnL, PositionGroupSnapshot,
)
from environments.virtual.authoritative_vssf.canonical import (
    CanonicalAssetType, CanonicalExecutionReport, CanonicalOptionType, CanonicalOrderSide,
)

SCHEMA = 's9-validation-only-virtual-restart-v2'


def _lot_to_json(lot: PositionLotProvenance) -> dict[str, Any]:
    identity = lot.instrument_identity
    return {
        'run_id': lot.run_id, 'instrument_id': lot.instrument_id,
        'strategy_id': lot.strategy_id, 'group_id': lot.group_id, 'leg_id': lot.leg_id,
        'client_order_id': lot.client_order_id, 'execution_id': lot.execution_id,
        'side': lot.side, 'opened_quantity': lot.opened_quantity,
        'remaining_quantity': lot.remaining_quantity,
        'execution_timestamp': lot.execution_timestamp.isoformat(),
        'instrument_identity': {
            'instrument_id': identity.instrument_id, 'symbol': identity.symbol,
            'expiry': identity.expiry, 'option_type': identity.option_type,
            'strike': str(identity.strike),
            'contract_multiplier': str(identity.contract_multiplier),
            'identity_source': identity.identity_source,
        },
        'contract_multiplier': str(lot.contract_multiplier),
        'identity_source': lot.identity_source, 'position_role': str(lot.position_role),
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _group_to_json(group: PositionGroup) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "strategy_id": group.strategy_id,
        "direction": group.direction,
        "legs": [
            {
                "leg_id": leg.leg_id, "group_id": leg.group_id,
                "instrument_id": leg.instrument_id, "side": leg.side,
                "quantity": leg.quantity, "contract_multiplier": str(leg.contract_multiplier),
                "identity_source": leg.identity_source, "status": str(_enum_value(leg.status)),
            }
            for leg in group.legs
        ],
    }


def _group_snapshot_to_json(snapshot: PositionGroupSnapshot) -> dict[str, Any]:
    return {
        "group_id": snapshot.group_id, "strategy_id": snapshot.strategy_id,
        "complete": snapshot.complete,
        "legs": [
            {
                "leg_id": leg.leg_id, "group_id": leg.group_id,
                "instrument_id": leg.instrument_id, "quantity": leg.quantity,
                "contract_multiplier": str(leg.contract_multiplier),
                "identity_source": leg.identity_source, "avg_price": leg.avg_price,
                "current_price": leg.current_price, "unrealized_pnl": leg.unrealized_pnl,
                "run_id": leg.run_id, "client_order_id": leg.client_order_id,
                "execution_id": leg.execution_id, "execution_ids": list(leg.execution_ids),
            }
            for leg in snapshot.legs
        ],
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "total_pnl": snapshot.total_pnl,
    }


def _execution_report_to_json(report: CanonicalExecutionReport) -> dict[str, Any]:
    return {
        "exec_id": report.exec_id, "client_order_id": report.client_order_id,
        "track_id": report.track_id, "asset_type": str(_enum_value(report.asset_type)),
        "side": str(_enum_value(report.side)), "executed_qty": report.executed_qty,
        "executed_price": report.executed_price, "fee": report.fee,
        "slippage": report.slippage, "timestamp": report.timestamp,
        "symbol": report.symbol,
        "option_type": str(_enum_value(report.option_type)) if report.option_type is not None else None,
        "strike": report.strike, "expiry": report.expiry,
        "strategy_id": report.strategy_id, "group_id": report.group_id,
        "leg_id": report.leg_id, "instrument_id": report.instrument_id,
        "contract_multiplier": report.contract_multiplier,
        "identity_source": report.identity_source,
    }


def _execution_report_from_json(row: dict[str, Any]) -> CanonicalExecutionReport:
    return CanonicalExecutionReport(
        exec_id=str(row["exec_id"]), client_order_id=str(row["client_order_id"]),
        track_id=str(row["track_id"]), asset_type=CanonicalAssetType(str(row["asset_type"])),
        side=CanonicalOrderSide(str(row["side"])), executed_qty=int(row["executed_qty"]),
        executed_price=float(row["executed_price"]), fee=float(row["fee"]),
        slippage=float(row["slippage"]), timestamp=str(row["timestamp"]),
        symbol=str(row["symbol"]),
        option_type=CanonicalOptionType(str(row["option_type"])) if row.get("option_type") else None,
        strike=float(row.get("strike", 0.0)), expiry=str(row.get("expiry", "")),
        strategy_id=str(row.get("strategy_id", "")), group_id=str(row.get("group_id", "")),
        leg_id=str(row.get("leg_id", "")), instrument_id=str(row.get("instrument_id", "")),
        contract_multiplier=(float(row["contract_multiplier"]) if row.get("contract_multiplier") is not None else None),
        identity_source=str(row.get("identity_source", "")),
    )


def _restore_group(row: dict[str, Any]) -> PositionGroup:
    return PositionGroup(
        group_id=str(row["group_id"]), strategy_id=str(row["strategy_id"]),
        direction=str(row["direction"]),
        legs=tuple(PositionGroupLeg(
            leg_id=str(leg["leg_id"]), group_id=str(leg["group_id"]),
            instrument_id=str(leg["instrument_id"]), side=str(leg["side"]),
            quantity=int(leg["quantity"]), contract_multiplier=Decimal(str(leg["contract_multiplier"])),
            identity_source=str(leg["identity_source"]), status=LegStatus(str(leg["status"])),
        ) for leg in row["legs"]),
    )


def _restore_group_snapshot(row: dict[str, Any]) -> PositionGroupSnapshot:
    return PositionGroupSnapshot(
        group_id=str(row["group_id"]), strategy_id=str(row["strategy_id"]),
        complete=bool(row["complete"]),
        legs=tuple(PositionGroupLegPnL(
            leg_id=str(leg["leg_id"]), group_id=str(leg["group_id"]),
            instrument_id=str(leg["instrument_id"]), quantity=int(leg["quantity"]),
            contract_multiplier=Decimal(str(leg["contract_multiplier"])),
            identity_source=str(leg["identity_source"]), avg_price=float(leg["avg_price"]),
            current_price=float(leg["current_price"]), unrealized_pnl=float(leg["unrealized_pnl"]),
            run_id=str(leg["run_id"]), client_order_id=str(leg["client_order_id"]),
            execution_id=str(leg["execution_id"]), execution_ids=tuple(str(x) for x in leg.get("execution_ids", [])),
        ) for leg in row["legs"]),
        realized_pnl=float(row["realized_pnl"]),
        unrealized_pnl=float(row["unrealized_pnl"]), total_pnl=float(row["total_pnl"]),
    )


def write_restart_snapshot(path: str | Path, *, run_id: str, adapter: Any,
                           runtime_snapshot: dict[str, Any], process_id: int) -> dict[str, Any]:
    lots = tuple(runtime_snapshot.get('open_lots', ()))
    positions = runtime_snapshot.get('account_positions', {})
    if len(lots) != 2 or len(positions) != 2:
        raise ValueError('S9_RESTART_CAPTURE_REQUIRES_EXACT_OPEN_PUT_CALL_PAIR')
    if {str(getattr(x, 'option_type', '')).upper() for x in (lot.instrument_identity for lot in lots)} != {'PUT', 'CALL'}:
        raise ValueError('S9_RESTART_CAPTURE_OPTION_PAIR_INVALID')
    payload = {
        'schema': SCHEMA, 'validation_only': True, 'provenance': 'SYNTHETIC',
        'run_id': run_id, 'captured_process_id': int(process_id),
        'scenario_id': adapter.evidence.scenario_id,
        'manifest_sha256': adapter.evidence.manifest_sha256,
        'dataset_sha256': adapter.evidence.dataset_sha256,
        'contract_profile_sha256': adapter.evidence.contract_profile_sha256,
        'risk_profile_sha256': adapter.evidence.risk_profile_sha256,
        'strategy_state': runtime_snapshot.get('strategy_state'),
        'open_lots': [_lot_to_json(x) for x in lots],
        'position_groups': [_group_to_json(x) for x in runtime_snapshot.get('position_groups', {}).values()],
        'position_group_snapshots': [_group_snapshot_to_json(x) for x in runtime_snapshot.get('position_group_snapshots', {}).values()],
        'execution_reports': [_execution_report_to_json(x) for x in runtime_snapshot.get('execution_reports', ())],
        'account': {
            'positions': positions,
            'balance': str(runtime_snapshot['account_balance']),
            'realized_pnl': str(runtime_snapshot['realized_pnl']),
            'unrealized_pnl': str(runtime_snapshot['unrealized_pnl']),
            'free_margin': str(runtime_snapshot['account_free_margin']),
            'used_margin': str(runtime_snapshot['account_used_margin']),
            'ledger_transactions': runtime_snapshot.get('ledger_transactions', []),
        },
        'fee_records': [
            {**vars(x), 'fee_amount': str(x.fee_amount), 'executed_price': str(x.executed_price),
             'executed_at': x.executed_at.isoformat()}
            for x in runtime_snapshot.get('fee_records', ())
        ],
        'risk_audit_records': list(runtime_snapshot.get('risk_audit_records', ())),
        'execution_sequence': int(runtime_snapshot.get('execution_sequence', 0)),
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + '\n').encode()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.with_suffix(target.suffix + '.sha256').exists():
        raise RuntimeError(f'S9_RESTART_SNAPSHOT_REFUSE_OVERWRITE:{target}')
    target.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    target.with_suffix(target.suffix + '.sha256').write_text(digest + f'  {target.name}\n', encoding='utf-8')
    return {'path': str(target), 'sha256': digest, 'open_lots': len(lots), 'positions': len(positions)}


def restore_restart_snapshot(path: str | Path, *, run_id: str, adapter: Any,
                              vssf_runtime: Any, replay_bridge: Any) -> dict[str, Any]:
    target = Path(path)
    encoded = target.read_bytes()
    sidecar = target.with_suffix(target.suffix + '.sha256')
    if not sidecar.is_file() or sidecar.read_text(encoding='utf-8').split()[0] != hashlib.sha256(encoded).hexdigest():
        raise ValueError('S9_RESTART_SNAPSHOT_HASH_MISMATCH')
    payload = json.loads(encoded)
    expected = {
        'schema': SCHEMA, 'validation_only': True, 'provenance': 'SYNTHETIC',
        'run_id': run_id, 'scenario_id': adapter.evidence.scenario_id,
        'manifest_sha256': adapter.evidence.manifest_sha256,
        'dataset_sha256': adapter.evidence.dataset_sha256,
        'contract_profile_sha256': adapter.evidence.contract_profile_sha256,
        'risk_profile_sha256': adapter.evidence.risk_profile_sha256,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f'S9_RESTART_SNAPSHOT_BINDING_MISMATCH:{key}')
    if payload.get('strategy_state') != 'OVERNIGHT_INSURANCE_ACTIVE':
        raise ValueError('S9_RESTART_SNAPSHOT_STRATEGY_NOT_ACTIVE')
    account = payload.get('account')
    lots = payload.get('open_lots')
    if not isinstance(account, dict) or not isinstance(lots, list) or len(lots) != 2:
        raise ValueError('S9_RESTART_SNAPSHOT_ACCOUNT_OR_LOTS_INVALID')

    groups = payload.get('position_groups')
    execution_reports = payload.get('execution_reports')
    if not isinstance(groups, list) or not groups or not isinstance(execution_reports, list) or len(execution_reports) < 2:
        raise ValueError('S9_RESTART_SNAPSHOT_GROUP_OR_EXECUTION_HISTORY_MISSING')
    for row in groups:
        replay_bridge.position_groups.register(_restore_group(row))
    for row in payload.get('position_group_snapshots', []):
        replay_bridge.position_groups.update_snapshot(_restore_group_snapshot(row))
    vssf_runtime.execution_engine.reports = [_execution_report_from_json(row) for row in execution_reports]

    # Restore execution-created provenance lots into a fresh VirtualPositionLotStore.
    for row in lots:
        ident = row['instrument_identity']
        identity = OptionInstrumentIdentity(
            instrument_id=str(ident['instrument_id']), symbol=str(ident['symbol']),
            expiry=str(ident['expiry']), option_type=str(ident['option_type']),
            strike=Decimal(str(ident['strike'])),
            contract_multiplier=Decimal(str(ident['contract_multiplier'])),
            identity_source=str(ident['identity_source']),
        )
        lot = PositionLotProvenance(
            run_id=str(row['run_id']), instrument_id=str(row['instrument_id']),
            strategy_id=str(row['strategy_id']), group_id=str(row['group_id']),
            leg_id=str(row['leg_id']), client_order_id=str(row['client_order_id']),
            execution_id=str(row['execution_id']), side=str(row['side']),
            opened_quantity=int(row['opened_quantity']), remaining_quantity=int(row['remaining_quantity']),
            execution_timestamp=datetime.fromisoformat(row['execution_timestamp']),
            instrument_identity=identity, contract_multiplier=Decimal(str(row['contract_multiplier'])),
            identity_source=str(row['identity_source']), position_role=PositionRole(str(row['position_role'])),
        )
        replay_bridge.position_lot_store.apply_execution(lot)

    positions = account.get('positions')
    if not isinstance(positions, dict) or len(positions) != 2:
        raise ValueError('S9_RESTART_SNAPSHOT_ACCOUNT_POSITIONS_INVALID')
    vssf_runtime.account.positions.clear()
    vssf_runtime.account.positions.update({str(k): dict(v) for k, v in positions.items()})
    vssf_runtime.account.balance = Decimal(str(account['balance']))
    vssf_runtime.account.realized_pnl = Decimal(str(account['realized_pnl']))
    vssf_runtime.account.unrealized_pnl = Decimal(str(account['unrealized_pnl']))
    vssf_runtime.account.pnl_engine.realized_pnl = vssf_runtime.account.realized_pnl
    vssf_runtime.account.pnl_engine.unrealized_pnl = vssf_runtime.account.unrealized_pnl
    vssf_runtime.account.free_margin = Decimal(str(account['free_margin']))
    vssf_runtime.account.used_margin = Decimal(str(account['used_margin']))
    vssf_runtime.account.ledger_engine.transactions = list(account.get('ledger_transactions', []))

    # Carry the execution sequence forward so post-restart fills cannot reuse IDs.
    vssf_runtime.execution_engine._seq = int(payload.get('execution_sequence', 0))
    for row in payload.get('fee_records', []):
        replay_bridge.fee_ledger.record(Track9FeeRecord(
            run_id=str(row['run_id']), strategy_id=str(row['strategy_id']),
            group_id=str(row['group_id']), leg_id=str(row['leg_id']),
            client_order_id=str(row['client_order_id']), execution_id=str(row['execution_id']),
            instrument_id=str(row['instrument_id']), fee_amount=Decimal(str(row['fee_amount'])),
            executed_quantity=int(row['executed_quantity']), executed_price=Decimal(str(row['executed_price'])),
            executed_at=datetime.fromisoformat(row['executed_at']), source=str(row['source']),
        ))
    adapter.risk_audit_records.extend(payload.get('risk_audit_records', []))

    open_lots = replay_bridge.position_lot_store.open_lots()
    if (len(open_lots) != 2
            or {x.position_role for x in open_lots} != {PositionRole.OVERNIGHT_INSURANCE}
            or {str(x.instrument_identity.option_type).upper() for x in open_lots} != {'PUT', 'CALL'}
            or any(x.run_id != run_id or x.strategy_id != 'track9_event_overnight_insurance'
                   or x.side != 'BUY' or x.remaining_quantity <= 0 for x in open_lots)):
        raise ValueError('S9_RESTART_RESTORED_POSITION_PAIR_INVALID')
    restored_groups = replay_bridge.position_groups.all()
    if len(restored_groups) != 1:
        raise ValueError('S9_RESTART_RESTORED_POSITION_GROUP_COUNT_INVALID')
    restored_group = next(iter(restored_groups.values()))
    if restored_group.strategy_id != 'track9_event_overnight_insurance':
        raise ValueError('S9_RESTART_RESTORED_POSITION_GROUP_STRATEGY_MISMATCH')
    group_legs = {leg.instrument_id: leg for leg in restored_group.legs}
    if len(group_legs) != 2 or {leg.leg_id for leg in restored_group.legs} != {'put', 'call'}:
        raise ValueError('S9_RESTART_RESTORED_POSITION_GROUP_PAIR_INVALID')
    restored_reports = {report.exec_id: report for report in vssf_runtime.execution_engine.reports}
    if len(restored_reports) != 2:
        raise ValueError('S9_RESTART_RESTORED_EXECUTION_HISTORY_COUNT_INVALID')
    for lot in open_lots:
        group_leg = group_legs.get(lot.instrument_id)
        if (group_leg is None or group_leg.status != LegStatus.FILLED
                or group_leg.quantity != lot.opened_quantity
                or group_leg.side != lot.side or group_leg.leg_id != lot.leg_id):
            raise ValueError('S9_RESTART_RESTORED_POSITION_GROUP_LOT_MISMATCH')
        execution = restored_reports.get(lot.execution_id)
        if (execution is None or execution.client_order_id != lot.client_order_id
                or execution.group_id != lot.group_id or execution.leg_id != lot.leg_id
                or execution.instrument_id != lot.instrument_id
                or execution.executed_qty != lot.opened_quantity):
            raise ValueError('S9_RESTART_RESTORED_EXECUTION_LOT_MISMATCH')
    lot_qty = {x.instrument_id: sum(y.remaining_quantity for y in open_lots if y.instrument_id == x.instrument_id)
               for x in open_lots}
    for instrument_id, quantity in lot_qty.items():
        position = vssf_runtime.account.positions.get(instrument_id)
        if position is None or int(position.get('qty', 0)) != quantity:
            raise ValueError('S9_RESTART_RESTORED_ACCOUNT_POSITION_MISMATCH')
    return {
        'status': 'RESTORED', 'captured_process_id': payload['captured_process_id'],
        'restored_open_lots': len(open_lots), 'restored_account_positions': len(positions),
        'restored_fee_records': len(payload.get('fee_records', [])),
        'restored_risk_audits': len(payload.get('risk_audit_records', [])),
        'restored_position_groups': len(groups),
        'restored_group_snapshots': len(payload.get('position_group_snapshots', [])),
        'restored_execution_reports': len(vssf_runtime.execution_engine.reports),
        'restored_ledger_transactions': len(vssf_runtime.account.ledger_engine.transactions),
        'execution_sequence': vssf_runtime.execution_engine._seq,
    }
