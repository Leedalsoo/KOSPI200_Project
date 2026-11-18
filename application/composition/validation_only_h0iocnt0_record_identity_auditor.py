from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Any, Mapping
from zoneinfo import ZoneInfo
import json

H0IOCNT0_FIELDS = 58

@dataclass(frozen=True)
class RecordIdentity:
    symbol: str
    observed_hour: str
    record_digest: str
    record_index: int
    observation_id: str


def parse_h0iocnt0_frame(
    frame: Mapping[str, Any], *, trading_date: str, line_number: int
) -> dict[str, Any]:
    payload = str(frame.get('payload') or '')
    parts = payload.split('|', 3)
    if len(parts) != 4 or parts[0] != '0' or parts[1] != 'H0IOCNT0':
        raise ValueError('H0IOCNT0_ENVELOPE_INVALID')
    try:
        declared_records = int(parts[2])
    except ValueError as exc:
        raise ValueError('H0IOCNT0_DECLARED_COUNT_INVALID') from exc
    values = parts[3].split('^')
    if len(values) % H0IOCNT0_FIELDS:
        raise ValueError('H0IOCNT0_FIELD_COUNT_NOT_MULTIPLE_OF_58')
    actual_records = len(values) // H0IOCNT0_FIELDS
    if actual_records != declared_records:
        raise ValueError('H0IOCNT0_DECLARED_RECORD_COUNT_MISMATCH')
    seq = frame.get('sequence')
    if seq is None:
        raise ValueError('RAW_SEQUENCE_MISSING')
    received_at = str(frame.get('received_at') or '')
    try:
        received = datetime.fromisoformat(received_at)
    except ValueError as exc:
        raise ValueError('RAW_RECEIVED_AT_INVALID') from exc
    if received.tzinfo is None:
        raise ValueError('RAW_RECEIVED_AT_TIMEZONE_REQUIRED')
    payload_hash = sha256(payload.encode('utf-8')).hexdigest()
    declared_hash = str(frame.get('payload_sha256') or '')
    if declared_hash and declared_hash != payload_hash:
        raise ValueError('RAW_PAYLOAD_HASH_MISMATCH')
    raw_id = f'{trading_date}:{seq}:{line_number}:{declared_hash or payload_hash}'
    run_id = f'vts-ws-canonical-{trading_date}-{frame.get("raw_file_sha256_prefix", "")}'
    legacy_keys: Counter[tuple[str, str]] = Counter()
    exact_records: Counter[str] = Counter()
    observations: list[RecordIdentity] = []
    for idx in range(actual_records):
        record = values[idx * H0IOCNT0_FIELDS:(idx + 1) * H0IOCNT0_FIELDS]
        symbol, hour = record[0], record[1]
        if not symbol:
            raise ValueError('H0IOCNT0_SYMBOL_MISSING')
        if len(hour) != 6 or not hour.isdigit():
            raise ValueError('H0IOCNT0_BSOP_HOUR_INVALID')
        datetime.strptime(trading_date + hour, '%Y%m%d%H%M%S')
        digest = sha256('^'.join(record).encode('utf-8')).hexdigest()
        legacy_keys[(symbol, hour)] += 1
        exact_records[digest] += 1
        observed_at = datetime.strptime(trading_date + hour, '%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
        # This reproduces the current normalizer's source/identity fields; the
        # run_id prefix is supplied by the caller in the full-file audit.
        seed = f'{raw_id}|{idx}|KIS:H0IOCNT0|{symbol}|{hour}|{observed_at}|{received.isoformat()}'
        observation_id = sha256(seed.encode('utf-8')).hexdigest()[:24]
        observations.append(RecordIdentity(symbol, hour, digest, idx, observation_id))
    return {
        'raw_id': raw_id,
        'payload_hash': payload_hash,
        'declared_records': declared_records,
        'actual_records': actual_records,
        'legacy_duplicate_groups': sum(1 for n in legacy_keys.values() if n > 1),
        'legacy_excess_records': sum(n - 1 for n in legacy_keys.values() if n > 1),
        'exact_duplicate_groups': sum(1 for n in exact_records.values() if n > 1),
        'exact_duplicate_excess_records': sum(n - 1 for n in exact_records.values() if n > 1),
        'observations': observations,
    }


def current_observation_id(*, run_id: str, raw_id: str, record_index: int, source: str,
                           symbol: str, observed_hour: str, observed_at: str, received_at: str) -> str:
    seed = f'{run_id}|{raw_id}|{record_index}|{source}|{symbol}|{observed_hour}|{observed_at}|{received_at}'
    return sha256(seed.encode('utf-8')).hexdigest()[:24]


def summarize_day(*, frames: list[Mapping[str, Any]], trading_date: str,
                  raw_file_sha256: str) -> dict[str, Any]:
    seqs: Counter[int] = Counter()
    payloads: Counter[str] = Counter()
    raw_ids: set[str] = set()
    observation_ids: set[str] = set()
    legacy_groups = legacy_excess = exact_groups = exact_excess = 0
    parsed = malformed = payload_hash_mismatch = 0
    symbol_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    run_id = f'vts-ws-canonical-{trading_date}-{raw_file_sha256[:8]}'
    for line_number, frame in enumerate(frames, 1):
        if frame.get('tr_id') != 'H0IOCNT0':
            continue
        seqs[int(frame['sequence'])] += 1
        payload = str(frame.get('payload') or '')
        ph = sha256(payload.encode('utf-8')).hexdigest()
        payloads[ph] += 1
        # Reproduce raw_id used by the current canonical ingestion caller.
        raw_id = f'{trading_date}:{frame["sequence"]}:{line_number}:{frame.get("payload_sha256") or ph}'
        raw_ids.add(raw_id)
        try:
            parsed_frame = parse_h0iocnt0_frame(frame, trading_date=trading_date, line_number=line_number)
        except (ValueError, KeyError, TypeError):
            malformed += 1
            if frame.get('payload_sha256') and frame['payload_sha256'] != ph:
                payload_hash_mismatch += 1
            continue
        parsed += parsed_frame['actual_records']
        legacy_groups += parsed_frame['legacy_duplicate_groups']
        legacy_excess += parsed_frame['legacy_excess_records']
        exact_groups += parsed_frame['exact_duplicate_groups']
        exact_excess += parsed_frame['exact_duplicate_excess_records']
        for item in parsed_frame['observations']:
            symbol_counts[item.symbol] += 1
            observed_at = datetime.strptime(trading_date + item.observed_hour, '%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
            received_at = str(frame['received_at'])
            oid = current_observation_id(run_id=run_id, raw_id=raw_id, record_index=item.record_index,
                source='KIS:H0IOCNT0', symbol=item.symbol, observed_hour=item.observed_hour,
                observed_at=observed_at, received_at=received_at)
            observation_ids.add(oid)
            if len(examples) < 5 and parsed_frame['legacy_excess_records']:
                examples.append({'sequence':frame['sequence'],'line_number':line_number,'symbol':item.symbol,
                    'bsop_hour':item.observed_hour,'record_index':item.record_index,'record_sha256':item.record_digest})
    duplicate_seq_groups = sum(1 for n in seqs.values() if n > 1)
    duplicate_seq_excess = sum(n - 1 for n in seqs.values() if n > 1)
    duplicate_payload_groups = sum(1 for n in payloads.values() if n > 1)
    duplicate_payload_excess = sum(n - 1 for n in payloads.values() if n > 1)
    return {
        'trading_date':trading_date,'raw_h0iocnt0_frames':sum(seqs.values()),'unique_sequence_count':len(seqs),
        'duplicate_sequence_groups':duplicate_seq_groups,'duplicate_sequence_excess_frames':duplicate_seq_excess,
        'duplicate_payload_hash_groups':duplicate_payload_groups,'duplicate_payload_hash_excess_frames':duplicate_payload_excess,
        'parsed_58_field_records':parsed,'malformed_frames':malformed,'payload_hash_mismatches':payload_hash_mismatch,
        'legacy_symbol_time_duplicate_groups':legacy_groups,'legacy_symbol_time_excess_records':legacy_excess,
        'exact_full_record_duplicate_groups_within_frame':exact_groups,'exact_full_record_duplicate_excess_records':exact_excess,
        'current_raw_id_unique_count':len(raw_ids),'current_raw_id_collision_count':sum(seqs.values())-len(raw_ids),
        'current_normalizer_observation_id_unique_count':len(observation_ids),
        'current_normalizer_observation_id_collision_count':parsed-len(observation_ids),
        'unique_symbols':len(symbol_counts),'symbol_record_counts':dict(sorted(symbol_counts.items())),
        'collision_examples':examples,
    }
