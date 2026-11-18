from collections import Counter
from application.composition.validation_only_accepted_runtime_raw_lineage_auditor import audit_accepted_row, raw_base_key, decimal_value


def row(generated=()):
    return {'schema':'reference-canonical-market-tick-v1','provenance':'DERIVED_SCENARIO','tick':{
      'timestamp':'2026-10-12T09:00:45+09:00','symbol':'B01611A14','source_instrument_code':'B01611A14','instrument_id':'B01611A14',
      'option_observed_hour':'09:00:45','last_price':43.85,'volume':1,'bid_price':33.6,'ask_price':43.9,
      'option_source':'KIS:H0IOCNT0+ACCEPTED_ENRICHMENT','instrument_identity_status':'KIS_MASTER_RESOLVED_POST_DATE_CORROBORATED'},
      'scenario_metadata':{'accepted_for_project_verification':True,'trading_date':'20261012','source_type':'COLLECTED_KIS_WS_WITH_ACCEPTED_ENRICHMENT',
       'source_observation_id':'oid-1','source_line_number':1,'source_observed_at':'2026-10-12T09:00:45+09:00','source_collected_at':'2026-10-12T00:00:45.939022+00:00',
       'source_raw_sha256':'rhash','source_canonical_sha256':'chash','target_master_sha256':'mhash','target_master_snapshot_date':'20261014',
       'generated_fields':list(generated),'field_provenance':{'order_book_quantities':{'method':'deterministic'},'contract_multiplier':{'source':'KRX_REGULAR_KOSPI200_OPTION_CONTRACT_SPEC'},'option_analytics':{'method':'deterministic'}}}}

def counters(ask=43.9):
    base=raw_base_key(symbol='B01611A14',hour='090045',last='43.85',volume=1,bid='33.60',received_at='2026-10-12T00:00:45.939022+00:00')
    return Counter({base:1}),Counter({base+(decimal_value(ask),):1})

def test_accepted_row_matches_raw_and_preserves_post_date_master_boundary():
    b,f=counters(); result=audit_accepted_row(row(),trading_date='20261012',raw_file_sha256='rhash',canonical_sha256='chash',raw_base_counts=b,raw_full_counts=f)
    assert result['errors']==[] and b[next(iter(b))]==0 and f[next(iter(f))]==0

def test_generated_ask_is_not_compared_as_observed_raw_value_but_needs_provenance():
    b,f=counters(); x=row(['ask_price']); x['scenario_metadata']['field_provenance']['ask_price']={'method':'nearest_spread'}
    result=audit_accepted_row(x,trading_date='20261012',raw_file_sha256='rhash',canonical_sha256='chash',raw_base_counts=b,raw_full_counts=f)
    assert result['errors']==[] and b[next(iter(b))]==0

def test_raw_hash_mismatch_is_reported_not_silently_accepted():
    b,f=counters(); result=audit_accepted_row(row(),trading_date='20261012',raw_file_sha256='wrong',canonical_sha256='chash',raw_base_counts=b,raw_full_counts=f)
    assert 'RAW_HASH_MISMATCH' in result['errors']

def test_missing_generated_field_provenance_is_reported():
    b,f=counters(); x=row(['contract_multiplier']); x['scenario_metadata']['field_provenance'].pop('contract_multiplier')
    result=audit_accepted_row(x,trading_date='20261012',raw_file_sha256='rhash',canonical_sha256='chash',raw_base_counts=b,raw_full_counts=f)
    assert 'GENERATED_FIELD_PROVENANCE_MISSING' in result['errors']
    assert 'CONTRACT_MULTIPLIER_SOURCE_MISMATCH' in result['errors']


def test_underlying_group_consensus_has_its_own_provenance_key():
    b,f=counters(); x=row(['underlying_price_group_consensus'])
    x['scenario_metadata']['field_provenance']['underlying_price_group_consensus']={'method':'KIS_SAME_TIMESTAMP_GROUP_MEDIAN'}
    result=audit_accepted_row(x,trading_date='20261012',raw_file_sha256='rhash',canonical_sha256='chash',raw_base_counts=b,raw_full_counts=f)
    assert result['errors']==[]
