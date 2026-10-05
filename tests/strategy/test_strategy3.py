from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage, Track3MarketInput

def test_strategy3_market_regime_requires_authoritative_input():
    try:
        Track3StatisticalArbitrage.detect_market_regime(Track3MarketInput(regime=None),vol_ratio=1.0,price_change_rate=0,bid_ask_spread=0,gap_pct=0)
    except ValueError as e:
        assert str(e)=="TRACK3_MARKET_REGIME_COMMON_ANALYTICS_REQUIRED"
    else:
        raise AssertionError("expected fail-closed regime error")

def test_strategy3_execution_signal_has_futures_proposal():
    signal=Track3StatisticalArbitrage()._signal("EXECUTE_STAT_ARB","SHORT_SPREAD","test",qty=1)
    assert signal.execution_proposal.asset_type=="FUTURES"
    assert signal.execution_proposal.side=="SELL"
