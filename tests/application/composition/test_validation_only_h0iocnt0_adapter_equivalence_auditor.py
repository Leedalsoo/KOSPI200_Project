from decimal import Decimal
import pytest
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_h0iocnt0_adapter_equivalence_auditor import audit_adapter_frame


def record(symbol='B01610A34',hour='085159',last='14.60',volume='36',ask='14.65',bid='14.55',iv='0.123'):
    x=['0']*58; x[0]=symbol; x[1]=hour; x[2]=last; x[10]=volume; x[33]=iv; x[41]=ask; x[42]=bid; return x

def frame(records):
    return '0|H0IOCNT0|'+f'{len(records):03d}'+'|'+'^'.join(v for row in records for v in row)

def test_adapter_matches_all_selected_fields_for_multiple_records():
    payload=frame([record(volume='36'),record(volume='35',iv='')])
    adapted=KISIndexOptionMarketWebSocketAdapter().adapt_many(payload,source='KIS:H0IOCNT0')
    result=audit_adapter_frame(payload,adapted,source='KIS:H0IOCNT0')
    assert result['raw_records']==2 and result['adapter_records']==2
    assert all(result[f'{field}_mismatches']==0 for field in ('shrn_iscd','observed_hour','last_price','volume','ask_price','bid_price','implied_volatility'))
    assert result['source_mismatches']==0

def test_adapter_count_mismatch_is_not_silently_accepted():
    payload=frame([record()])
    adapted=KISIndexOptionMarketWebSocketAdapter().adapt_many(payload,source='KIS:H0IOCNT0')
    with pytest.raises(ValueError,match='RECORD_COUNT_MISMATCH'):
        audit_adapter_frame(payload,adapted*2,source='KIS:H0IOCNT0')

def test_bad_58_field_boundary_is_rejected():
    payload=frame([record()])+'^EXTRA'
    with pytest.raises(ValueError,match='58_FIELD_LAYOUT_INVALID'):
        audit_adapter_frame(payload,(),source='KIS:H0IOCNT0')

def test_adapter_field_mismatch_is_reported():
    payload=frame([record(last='14.60')])
    adapted=KISIndexOptionMarketWebSocketAdapter().adapt_many(payload,source='KIS:H0IOCNT0')
    class Wrong:
        shrn_iscd=adapted[0].shrn_iscd; observed_hour=adapted[0].observed_hour
        last_price=Decimal('14.61'); volume=adapted[0].volume; ask_price=adapted[0].ask_price
        bid_price=adapted[0].bid_price; implied_volatility=adapted[0].implied_volatility; source='KIS:H0IOCNT0'
    result=audit_adapter_frame(payload,[Wrong()],source='KIS:H0IOCNT0')
    assert result['last_price_mismatches']==1
