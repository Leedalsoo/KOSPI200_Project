from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import pytest
from hashlib import sha256
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import (
    attach_standard_automated_loop,
)
from contracts.futures_contract_spec import FuturesProductType
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.option.option_master import InMemoryOptionContractMaster
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources


def _loop(strategy_key: tuple[str, str], run_id: str):
    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=InMemoryOptionContractMaster(auto_load_kis_source=False),
        initial_capital=1_000_000_000.0,
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


def test_track4_mini_futures_runtime_routes_fills_and_closes_flat() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-FUTURES-RUNTIME-E2E")
    bridge = loop.multi_leg_bridge
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
    identity = plan.legs[0].instrument_identity
    assert identity.product_type is FuturesProductType.MINI
    assert identity.contract_multiplier == Decimal(50000)

    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    bridge.bundle.market._futures_price = Decimal("1000")
    vssf.order_book.update_bid_ask(1000, 1000, identity.instrument_id)

    def freshness(_plan, _leg, resolved_identity, command):
        observed_at = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S4_SYNTHETIC_DERIVED_SCENARIO",
            policy_version="S4-MINI-RUNTIME-FAULT-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="S4-SYNTHETIC-VIRTUAL",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{observed_at.isoformat()}|{resolved_identity.instrument_id}|S4".encode()
            ).hexdigest(),
        )

    bridge.freshness_verdict_provider = freshness
    entry = bridge.execute(plan)
    assert entry.approved_legs == entry.routed_legs == 1
    assert entry.filled_legs == 5
    assert entry.group_complete is True
    assert entry.reports[0].status == "FILLED"
    assert entry.reports[0].filled_quantity == 5
    assert entry.reports[0].execution_id
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].instrument_id == identity.instrument_id
    assert lots[0].contract_multiplier == Decimal(50000)
    assert lots[0].instrument_identity == identity
    assert vssf.account.positions[identity.instrument_id]["qty"] == 5

    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track4_gamma_scalping",
        purpose="S4_VALIDATION_CLOSE",
        asset_type="FUTURES",
    )
    close = bridge.execute(close_plan)
    assert close.approved_legs == close.routed_legs == 1
    assert close.filled_legs == 5
    assert close.group_complete is True
    assert close.reports[0].status == "FILLED"
    assert close.reports[0].filled_quantity == 5
    assert bridge.position_lot_store.open_lots() == ()
    remaining_position = vssf.account.positions.get(identity.instrument_id)
    assert remaining_position is None or int(remaining_position.get("qty", 0)) == 0
    assert close.position_flat is True


def test_track4_standard_futures_identity_is_rejected_before_vssf_submission() -> None:
    loop = _loop(("track4_gamma_scalping", "1.0"), "S4-MINI-IDENTITY-FAULT-INJECTION")
    bridge = loop.multi_leg_bridge
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
    valid_identity = plan.legs[0].instrument_identity
    standard_identity = replace(
        valid_identity,
        product_type=FuturesProductType.STANDARD,
        contract_multiplier=Decimal(250000),
    )
    invalid_leg = replace(plan.legs[0], instrument_identity=standard_identity)
    invalid_plan = replace(plan, legs=(invalid_leg,))
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    before = vssf.metrics["order_commands"]

    with pytest.raises(ValueError, match="TRACK4_MINI_FUTURES_IDENTITY_REQUIRED"):
        bridge.execute(invalid_plan)

    assert vssf.metrics["order_commands"] == before == 0
    assert bridge.position_lot_store.open_lots() == ()
