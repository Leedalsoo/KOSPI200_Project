from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_s3_s4_input_adapter import (
    ValidationOnlyS3S4InputAdapter,
)
from application.strategy_hub.hub import StrategyHub
from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
from core.strategy.contracts import SignalKind, StrategyContext, StrategyInput
from core.strategy.registry import StrategyRegistry
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config/validation_only/q25_s3_s4/mini_futures_profile.v2.json"


def _adapter() -> tuple[dict, ValidationOnlyS3S4InputAdapter]:
    raw = PROFILE_PATH.read_bytes()
    expected = PROFILE_PATH.with_suffix(PROFILE_PATH.suffix + ".sha256").read_text(encoding="ascii").strip()
    assert hashlib.sha256(raw).hexdigest() == expected
    profile = json.loads(raw.decode("utf-8-sig"))
    for anchor in profile["source_anchors"]:
        path = ROOT / anchor["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == anchor["sha256"]
    return profile, ValidationOnlyS3S4InputAdapter(profile)


def _snapshot(run_id: str, as_of: datetime, values: dict[str, object]) -> AnalyticsSnapshot:
    metrics = {
        key: AnalyticsMetric(
            metric_key=key,
            value=value,
            status=AnalyticsStatus.AVAILABLE,
            unit="SYNTHETIC_VALIDATION_ONLY",
            as_of=as_of,
            calculation_version="Q25-S3-S4-HUB-VALIDATION-v1",
            provenance=("SYNTHETIC:DERIVED_SCENARIO",),
        )
        for key, value in values.items()
    }
    return AnalyticsSnapshot(
        run_id=run_id,
        instrument_identity=None,
        as_of=as_of,
        timeframe="tick",
        window=1,
        analytics_version="Q25-S3-S4-HUB-VALIDATION-v1",
        metrics=metrics,
    )


def _context(strategy_id: str, data: object, analytics: AnalyticsSnapshot) -> StrategyContext:
    return StrategyContext(
        market_state=None,
        strategy_id=strategy_id,
        input=StrategyInput(payload=data),
        analytics=analytics,
    )


def test_s3_natural_strategy_signal_and_close_cycle_runs_through_strategy_hub():
    profile, adapter = _adapter()
    data = adapter.build_track3_input()
    strategy = Track3StatisticalArbitrage(
        enabled=True,
        capital_gate_min=1.0,
        risk_limits_available=True,
    )
    registry = StrategyRegistry()
    registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    as_of = datetime.fromisoformat(profile["s4"]["observed_at"])
    base = {
        "spread.std": profile["s3"]["spread_std"],
        "volatility.ratio": 1.0,
        "microstructure.spread": 0.1,
        "price.change_rate": 0.0,
        "market.gap_pct": 0.0,
        "market.current_regime": "NORMAL",
        "cost.fees": 0.0,
        "portfolio.options_pnl": 0.0,
        "portfolio.premium_spent": 0.0,
    }
    entry_values = {**base, "spread.z_score": 2.5, "portfolio.current_pnl": 0.0}
    entry = hub.run({
        strategy.strategy_id: _context(
            strategy.strategy_id,
            data,
            _snapshot("S3-HUB-ENTRY", as_of, entry_values),
        )
    })
    assert entry.failures == ()
    assert len(entry.signals) == 1
    assert entry.signals[0].execution_proposal is not None
    assert entry.signals[0].execution_proposal.asset_type == "FUTURES"
    assert entry.signals[0].execution_proposal.tag_id == "EXECUTE_STAT_ARB"
    assert strategy.active_position == "SHORT_SPREAD"

    close_values = {**base, "spread.z_score": 0.1, "portfolio.current_pnl": 100000.0}
    close = hub.run({
        strategy.strategy_id: _context(
            strategy.strategy_id,
            data,
            _snapshot("S3-HUB-CLOSE", as_of, close_values),
        )
    })
    assert close.failures == ()
    assert len(close.signals) == 1
    assert close.signals[0].execution_proposal is not None
    assert close.signals[0].execution_proposal.tag_id == "CLOSE_STAT_ARB"
    hub.on_execution_result(
        strategy.strategy_id,
        "CLOSE_STAT_ARB",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.active_position is None
    assert strategy.active_group_id is None


def test_s4_natural_gamma_hedge_and_trailing_close_signals_run_through_strategy_hub():
    _profile, adapter = _adapter()
    data = adapter.build_track4_input()
    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=1,
        risk_limits_available=True,
    )
    registry = StrategyRegistry()
    registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    base = {
        "volatility.active": data.active_vol,
        "volatility.base": data.base_vol,
        "volatility.ratio": data.active_vol / data.base_vol,
        "options.delta": data.current_delta,
        "portfolio.equity": data.current_equity,
        "price.tick_deadband": Decimal(0),
        "portfolio.premium_spent": data.premium_spent,
    }
    entry_values = {**base, "portfolio.current_pnl": Decimal(50000)}
    entry = hub.run({
        strategy.strategy_id: _context(
            strategy.strategy_id,
            data,
            _snapshot("S4-HUB-ENTRY", data.observed_at, entry_values),
        )
    })
    assert entry.failures == ()
    execution_signals = tuple(signal for signal in entry.signals if signal.kind is SignalKind.EXECUTION)
    non_execution_signals = tuple(signal for signal in entry.signals if signal.kind is SignalKind.NON_EXECUTION)
    assert len(execution_signals) == 1
    assert execution_signals[0].execution_proposal is not None
    assert execution_signals[0].execution_proposal.asset_type == "FUTURES"
    assert execution_signals[0].execution_proposal.side == "SELL"
    assert execution_signals[0].execution_proposal.proposed_quantity == 5
    assert len(non_execution_signals) in (0, 1)
    assert strategy.state.active_hedge_qty == -5

    close_values = {**base, "portfolio.current_pnl": Decimal(40000)}
    close = hub.run({
        strategy.strategy_id: _context(
            strategy.strategy_id,
            data,
            _snapshot("S4-HUB-CLOSE", data.observed_at, close_values),
        )
    })
    assert close.failures == ()
    close_signals = tuple(signal for signal in close.signals if signal.kind is SignalKind.EXECUTION)
    assert len(close_signals) == 1
    assert close_signals[0].execution_proposal is not None
    assert close_signals[0].execution_proposal.tag_id == "PROFIT_TAKEN_TRAILING_STOP"
    assert close_signals[0].execution_proposal.side == "BUY"
    assert close_signals[0].execution_proposal.proposed_quantity == 5
    hub.on_execution_result(
        strategy.strategy_id,
        "PROFIT_TAKEN_TRAILING_STOP",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.state.active_hedge_qty == 0
    assert strategy.state.is_active is False
