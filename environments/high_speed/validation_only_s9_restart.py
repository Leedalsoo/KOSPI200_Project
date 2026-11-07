from __future__ import annotations
from datetime import datetime
from decimal import Decimal
import hashlib, json
from pathlib import Path
from typing import Any

from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity

SCHEMA = 's9-validation-only-virtual-restart-v1'


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
        'execution_sequence': vssf_runtime.execution_engine._seq,
    }
