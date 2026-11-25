from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.analytics import AnalyticsStatus
from contracts.types import MarketState
from core.strategy.contracts import UnavailableStrategyPayload
from core.strategy.track4_gamma_scalping import Track4MarketInput
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource


MANIFEST_PATH = Path(__file__).parents[1] / "fixtures/track4/synthetic_s4_greeks_runtime_v1.json"


class _SyntheticTrack4GreeksSource(KISTrack4GreeksRealtimeSource):
    source_name = "SYNTHETIC:DERIVED_SCENARIO"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))


def _frame(instrument_id: str, greeks: dict[str, str]) -> str:
    values = [""] * 58
    values[0] = instrument_id
    values[1] = "101500"
    values[28] = greeks["delta"]
    values[29] = greeks["gamma"]
    values[31] = greeks["theta_raw"]
    values[33] = greeks["iv_raw"]
    return "0|H0IOCNT0|1|" + "^".join(values)


def _tick(instrument_id: str, observed_at: datetime, *, seq: int, last: str, strike: str = "350"):
    return ReferenceCanonicalMarketTick(
        timestamp=observed_at.isoformat(),
        underlying_price=Decimal("350"),
        strike_price=Decimal(strike),
        last_price=Decimal(last),
        seq_id=seq,
        expiry="20261210",
        symbol=instrument_id,
        instrument_id=instrument_id,
    )


def _build_context(instrument_id: str, observed_at: datetime, source: _SyntheticTrack4GreeksSource):
    ticks = (
        _tick(instrument_id, observed_at - timedelta(seconds=1), seq=1, last="10.0"),
        _tick(instrument_id, observed_at, seq=2, last="10.1"),
    )
    market = SimpleNamespace(
        recent_ticks=list(ticks),
        underlying_history=[],
        scenario=SimpleNamespace(active_config=lambda: {}),
    )
    runtime_inputs = StandardRuntimeInputProvider(
        market,
        run_id="SYNTHETIC-S4-GREEKS-RUNTIME",
        track4_greeks_provider=source,
        strategy_keys=("track4_gamma_scalping",),
    )
    market_state = MarketState(as_of=observed_at, ticks={instrument_id: ticks[-1]}, quality={})
    account = SimpleNamespace(balances={
        "available_cash": "1000000",
        "realized_pnl": "0",
        "unrealized_pnl": "0",
    })
    return runtime_inputs.build(ticks[-1], market_state, account)["track4_gamma_scalping"]


def test_synthetic_h0iocnt0_greeks_reach_standard_track4_strategy_input_without_promoting_theta_units() -> None:
    manifest = _manifest()
    assert manifest["validation_only"] is True
    assert manifest["runtime_use"] == "PROHIBITED_OUTSIDE_VALIDATION"
    assert manifest["provenance"] == "SYNTHETIC:DERIVED_SCENARIO"

    observed_at = datetime.fromisoformat(manifest["observed_at"])
    instrument_id = manifest["instrument_id"]
    source = _SyntheticTrack4GreeksSource()
    source_provider = source.accept_frame(_frame(instrument_id, manifest["greeks"]), observed_at=observed_at)

    assert source_provider is not None
    assert source_provider.snapshot.source == manifest["provenance"]
    assert source_provider.snapshot.instrument_id == instrument_id
    assert source_provider.snapshot.observed_at == observed_at.isoformat()

    context = _build_context(instrument_id, observed_at, source)

    assert isinstance(context.input.payload, Track4MarketInput)
    assert context.input.payload.current_delta == Decimal(manifest["greeks"]["delta"])
    assert context.input.payload.current_gamma == Decimal(manifest["greeks"]["gamma"])
    # H0IOCNT0 theta unit/period is not established by the current contract.
    assert context.input.payload.current_theta is None
    assert context.analytics.as_of == observed_at
    assert context.analytics.metrics["options.delta"].value == Decimal(manifest["greeks"]["delta"])
    assert context.analytics.metrics["options.delta"].status is AnalyticsStatus.AVAILABLE
    assert context.analytics.metrics["options.gamma"].value == Decimal(manifest["greeks"]["gamma"])
    assert context.analytics.metrics["options.gamma"].status is AnalyticsStatus.AVAILABLE
    assert context.analytics.metrics["options.theta"].value is None
    assert context.analytics.metrics["options.theta"].status is AnalyticsStatus.UNAVAILABLE


def test_synthetic_greeks_wrong_instrument_or_prior_tick_do_not_reach_standard_track4_input() -> None:
    manifest = _manifest()
    observed_at = datetime.fromisoformat(manifest["observed_at"]) + timedelta(minutes=1)
    option_a = manifest["instrument_id"]
    option_b = "SYNTHETIC_CONTRACT:TRACK4-PUT-350-20261210"

    for greek_instrument, greek_at, tick_instrument in (
        (option_a, observed_at, option_b),
        (option_a, observed_at - timedelta(seconds=1), option_a),
    ):
        source = _SyntheticTrack4GreeksSource()
        source.accept_frame(_frame(greek_instrument, manifest["greeks"]), observed_at=greek_at)
        context = _build_context(tick_instrument, observed_at, source)
        assert isinstance(context.input.payload, UnavailableStrategyPayload)
        assert context.input.payload.reason == "TRACK4_COMMON_ANALYTICS_INPUTS_UNAVAILABLE"
