from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import (
    attach_standard_automated_loop,
)
from contracts.futures_contract_spec import FuturesProductType
from core.option.option_master import InMemoryOptionContractMaster
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources


def _loop(strategy_key: tuple[str, str], run_id: str):
    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=InMemoryOptionContractMaster(auto_load_kis_source=False),
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    return attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(strategy_key,),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )


def test_track4_virtual_runtime_binds_synthetic_mini_futures_identity() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-FUTURES-IDENTITY-VALIDATION")
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        requested_price=None,
        side="SELL",
        track_id="track4_gamma_scalping",
        tag_id="GAMMA_REBALANCE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(
            strategy_id="track4_gamma_scalping",
            market_state=SimpleNamespace(ticks={"synthetic": tick}),
        ),
        result=SimpleNamespace(execution_proposal=proposal),
    )
    canonical = SimpleNamespace(
        side=SimpleNamespace(value="SELL"),
        qty=5,
        tag_id="GAMMA_REBALANCE",
        track_id="track4_gamma_scalping",
    )

    plan = loop.multi_leg_plan_resolver(evaluation, canonical)

    assert plan is not None
    assert plan.strategy_id == "track4_gamma_scalping"
    assert len(plan.legs) == 1
    leg = plan.legs[0]
    assert leg.side == "SELL"
    assert leg.quantity == 5
    assert leg.instrument_identity.product_type is FuturesProductType.MINI
    assert leg.instrument_identity.contract_multiplier == Decimal(50000)
    assert leg.instrument_identity.identity_source.startswith("SYNTHETIC:")


def test_other_synthetic_futures_routes_keep_standard_contract_spec() -> None:
    loop = _loop(("TRACK1_TAIL_DEFENSE", "1.2.0"), "SYNTHETIC-STANDARD-FUTURES-IDENTITY")
    tick = SimpleNamespace(
        underlying_symbol="SYNTHETIC_KOSPI200",
        symbol="SYNTHETIC_KOSPI200",
        instrument_id="SYNTHETIC_KOSPI200",
        timestamp="2026-10-08T09:00:49+09:00",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="FUTURES",
        requested_price=None,
        side="BUY",
        track_id="TRACK1_TAIL_DEFENSE",
        tag_id="FUTURES_HEDGE",
        option_type=None,
        strike=None,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="TRACK1_TAIL_DEFENSE"),
        result=SimpleNamespace(execution_proposal=proposal),
    )

    identity = loop.identity_provider(evaluation, tick, asset_type="FUTURES")

    assert identity.product_type is FuturesProductType.STANDARD
    assert identity.contract_multiplier == Decimal(250000)
