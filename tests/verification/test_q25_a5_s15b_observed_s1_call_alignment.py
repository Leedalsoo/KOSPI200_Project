from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.strategy_hub.hub import StrategyHub
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from contracts.types import CanonicalMarketTick
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from environments.high_speed.validation_only_s15b_observed_option_adapter import (
    S15BObservedOptionMarketAdapter,
    S15BObservedOptionMarketError,
)
from environments.high_speed.validation_only_s15b_option_proposal_resolver import S15BOptionProposalResolver

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_observed_s1_call_alignment/manifest.json"
STRATEGY_ID = "TRACK1_TAIL_DEFENSE"
STRATEGY_KEY = (STRATEGY_ID, "1.2.0")
CONTRACT_KEY = "S1_SHORT_CALL_887_5"


def _natural_signal():
    adapter = S15BObservedOptionMarketAdapter(MANIFEST, project_root=ROOT)
    strategy = Track1TailDefense()
    adapter.apply_to_strategy(strategy)
    registry = StrategyRegistry()
    registry.register(strategy)
    hub = StrategyHub(registry, (STRATEGY_KEY,))
    context = adapter.build_strategy_context()
    result = hub.run({STRATEGY_ID: context})
    assert not result.failures
    return adapter, result.signals


def test_strategy_hub_natural_signal_resolves_to_exact_observed_option_contract():
    adapter, signals = _natural_signal()
    assert len(signals) == 1
    signal = signals[0]
    proposal = signal.execution_proposal
    assert signal.direction == "SELL"
    assert proposal.asset_type == "OPTION"
    assert proposal.side == "SELL"
    assert proposal.option_type == "CALL"
    assert proposal.strike == Decimal("887.5")
    assert proposal.proposed_quantity == 1
    assert proposal.tag_id == "S1_SHORT_ACCUMULATION_CALL_000001"

    identity = adapter.identity(CONTRACT_KEY)
    quote = adapter.quote(CONTRACT_KEY)
    freshness = adapter.freshness(CONTRACT_KEY)
    book = adapter.order_book(CONTRACT_KEY)
    assert identity.symbol == "B01611887"
    assert identity.expiry == "20261112"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("887.50")
    assert identity.contract_multiplier == Decimal("250000")
    assert quote.bid == Decimal("35.00")
    assert quote.ask == Decimal("37.65")
    assert quote.last == Decimal("36.325")
    assert freshness.status.value == "FRESH"
    assert freshness.policy_version == "S15B_OBSERVED_COLLECTOR_RECEIVE_TIME_VALIDATION_ONLY"
    assert book.source == "OBSERVED_KIS_VTS:H0IOASP0:VALIDATION_ONLY"
    assert len(book.ask_levels) == len(book.bid_levels) == 5

    plan = S15BOptionProposalResolver(adapter).resolve(
        proposal,
        scenario_contract_key=CONTRACT_KEY,
        group_id="S15B-OBSERVED-S1-CALL-8875",
    )
    assert plan.strategy_id == STRATEGY_ID
    assert plan.purpose == "S15B_VALIDATION_ONLY_SHORT_ACCUMULATION"
    assert plan.strategy_code_version == "1.2.0"
    assert plan.strategy_config_hash == adapter.manifest_sha256
    assert len(plan.legs) == 1
    leg = plan.legs[0]
    assert leg.side == "SELL"
    assert leg.quantity == 1
    assert leg.option_type == "CALL"
    assert leg.strike == Decimal("887.5")
    assert leg.instrument_identity == identity


def test_observed_orderbook_flows_into_virtual_runtime_data_provider():
    adapter = S15BObservedOptionMarketAdapter(MANIFEST, project_root=ROOT)
    quote = adapter.quote(CONTRACT_KEY)
    book_event = adapter.by_type["OPTION_ORDERBOOK"]
    received_at = __import__("datetime").datetime.fromisoformat(book_event["source"]["received_at"])
    received_kst = received_at.astimezone(timezone(timedelta(hours=9)))
    market = SimpleNamespace(
        recent_ticks=[SimpleNamespace(last_price=quote.last)],
        underlying_history=[],
        scenario=SimpleNamespace(active_config=lambda: {"base_volatility": 1.0, "shock_interval_days": 999999}),
    )
    tick = SimpleNamespace(
        timestamp=received_kst.isoformat(),
        last_price=quote.last,
        strike_price=Decimal("887.50"),
        seq_id=1,
        symbol="B01611887",
        underlying_symbol="KOSPI200",
        underlying_price=Decimal("876.54"),
        expiry="2026-11-12",
        option_type="CALL",
        validation_only=True,
        dte_trading_days=21,
        delta=None,
        gamma=None,
    )
    runtime_data = VirtualRuntimeDataProvider(market, option_orderbook_source=adapter).snapshot(tick)
    status = runtime_data.status["option_orderbook"]
    assert status.available is True
    assert status.fresh is True
    assert status.source == "OBSERVED_KIS_VTS:H0IOASP0:VALIDATION_ONLY"
    assert runtime_data.option_bid_qtys == (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("10"), Decimal("1"))
    assert runtime_data.option_ask_qtys == (Decimal("1"), Decimal("1"), Decimal("2"), Decimal("2"), Decimal("10"))


def test_option_resolver_fails_closed_on_contract_or_proposal_mismatch():
    adapter, signals = _natural_signal()
    resolver = S15BOptionProposalResolver(adapter)
    proposal = signals[0].execution_proposal
    with pytest.raises(S15BObservedOptionMarketError, match="S15B_SCENARIO_CONTRACT_KEY_UNKNOWN"):
        resolver.resolve(proposal, scenario_contract_key="UNMAPPED", group_id="bad-key")
    with pytest.raises(S15BObservedOptionMarketError, match="S15B_OPTION_PROPOSAL_SCENARIO_MISMATCH"):
        resolver.resolve(replace(proposal, strike=Decimal("885.0")), scenario_contract_key=CONTRACT_KEY, group_id="bad-strike")
