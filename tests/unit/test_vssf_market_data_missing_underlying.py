from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


def test_process_market_data_allows_missing_underlying_price():
    runtime = VirtualSecuritiesFirmRuntime()
    tick = ReferenceCanonicalMarketTick(
        timestamp='2026-09-21T05:44:13.922628+00:00', underlying_price=None,
        underlying_symbol='', underlying_observed_hour='', underlying_source='',
        strike_price=1075.0, option_type='PUT', contract_multiplier=250000.0,
        bid_price=22.0, ask_price=23.45, last_price=32.8, volume=0, seq_id=0,
        expiry='2026-10-08', symbol='C01610A29', option_observed_hour='',
        option_source='', underlying_sequence=0,
    )
    runtime.process_market_data(tick)
    assert runtime.order_book.bid == 22.0
    assert runtime.order_book.ask == 23.45
    assert runtime.account.positions == {}
