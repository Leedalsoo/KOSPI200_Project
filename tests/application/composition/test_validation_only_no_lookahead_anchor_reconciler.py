from decimal import Decimal
import pytest
from application.composition.validation_only_no_lookahead_anchor_reconciler import (
 nearest_prior_anchor, nearest_same_time_option_spread, apply_prior_underlying_anchor,
 apply_same_time_spread_proxy, find_future_donors, mark_nonfuture_underlying_anchor,
)


def base_row():
 return {'tick':{'timestamp':'2026-10-13T08:47:35+09:00','underlying_price':1048.2,'underlying_observed_hour':'085000','underlying_source':'SYNTHETIC:KRX_SHOCK_V4_NEAREST_SPOT','strike_price':1000.0,'option_type':'CALL','expiry':'20261112','bid_price':35.5,'ask_price':37.45},'scenario_metadata':{'source_observed_at':'2026-10-13T08:47:35+09:00','field_provenance':{'underlying_price':{'method':'nearest','donor_timestamp':'2026-10-13T08:50:00+09:00'},'ask_price':{'method':'future_spread','donor':{'timestamp':'2026-10-13T08:47:50+09:00'}}}}}

def test_nearest_prior_ignores_future_and_selects_latest_prior():
 anchors=[{'timestamp':'2026-10-13T08:45:00+09:00','underlying_price':1048.2},{'timestamp':'2026-10-13T08:50:00+09:00','underlying_price':1048.0}]
 assert nearest_prior_anchor('2026-10-13T08:47:35+09:00',anchors)['timestamp'].endswith('08:45:00+09:00')

def test_no_prior_anchor_is_explicit():
 with pytest.raises(ValueError,match='NO_SAME_DAY_PRIOR_ANCHOR'):
  nearest_prior_anchor('2026-10-13T08:44:00+09:00',[{'timestamp':'2026-10-13T08:45:00+09:00'}])

def test_nearest_same_time_same_expiry_right_spread_selected():
 candidates=[{'timestamp':'2026-10-13T08:45:00+09:00','expiry':'20261112','option_type':'CALL','strike_price':1032.5,'bid_price':41.65,'ask_price':42.15}, {'timestamp':'2026-10-13T08:45:15+09:00','expiry':'20261112','option_type':'CALL','strike_price':1000,'bid_price':35,'ask_price':36}]
 got=nearest_same_time_option_spread(target_timestamp='2026-10-13T08:45:00+09:00',target_expiry='20261112',target_option_type='CALL',target_strike=1000,candidates=candidates)
 assert got['strike_price']==1032.5

def test_future_anchor_replaced_by_prior_spot_and_original_preserved():
 x=base_row(); a={'timestamp':'2026-10-13T08:45:00+09:00','underlying_price':1048.2175}
 out=apply_prior_underlying_anchor(x,a,source_manifest_sha256='m',source_file_sha256='f')
 assert out['tick']['underlying_price']==1048.2175
 assert out['scenario_metadata']['field_provenance']['underlying_price']['distance_seconds']==155
 assert out['scenario_metadata']['original_future_underlying_anchor']['donor_timestamp']=='2026-10-13T08:50:00+09:00'

def test_same_time_spread_proxy_replaces_future_ask_with_tick_aligned_synthetic_ask():
 x=base_row(); x['tick']['timestamp']='2026-10-13T08:45:00+09:00'; x['scenario_metadata']['source_observed_at']='2026-10-13T08:45:00+09:00'
 donor={'timestamp':'2026-10-13T08:45:00+09:00','expiry':'20261112','option_type':'CALL','strike_price':1032.5,'bid_price':41.65,'ask_price':42.15}
 out=apply_same_time_spread_proxy(x,donor,source_manifest_sha256='m',source_file_sha256='f')
 assert out['tick']['ask_price']==36.0
 assert out['scenario_metadata']['ask_price_is_synthetic_proxy'] is True
 assert out['scenario_metadata']['original_future_ask_anchor']['donor']['timestamp']=='2026-10-13T08:47:50+09:00'

def test_future_donor_scanner_detects_original_future_sources():
 x=base_row(); found=find_future_donors(x)
 assert {z['field'] for z in found}=={'underlying_price','ask_price'}


def test_existing_prior_or_exact_anchor_is_labeled_at_or_before_target():
 x=base_row(); x['scenario_metadata']['field_provenance']['underlying_price']['donor_timestamp']='2026-10-13T08:47:35+09:00'
 out=mark_nonfuture_underlying_anchor(x,source_manifest_sha256='m',source_file_sha256='f')
 assert out['tick']['underlying_source']=='SYNTHETIC:KRX_SHOCK_V4_AT_OR_BEFORE_TARGET_SPOT'
 assert out['scenario_metadata']['field_provenance']['underlying_price']['distance_seconds']==0

def test_future_anchor_cannot_be_marked_nonfuture_without_replacement():
 with pytest.raises(ValueError,match='FUTURE_UNDERLYING_ANCHOR_REQUIRES_REPLACEMENT'):
  mark_nonfuture_underlying_anchor(base_row(),source_manifest_sha256='m',source_file_sha256='f')
