from application.composition.validation_only_rest_trade_cross_auditor import ValidationOnlyRestTradeCrossAuditor

def audit(trades, rest):
    return ValidationOnlyRestTradeCrossAuditor(validation_only=True).audit(trades=trades,rest=rest,source_hashes={'fixture':'a'*64})

def test_nearest_prior_and_receive_proxy_are_separated():
    trades=[{'symbol':'O1','trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00','received_at':'2026-10-01T09:00:00.1+09:00','last_price':'1.00','bid_price':'0.95','ask_price':'1.05','payload_sha256':'b'*64}]
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp':'2026-10-01T09:00:01+09:00','collected_at':'2026-10-01T09:00:01.1+09:00','last_price':'1.00','bid_price':'0.95','ask_price':'1.05'}, {'symbol':'O1','trading_date':'20261001','record_id':'R2','source_timestamp':None,'collected_at':'2026-10-01T09:00:02+09:00','last_price':'1.01','bid_price':'0.95','ask_price':'1.06'}]
    r=audit(trades,rest)
    assert r['counts']['nearest_prior_source_time']==1
    assert r['counts']['nearest_prior_receive_time_proxy']==1
    assert r['counts']['all_three_equal']==1
    assert r['alignments'][1]['comparison_time_mode']=='COLLECTED_AT_RECEIVE_TIME_PROXY'
    assert r['authority_claimed'] is False and r['gate_release_permitted'] is False

def test_future_only_and_no_source_are_distinct():
    trades=[{'symbol':'O1','trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T09:02:00+09:00','received_at':'2026-10-01T09:02:01+09:00'}]
    rest=[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp':'2026-10-01T09:00:00+09:00'}, {'symbol':'O2','trading_date':'20261001','record_id':'R2','source_timestamp':'2026-10-01T09:00:00+09:00'}]
    r=audit(trades,rest)
    assert r['counts']['future_trade_only']==1 and r['counts']['no_trade_source']==1

def test_missing_prices_do_not_invent_equality():
    r=audit([{'symbol':'O1','trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00'}],[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp':'2026-10-01T09:00:01+09:00'}])
    assert r['counts']['missing_rest_price']==1
    assert r['counts']['all_three_equal']==0

def test_timezones_required_and_opt_in_required():
    try: audit([{'symbol':'O1','source_timestamp_candidate':'2026-10-01T09:00:00'}],[])
    except ValueError as exc: assert 'TIMEZONE_REQUIRED' in str(exc)
    else: raise AssertionError('naive timestamp accepted')
    try: ValidationOnlyRestTradeCrossAuditor()
    except ValueError as exc: assert 'OPT_IN_REQUIRED' in str(exc)
    else: raise AssertionError('validation-only opt-in missing')

def test_report_hash_is_deterministic():
    a=([{'symbol':'O1','trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T09:00:00+09:00'}],[{'symbol':'O1','trading_date':'20261001','record_id':'R1','source_timestamp':'2026-10-01T09:00:01+09:00'}])
    assert audit(*a)['report_sha256']==audit(*a)['report_sha256']


def test_previous_trading_day_trade_is_never_used_as_anchor():
    trades=[{'symbol':'O1','trading_date':'20261001','record_id':'T1','source_timestamp_candidate':'2026-10-01T15:00:00+09:00','received_at':'2026-10-01T15:00:01+09:00'}]
    rest=[{'symbol':'O1','trading_date':'20261002','record_id':'R1','source_timestamp':'2026-10-02T09:00:00+09:00'}]
    r=audit(trades,rest)
    assert r['counts']['no_trade_source']==1
    assert r['counts']['nearest_prior_source_time']==0
