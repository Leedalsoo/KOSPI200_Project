from decimal import Decimal
from core.strategy.track5_gap_divergence import Track5GapDivergence
from types import SimpleNamespace

def test_strategy5_effective_threshold_is_stricter_in_high_vol():
    s=Track5GapDivergence()
    assert s.effective_z_threshold("HIGH_VOL")==s.effective_z_threshold("NOISE_CHOPPY")==Decimal("1.8")

def test_strategy5_missing_analytics_fails_closed():
    s=Track5GapDivergence()
    assert s.evaluate(SimpleNamespace(strategy_id=s.strategy_id,analytics=None,input=None))==()
