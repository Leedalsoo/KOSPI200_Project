from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.bootstrap import create_virtual_runtime_bootstrap
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from contracts.futures_contract_spec import FuturesProductType
from core.option.option_master import InMemoryOptionContractMaster
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources


def test_s4_runtime_tick_identity_is_not_propagated_to_plan_attempt_id() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures" / "track4"
        / "synthetic_s4_attempt_id_upstream_propagation_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["validation_only"] is True
    assert fixture["runtime_use"] == "PROHIBITED_OUTSIDE_VALIDATION"
    scenario = fixture["scenario"]

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=InMemoryOptionContractMaster(auto_load_kis_source=False),
        initial_capital=1_000_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=((scenario["strategy_id"], "1.0"),),
        run_id=scenario["run_id"],
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )

    def resolve(tick_sequence: int, timestamp: str):
        tick = SimpleNamespace(
            underlying_symbol="SYNTHETIC_KOSPI200",
            symbol="SYNTHETIC_KOSPI200",
            instrument_id="SYNTHETIC_KOSPI200",
            timestamp=timestamp,
        )
        proposal = StrategyExecutionProposal(
            proposed_quantity=int(scenario["quantity"]),
            asset_type="FUTURES",
            requested_price=None,
            side=scenario["side"],
            track_id=scenario["strategy_id"],
            tag_id=scenario["tag_id"],
            option_type=None,
            strike=None,
        )
        context = SimpleNamespace(
            strategy_id=scenario["strategy_id"],
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        )
        runtime_context = RuntimeExecutionContext(
            tick_sequence=tick_sequence,
            local_sequence=1,
        )
        evaluation = RuntimeStrategyEvaluation(
            context=context,
            result=SimpleNamespace(execution_proposal=proposal),
            local_sequence=1,
            runtime_context=runtime_context,
        )
        canonical = SimpleNamespace(
            signal_id=runtime_context.signal_id(scenario["strategy_id"]),
            side=SimpleNamespace(value=scenario["side"]),
            qty=int(scenario["quantity"]),
            tag_id=scenario["tag_id"],
            track_id=scenario["strategy_id"],
        )
        plan = loop.multi_leg_plan_resolver(evaluation, canonical)
        assert plan is not None
        return runtime_context, proposal, plan

    first_context, first_proposal, first_plan = resolve(
        int(scenario["first_tick_sequence"]), scenario["first_tick_timestamp"]
    )
    second_context, second_proposal, second_plan = resolve(
        int(scenario["second_tick_sequence"]), scenario["second_tick_timestamp"]
    )

    assert not hasattr(first_proposal, "attempt_id")
    assert not hasattr(second_proposal, "attempt_id")
    assert first_context.signal_id(scenario["strategy_id"]) != second_context.signal_id(scenario["strategy_id"])
    assert first_context.client_order_id(scenario["strategy_id"]) != second_context.client_order_id(scenario["strategy_id"])
    assert first_plan.group_id == second_plan.group_id == (
        f'{scenario["run_id"]}-{scenario["strategy_id"]}-FUTURES-HEDGE'
    )
    assert first_plan.legs[0].leg_id == second_plan.legs[0].leg_id == "futures-gamma_rebalance"
    assert first_plan.attempt_id is None
    assert second_plan.attempt_id is None
    identity = first_plan.legs[0].instrument_identity
    assert identity is not None
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == 50000
    assert loop.multi_leg_bridge._client_order_id(first_plan, first_plan.legs[0], identity) == (
        loop.multi_leg_bridge._client_order_id(second_plan, second_plan.legs[0], identity)
    )
    assert fixture["expected_observations"]["runtime_tick_signal_identity_changes"] is True
    assert fixture["expected_observations"]["strategy_execution_proposal_has_no_attempt_id_field"] is True
    assert fixture["expected_observations"]["resolver_plan_attempt_id_remains_none"] is True
    assert fixture["expected_observations"]["tick_identity_is_not_injected_into_bridge_plan_identity"] is True
    assert fixture["expected_observations"]["no_order_submission_performed"] is True
