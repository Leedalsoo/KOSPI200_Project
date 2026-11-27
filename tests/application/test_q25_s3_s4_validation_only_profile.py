from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.composition.validation_only_s3_s4_input_adapter import (
    ValidationOnlyProfileError,
    ValidationOnlyS3S4InputAdapter,
)
from core.strategy.contracts import SignalKind
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config/validation_only/q25_s3_s4/profile.v1.json"


def _adapter() -> ValidationOnlyS3S4InputAdapter:
    raw = PROFILE_PATH.read_bytes()
    expected_hash = PROFILE_PATH.with_suffix(PROFILE_PATH.suffix + ".sha256").read_text().strip()
    assert hashlib.sha256(raw).hexdigest() == expected_hash
    return ValidationOnlyS3S4InputAdapter(json.loads(raw))


def _track3_analytics(z_score: float, current_pnl: float = 0.0):
    values = {
        "spread.z_score": z_score,
        "spread.std": 0.5286631725399453,
        "volatility.ratio": 1.0,
        "microstructure.spread": 0.1,
        "price.change_rate": 0.0,
        "market.gap_pct": 0.0,
        "market.current_regime": "NORMAL",
        "cost.fees": 0.0,
        "portfolio.current_pnl": current_pnl,
        "portfolio.options_pnl": 0.0,
        "portfolio.premium_spent": 0.0,
    }
    return {key: SimpleNamespace(value=value) for key, value in values.items()}


def test_profile_has_reproducible_raw_anchor_and_explicit_nonproduction_boundary():
    adapter = _adapter()
    provenance = adapter.provenance

    assert adapter.profile_id == "Q25-S3-S4-MARKET-ANCHORED-VALIDATION-v1"
    assert provenance["namespace"] == "SYNTHETIC:DERIVED_SCENARIO"
    assert provenance["authority"]["identity_authority"] == "NONE"
    assert provenance["authority"]["execution_authority"] == "NONE"
    assert provenance["authority"]["production_eligible"] is False
    assert provenance["authority"]["live_eligible"] is False
    assert len(provenance["source_anchors"]) == 2
    assert provenance["source_anchors"][0]["sha256"] == "794f17cb445878b6688fea79e04d5473a33b5e5e1856eb166ab0232eaf429c2f"
    assert provenance["source_anchors"][1]["sha256"] == "998198545e60aaa266e0f9796f66a70baa5d5787a6fd09c735845685bc0c3ad4"


def test_s3_market_anchored_basis_drives_strategy_entry_and_close_signal_lifecycle():
    adapter = _adapter()
    data = adapter.build_track3_input()
    strategy = Track3StatisticalArbitrage(
        enabled=True,
        capital_gate_min=1.0,
        risk_limits_available=True,
    )

    entry = strategy.evaluate_input(data, _track3_analytics(2.5))

    assert entry.status == "ENTER"
    assert entry.signals
    assert entry.signals[0].execution_proposal.asset_type == "FUTURES"
    assert entry.signals[0].execution_proposal.proposed_quantity == 1
    assert strategy.active_position == "SHORT_SPREAD"

    close = strategy.evaluate_input(data, _track3_analytics(0.1, current_pnl=100000.0))

    assert close.status == "CLOSED"
    assert close.signals
    assert close.signals[0].execution_proposal.tag_id == "CLOSE_STAT_ARB"
    assert strategy.active_position == "SHORT_SPREAD"

    strategy.on_execution_result(
        "CLOSE_STAT_ARB",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.active_position is None
    assert strategy.active_group_id is None
    assert strategy._exit_pending is False


def test_s4_synthetic_greek_stress_exercises_basecamp_and_futures_hedge_close():
    adapter = _adapter()
    data = adapter.build_track4_input()
    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=Decimal("1"),
        risk_limits_available=True,
    )

    basecamp_signals = strategy.evaluate_basecamp(
        data, active_vol=data.active_vol, base_vol=data.base_vol
    )
    hedge_signals = strategy.evaluate_delta_hedge(
        data,
        delta=data.current_delta,
        deadband=Decimal("0"),
        equity=data.current_equity,
        max_hedge_qty=data.max_hedge_qty,
        actual_hedge_qty=0,
        pending_hedge_qty=0,
    )
    assert len(basecamp_signals) == 1
    assert basecamp_signals[0].kind == SignalKind.NON_EXECUTION
    assert basecamp_signals[0].execution_proposal is None
    assert len(hedge_signals) == 1
    assert hedge_signals[0].execution_proposal.asset_type == "FUTURES"
    assert hedge_signals[0].execution_proposal.proposed_quantity == 2
    assert strategy.state.active_hedge_qty == -2

    initial_profit = strategy.evaluate_profit_trailing(
        data, current_pnl=Decimal("50000"), premium_spent=data.premium_spent
    )
    assert initial_profit == ()
    exit_signals = strategy.evaluate_profit_trailing(
        data, current_pnl=Decimal("40000"), premium_spent=data.premium_spent
    )
    assert len(exit_signals) == 1
    close = exit_signals[0]
    assert close.direction == "CLOSE"
    assert close.execution_proposal.tag_id == "PROFIT_TAKEN_TRAILING_STOP"
    assert close.execution_proposal.side == "BUY"
    assert close.execution_proposal.proposed_quantity == 2
    assert strategy._exit_pending is True

    strategy.on_execution_result(
        "PROFIT_TAKEN_TRAILING_STOP",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.state.active_hedge_qty == 0
    assert strategy.state.is_active is False
    assert strategy._exit_pending is False


def test_adapter_rejects_profile_that_claims_production_authority():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8-sig"))
    profile["authority"]["production_eligible"] = True

    with pytest.raises(ValidationOnlyProfileError, match="AUTHORITY_BOUNDARY_REQUIRED"):
        ValidationOnlyS3S4InputAdapter(profile)
