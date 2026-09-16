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
