from application.composition.validation_only_h0iocnt0_record_identity_auditor import (
    parse_h0iocnt0_frame, current_observation_id, summarize_day,
)
import hashlib


def frame(records, sequence=1):
    payload='0|H0IOCNT0|'+f'{len(records):03d}'+'|'+'^'.join(v for r in records for v in r)
    return {'tr_id':'H0IOCNT0','sequence':sequence,'received_at':'2026-10-01T00:00:01+00:00',
        'payload':payload,'payload_sha256':hashlib.sha256(payload.encode()).hexdigest()}


def rec(symbol='B01610A34', hour='085159', marker='36'):
    x=['0']*58; x[0]=symbol; x[1]=hour; x[57]=marker; return x


def test_same_symbol_time_different_records_have_distinct_record_digests():
    f=frame([rec(marker='36'),rec(marker='35')])
    r=parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    assert r['legacy_duplicate_groups']==1 and r['legacy_excess_records']==1
    assert len({x.record_digest for x in r['observations']})==2


def test_exact_duplicate_records_are_separately_counted():
    f=frame([rec(),rec()])
    r=parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    assert r['legacy_excess_records']==1
    assert r['exact_duplicate_groups']==1 and r['exact_duplicate_excess_records']==1


def test_declared_count_and_58_field_boundary_are_enforced():
    f=frame([rec()]); f['payload']=f['payload'].replace('001|','002|',1)
    try: parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    except ValueError as e: assert str(e)=='H0IOCNT0_DECLARED_RECORD_COUNT_MISMATCH'
    else: raise AssertionError('count mismatch accepted')
    f=frame([rec()]); f['payload']+='^EXTRA'
    try: parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    except ValueError as e: assert str(e)=='H0IOCNT0_FIELD_COUNT_NOT_MULTIPLE_OF_58'
    else: raise AssertionError('bad field boundary accepted')


def test_payload_hash_and_timezone_are_verified():
    f=frame([rec()]); f['payload_sha256']='0'*64
    try: parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    except ValueError as e: assert str(e)=='RAW_PAYLOAD_HASH_MISMATCH'
    else: raise AssertionError('bad payload hash accepted')
    f=frame([rec()]); f['received_at']='2026-10-01T00:00:01'
    try: parse_h0iocnt0_frame(f,trading_date='20261001',line_number=1)
    except ValueError as e: assert str(e)=='RAW_RECEIVED_AT_TIMEZONE_REQUIRED'
    else: raise AssertionError('naive receive timestamp accepted')


def test_current_observation_id_includes_raw_frame_and_record_index():
    base=dict(run_id='run',raw_id='day:seq:line:hash',source='KIS:H0IOCNT0',symbol='B01610A34',
        observed_hour='085159',observed_at='2026-10-01T08:51:59+09:00',received_at='2026-10-01T08:52:00+09:00')
    a=current_observation_id(**base,record_index=0)
    b=current_observation_id(**base,record_index=1)
    c=current_observation_id(**(base|{'raw_id':'day:seq2:line2:hash2'}),record_index=0)
    assert len({a,b,c})==3
    assert current_observation_id(**base,record_index=0)==a


def test_summarize_day_uses_kst_and_matches_current_ingestion_identity_seed():
    f=frame([rec(marker='36'),rec(marker='35')])
    raw_hash=hashlib.sha256(f['payload'].encode()).hexdigest()
    f['payload_sha256']=raw_hash
    f['raw_file_sha256_prefix']=raw_hash[:8]
    report=summarize_day(frames=[f],trading_date='20261001',raw_file_sha256=raw_hash)
    assert report['parsed_58_field_records']==2
    assert report['current_normalizer_observation_id_collision_count']==0
