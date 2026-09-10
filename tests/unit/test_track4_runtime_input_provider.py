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
