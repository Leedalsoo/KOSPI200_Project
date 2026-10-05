from contracts.track4_runtime_input_provider import Track4RuntimeInputProvider, Track4RuntimeInputReadiness


def test_readiness_is_incomplete_when_sources_missing():
    r = Track4RuntimeInputReadiness(True, True, True, False, False)
    assert r.is_complete is False


def test_readiness_is_complete_only_when_all_authoritative():
    r = Track4RuntimeInputReadiness(True, True, True, True, True)
    assert r.is_complete is True


def test_port_declares_all_track4_boundaries():
    required = {
        'readiness', 'observed_at', 'current_price', 'active_vol', 'base_vol',
        'current_pnl', 'current_equity', 'price_history', 'current_delta',
        'current_gamma', 'premium_spent', 'accumulated_gamma_profit', 'theta_decay_cost'
    }
    assert required.issubset(set(Track4RuntimeInputProvider.__dict__))


def test_virtual_runtime_snapshot_accepts_callable_track4_greeks_snapshot():
    from datetime import datetime
    from types import SimpleNamespace
    from decimal import Decimal
    from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
    from environments.virtual.market.canonical import ReferenceCanonicalMarketTick

    tick = ReferenceCanonicalMarketTick(
        timestamp="2025-01-02T09:00:00",
        underlying_price=Decimal("1100"),
        underlying_symbol="KOSPI200_SYNTHETIC",
        strike_price=Decimal("1100"),
        option_type="CALL",
        contract_multiplier=Decimal("250000"),
        bid_price=Decimal("10"),
        ask_price=Decimal("11"),
        last_price=Decimal("10.5"),
        volume=1,
        seq_id=1,
        expiry="20250116",
        symbol="SYN-1",
        option_observed_hour="09:00",
        option_source="SYNTHETIC",
        instrument_id="SYN-1",
    )
    class Greeks:
        def snapshot(self):
            return SimpleNamespace(observed_at="2025-01-02T09:00:00")
        def current_delta(self):
            return Decimal("0.5")
        def current_gamma(self):
            return Decimal("0.01")

    market = SimpleNamespace(
        recent_ticks=[tick],
        underlying_history=[(datetime.fromisoformat(tick.timestamp), Decimal("1100"))],
        scenario=SimpleNamespace(active_config=lambda: {}),
    )
    data = VirtualRuntimeDataProvider(market, track4_greeks_provider=Greeks()).snapshot(tick)
    assert data.option_delta == Decimal("0.5")
    assert data.option_gamma == Decimal("0.01")
