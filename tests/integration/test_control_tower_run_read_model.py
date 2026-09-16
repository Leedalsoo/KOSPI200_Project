from application.bootstrap import create_virtual_runtime_bootstrap


def test_control_tower_exposes_strategy_run_scenario_read_models():
    bootstrap = create_virtual_runtime_bootstrap()
    tower = bootstrap.control_tower_hub
    strategies = tower.strategy_read_model()["strategies"]
    scenarios = tower.scenario_read_model()
    run = tower.run_read_model()
    assert len(strategies) == 9
    assert all(item["strategy_id"] and item["version"] for item in strategies)
    assert scenarios["available_scenarios"]
    assert run["active"] is True
    assert run["run_id"] == bootstrap.run_context.run_id
    bootstrap.run_hub.close()


def test_control_tower_creates_new_run_with_selected_scenario_and_replay_boundary():
    bootstrap = create_virtual_runtime_bootstrap()
    tower = bootstrap.control_tower_hub
    strategy = tower.strategy_read_model()["strategies"][0]
    scenario = tower.scenario_read_model()["available_scenarios"][0]
    result = tower.create_run({
        "run_id": "CT-RUN-002",
        "environment": "virtual",
        "scenario": scenario,
        "strategy_keys": [[strategy["strategy_id"], strategy["version"]]],
        "initial_capital": 250_000_000.0,
    })
    assert result["run_id"] == "CT-RUN-002"
    assert result["scenario"] == scenario
    replay = tower.run_action("REPLAY")
    assert "run_id" in replay
    bootstrap.run_hub.close()


def test_run_historical_store_replay_and_broker_read_model(tmp_path):
    from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
    from environments.virtual.market.historical_market_store import HistoricalMarketStore
    from application.run_hub.contracts import RunContextFactory
    from application.run_hub.virtual_session_factory import create_virtual_run_session
    from application.composition.option_master_factory import create_production_option_master

    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-17T10:00:00.123", underlying_price=512.5,
        strike_price=510.0, option_type="CALL", contract_multiplier=250000.0,
        bid_price=3.20, ask_price=3.30, last_price=3.25, volume=120,
        seq_id=701, expiry="202610", symbol="201S11305",
    )
    store.append(tick, source="TEST_HISTORICAL")
    context = RunContextFactory().create(
        run_id="CT-HIST-001", environment="virtual",
        historical_source="TEST_HISTORICAL", historical_store_path=str(store.path), initial_capital=250_000_000.0,
    )
    session = create_virtual_run_session(context, create_production_option_master())
    from application.run_hub.hub import RunScenarioHub
    run_hub = RunScenarioHub()
    run_hub.adopt(session)
    session.control_tower_hub.attach_run_hub(run_hub)
    try:
        before = session.control_tower_hub.run_read_model()
        assert before["last_replay_tick"] is None
        replay = session.control_tower_hub.run_action("REPLAY")
        assert replay["replay_tick"]["seq_id"] == 701
        after = session.control_tower_hub.run_read_model()
        assert after["last_replay_tick"]["timestamp"] == tick.timestamp
        assert "account" in after and "margin" in after and "pnl" in after
        assert "execution_reports" in after
    finally:
        run_hub.close()
