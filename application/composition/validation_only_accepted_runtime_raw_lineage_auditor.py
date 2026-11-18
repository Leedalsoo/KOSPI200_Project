from __future__ import annotations
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == '': return None
    try: return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc: raise ValueError('ACCEPTED_RUNTIME_NUMERIC_FIELD_INVALID') from exc


def raw_base_key(*, symbol: str, hour: str, last: Any, volume: Any, bid: Any, received_at: str) -> tuple[Any, ...]:
    return (symbol, hour, decimal_value(last), decimal_value(volume), decimal_value(bid), received_at)


def audit_accepted_row(row: Mapping[str, Any], *, trading_date: str, raw_file_sha256: str,
                       canonical_sha256: str, raw_base_counts: Counter[tuple[Any, ...]],
                       raw_full_counts: Counter[tuple[Any, ...]]) -> dict[str, Any]:
    tick=row.get('tick') or {}; meta=row.get('scenario_metadata') or {}; field_prov=meta.get('field_provenance') or {}
    generated=set(meta.get('generated_fields') or [])
    symbol=str(tick.get('symbol') or '')
    hour=str(tick.get('option_observed_hour') or '').replace(':','')
    received=str(meta.get('source_collected_at') or '')
    base=raw_base_key(symbol=symbol,hour=hour,last=tick.get('last_price'),volume=tick.get('volume'),bid=tick.get('bid_price'),received_at=received)
    errors=[]
    if row.get('schema')!='reference-canonical-market-tick-v1': errors.append('SCHEMA_MISMATCH')
    if row.get('provenance')!='DERIVED_SCENARIO': errors.append('PROVENANCE_NOT_DERIVED_SCENARIO')
    if meta.get('accepted_for_project_verification') is not True: errors.append('ACCEPTANCE_FLAG_MISSING')
    if meta.get('trading_date')!=trading_date: errors.append('TRADING_DATE_MISMATCH')
    if meta.get('source_raw_sha256')!=raw_file_sha256: errors.append('RAW_HASH_MISMATCH')
    if meta.get('source_canonical_sha256')!=canonical_sha256: errors.append('CANONICAL_HASH_REFERENCE_MISMATCH')
    if tick.get('timestamp')!=meta.get('source_observed_at'): errors.append('SOURCE_OBSERVED_AT_MISMATCH')
    if tick.get('source_instrument_code')!=symbol or tick.get('instrument_id')!=symbol: errors.append('INSTRUMENT_CODE_MISMATCH')
    if tick.get('option_source')!='KIS:H0IOCNT0+ACCEPTED_ENRICHMENT': errors.append('OPTION_SOURCE_MISMATCH')
    if meta.get('source_type')!='COLLECTED_KIS_WS_WITH_ACCEPTED_ENRICHMENT': errors.append('SOURCE_TYPE_MISMATCH')
    if not meta.get('source_observation_id'): errors.append('SOURCE_OBSERVATION_ID_MISSING')
    if not isinstance(meta.get('source_line_number'),int): errors.append('SOURCE_LINE_NUMBER_INVALID')
    identity_status=tick.get('instrument_identity_status')
    if identity_status!='KIS_MASTER_RESOLVED_POST_DATE_CORROBORATED': errors.append('IDENTITY_STATUS_NOT_POST_DATE_CORROBORATED')
    if meta.get('target_master_snapshot_date')!='20261014': errors.append('TARGET_MASTER_SNAPSHOT_DATE_UNEXPECTED')
    if not meta.get('target_master_sha256'): errors.append('TARGET_MASTER_HASH_MISSING')
    if base not in raw_base_counts or raw_base_counts[base]<=0: errors.append('RAW_SOURCE_RECORD_NOT_MATCHED')
    else:
        raw_base_counts[base]-=1
        if 'ask_price' not in generated:
            full=base+(decimal_value(tick.get('ask_price')),)
            if raw_full_counts[full]<=0: errors.append('RAW_ASK_PRICE_NOT_MATCHED')
            else: raw_full_counts[full]-=1
    generated_to_provenance={
        'underlying_price':'underlying_price','underlying_price_group_consensus':'underlying_price_group_consensus','ask_price':'ask_price',
        'order_book.bid_quantity':'order_book_quantities','order_book.ask_quantity':'order_book_quantities',
        'contract_multiplier':'contract_multiplier','implied_volatility':'option_analytics',
        'delta':'option_analytics','gamma':'option_analytics','theta':'option_analytics','vega':'option_analytics',
    }
    missing=[f for f in generated if generated_to_provenance.get(f) not in field_prov]
    if missing: errors.append('GENERATED_FIELD_PROVENANCE_MISSING')
    if 'contract_multiplier' in generated and field_prov.get('contract_multiplier',{}).get('source')!='KRX_REGULAR_KOSPI200_OPTION_CONTRACT_SPEC':
        errors.append('CONTRACT_MULTIPLIER_SOURCE_MISMATCH')
    return {'errors':errors,'generated_fields':sorted(generated),'underlying_source':tick.get('underlying_source'),
        'source_observation_id':meta.get('source_observation_id'),'source_line_number':meta.get('source_line_number'),
        'symbol':symbol,'option_observed_hour':hour}
