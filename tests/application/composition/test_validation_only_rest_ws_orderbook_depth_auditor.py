from application.composition.validation_only_rest_ws_orderbook_depth_auditor import ValidationOnlyRestWsOrderBookDepthAuditor

def audit(rest,ws):
    return ValidationOnlyRestWsOrderBookDepthAuditor(validation_only=True).audit(rest_records=rest,ws_records=ws,source_hashes={'fixture':'a'*64})

def test_nearest_prior_compares_all_levels_and_depth():
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','collected_at':'2026-10-01T09:00:00.1+09:00','bids':[{'price':'1.0','quantity':'10'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    ws=[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T09:00:01+09:00','received_at':'2026-10-01T09:00:01.1+09:00','bids':[{'price':'1.0','quantity':'10'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    r=audit(rest,ws)
    assert r['counts']['nearest_prior']==1
    assert r['counts']['price_equal']==10 and r['counts']['quantity_equal']==10

def test_price_and_quantity_differences_are_separate():
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','bids':[{'price':'1.0','quantity':'10'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    ws=[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T09:00:01+09:00','bids':[{'price':'1.05','quantity':'12'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    r=audit(rest,ws)
    assert r['counts']['price_different']==5
    assert r['counts']['quantity_different']==5
    assert r['counts']['price_equal']==5 and r['counts']['quantity_equal']==5

def test_zero_book_levels_are_not_counted_as_price_equal():
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','bids':[{'price':'0','quantity':'0'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    ws=[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T09:00:01+09:00','bids':[{'price':'0','quantity':'0'}]*5,'asks':[{'price':'1.1','quantity':'11'}]*5}]
    r=audit(rest,ws)
    assert r['counts']['price_both_empty']==5
    assert r['counts']['price_equal']==5

def test_future_only_no_source_and_cross_day_are_separate():
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00'}]
    ws=[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T08:00:00+09:00'}, {'symbol':'O2','trading_date':'20261001','record_id':'W2','source_timestamp_candidate':'2026-10-01T09:00:00+09:00'}, {'symbol':'O1','trading_date':'20261002','record_id':'W3','source_timestamp_candidate':'2026-10-02T09:00:00+09:00'}]
    r=audit(rest,ws)
    assert r['counts']['future_only']==1 and r['counts']['no_rest_source']==2

def test_timezone_opt_in_and_hash_determinism():
    try: ValidationOnlyRestWsOrderBookDepthAuditor()
    except ValueError as exc: assert 'OPT_IN_REQUIRED' in str(exc)
    else: raise AssertionError('validation-only opt-in missing')
    a=([{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00'}],[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T09:00:01+09:00'}])
    assert audit(*a)['report_sha256']==audit(*a)['report_sha256']
    try: audit([], [{'symbol':'O1','trading_date':'20261001','source_timestamp_candidate':'2026-10-01T09:00:00'}])
    except ValueError as exc: assert 'TIMEZONE_REQUIRED' in str(exc)
    else: raise AssertionError('naive timestamp accepted')


def test_missing_price_and_quantity_are_not_misclassified_as_empty():
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','bids':[{'price':None,'quantity':None}]+[{'price':'1','quantity':'2'}]*4,'asks':[{'price':'1.1','quantity':'3'}]*5}]
    ws=[{'symbol':'O1','trading_date':'20261001','record_id':'W1','source_timestamp_candidate':'2026-10-01T09:00:01+09:00','bids':[{'price':None,'quantity':None}]+[{'price':'1','quantity':'2'}]*4,'asks':[{'price':'1.1','quantity':'3'}]*5}]
    r=audit(rest,ws)
    assert r['counts']['price_missing']==1
    assert r['counts']['price_one_empty']==0
    assert r['counts']['quantity_missing']==1
