from application.composition.validation_only_three_source_orderbook_auditor import ValidationOnlyThreeSourceOrderBookAuditor

def audit(triples):
    return ValidationOnlyThreeSourceOrderBookAuditor(validation_only=True).audit(triples=triples,source_hashes={'fixture':'a'*64})

def make(side='1.0',trade='1.0',rest='1.0'):
    return {'symbol':'O1','trading_date':'20261001','record_id':'W1','ws_time_candidate':'2026-10-01T09:00:01+09:00','ws_received_at':'2026-10-01T09:00:01.1+09:00','rest_anchor':{'trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','collected_at':'2026-10-01T09:00:00.1+09:00','bid_price':rest,'ask_price':'1.1','bid_quantity':'10','ask_quantity':'11','payload_sha256':'b'*64},'trade_anchor':{'trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T09:00:00.5+09:00','received_at':'2026-10-01T09:00:00.6+09:00','bid_price':trade,'ask_price':'1.1','last_price':'1.05','payload_sha256':'c'*64},'ws_orderbook':{'bid_price':side,'ask_price':'1.1','bid_quantity':'10','ask_quantity':'11'},'ws_payload_sha256':'d'*64}

def test_three_sources_consistent_and_anchor_age_separated():
    r=audit([make()])
    assert r['counts'].get('exact_rest_anchor',0)==0 and r['counts']['nearest_prior_rest_anchor']==1
    assert r['counts']['nearest_prior_trade_anchor']==1
    assert r['three_source_consensus']['bid']['all_three_equal']==1
    assert r['rest_vs_ws_quantity_comparison']['bid']['equal']==1

def test_pairwise_differences_do_not_become_blocked():
    r=audit([make(side='1.0',trade='1.1',rest='1.2')])
    assert r['counts']['rest_vs_ws_bid_different']==1
    assert r['counts']['trade_vs_ws_bid_different']==1
    assert r['counts']['rest_vs_trade_bid_different']==1
    assert r['authority_claimed'] is False and r['gate_release_permitted'] is False

def test_missing_anchor_is_reported_without_fabrication():
    x=make(); x['rest_anchor']=None; x['trade_anchor']=None
    r=audit([x])
    assert r['counts']['no_rest_anchor']==1 and r['counts']['no_trade_anchor']==1
    assert r['counts']['rest_vs_ws_bid_missing']==1

def test_future_or_cross_day_anchor_is_not_used():
    x=make(); x['rest_anchor']['source_timestamp_candidate']='2026-10-01T09:00:02+09:00'; x['trade_anchor']['trading_date']='20261002'
    r=audit([x])
    assert r['counts']['future_rest_anchor']==1
    assert any('TRADE_CROSS_DAY_ANCHOR' in e for e in r['issues'])

def test_empty_and_missing_are_distinct_and_hash_deterministic():
    x=make(side='0',trade='0',rest='0'); r=audit([x])
    assert r['three_source_consensus']['bid']['missing_or_empty']==1
    assert audit([x])['report_sha256']==r['report_sha256']
    try: audit([{'symbol':'O1','trading_date':'20261001','ws_time_candidate':'2026-10-01T09:00:00'}])
    except ValueError as exc: assert 'TIMEZONE_REQUIRED' in str(exc)
    else: raise AssertionError('naive timestamp accepted')
