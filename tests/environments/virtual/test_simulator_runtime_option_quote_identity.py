from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


def test_replay_quote_store_preserves_each_synthetic_contract_identity():
    market = VirtualMarketSimulatorRuntime()
    timestamp = "2026-11-02T10:00:00+09:00"
    first = "SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5"
    second = "SYNTHETIC_CONTRACT:SYNTH-S6-2-20261102-PUT-487.5"
    common = dict(option_type="PUT", strike=487.5, expiry="20261102", timestamp=timestamp,
                  contract_multiplier=250000, source="SYNTHETIC:DERIVED_SCENARIO")
    market.register_replay_option_quote(symbol=first, bid=0.8, ask=0.9, last=0.85, **common)
    market.register_replay_option_quote(symbol=second, bid=0.5, ask=0.6, last=0.55, **common)

    exact = market.option_quotes_by_instrument_id
    assert exact[first]["bid"] == 0.8
    assert exact[second]["bid"] == 0.5
    assert exact[first]["source"] == "SYNTHETIC:DERIVED_SCENARIO"
    # The legacy strike-keyed view remains backward-compatible and is not used
    # for synthetic S6 identity resolution.
    legacy = market.option_quotes[("PUT", 487.5, "20261102")]
    assert set(legacy) == {"bid", "ask", "last", "timestamp", "contract_multiplier"}
