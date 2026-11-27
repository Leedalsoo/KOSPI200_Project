from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_s3_s4_input_adapter import (
    ValidationOnlyS3S4InputAdapter,
)
from core.strategy.contracts import SignalKind
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config/validation_only/q25_s3_s4/mini_futures_profile.v2.json"


def _profile():
    raw = PROFILE_PATH.read_bytes()
    expected = PROFILE_PATH.with_suffix(PROFILE_PATH.suffix + ".sha256").read_text().strip()
    assert hashlib.sha256(raw).hexdigest() == expected
    return json.loads(raw)


def _adapter():
    return ValidationOnlyS3S4InputAdapter(_profile())


def _analytics(z_score: float, spread_std: float, current_pnl: float = 0.0):
    values = {
        "spread.z_score": z_score,
        "spread.std": spread_std,
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


def test_mini_profile_reuses_actual_raw_and_marks_only_missing_orderbook_as_synthetic():
    profile = _profile()
    adapter = _adapter()
    market = profile["futures_market"]
    quote = adapter.build_futures_quote_proxy()

    assert profile["profile_id"] == "Q25-S3-S4-MINI-FUTURES-VALIDATION-v2"
    assert profile["authority"]["identity_authority"] == "NONE"
    assert profile["authority"]["execution_authority"] == "NONE"
    assert profile["authority"]["production_eligible"] is False
    assert market["product_type"] == "MINI"
    assert market["source_instrument"] == "A05610"
    assert market["contract_multiplier"] == 50000
    assert market["raw_tr_frames"] == 27114
    assert market["parsed_trade_records"] == 45295
    assert market["exact_event_time_matches"] == 12619
    assert market["mini_orderbook_frames"] == 0
    assert quote["source_kind"] == "SYNTHETIC_L1_DEPTH_PROXY"
    assert quote["namespace"] == "SYNTHETIC:DERIVED_SCENARIO"
    assert quote["source_last_price"] == 1074.16
    assert quote["bid"] == 1074.11
    assert quote["ask"] == 1074.21
    assert quote["bid_size"] == quote["ask_size"] == 5
    assert quote["official_tick_size_claimed"] is False
    assert len(profile["s3"]["observations"]) == 20
    assert profile["s3"]["product_type"] == "MINI"
    assert profile["s3"]["contract_multiplier"] == 50000


def test_s3_uses_same_time_mini_futures_index_basis_and_completes_signal_state_cycle():
    adapter = _adapter()
    data = adapter.build_track3_input()
    profile = _profile()
    strategy = Track3StatisticalArbitrage(
        enabled=True, capital_gate_min=1.0, risk_limits_available=True
    )

    entry = strategy.evaluate_input(
        data, _analytics(2.5, profile["s3"]["spread_std"])
    )
    assert entry.status == "ENTER"
    assert entry.signals[0].execution_proposal.asset_type == "FUTURES"
    assert entry.signals[0].execution_proposal.proposed_quantity == 1
    assert data.contract_multiplier == 50000
    assert strategy.active_position == "SHORT_SPREAD"

    close = strategy.evaluate_input(
        data, _analytics(0.1, profile["s3"]["spread_std"], current_pnl=100000.0)
    )
    assert close.status == "CLOSED"
    assert close.signals[0].execution_proposal.tag_id == "CLOSE_STAT_ARB"
    strategy.on_execution_result(
        "CLOSE_STAT_ARB",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.active_position is None
    assert strategy.active_group_id is None
    assert strategy._exit_pending is False


def test_s4_synthetic_greek_stress_generates_and_closes_five_mini_futures_hedges():
    adapter = _adapter()
    data = adapter.build_track4_input()
    strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=1, risk_limits_available=True
    )

    basecamp = strategy.evaluate_basecamp(
        data, active_vol=data.active_vol, base_vol=data.base_vol
    )
    assert len(basecamp) == 1
    assert basecamp[0].kind == SignalKind.NON_EXECUTION

    hedge = strategy.evaluate_delta_hedge(
        data,
        delta=data.current_delta,
        deadband=0,
        equity=data.current_equity,
        max_hedge_qty=data.max_hedge_qty,
        actual_hedge_qty=0,
        pending_hedge_qty=0,
    )
    assert len(hedge) == 1
    assert hedge[0].execution_proposal.asset_type == "FUTURES"
    assert hedge[0].execution_proposal.side == "SELL"
    assert hedge[0].execution_proposal.proposed_quantity == 5
    assert strategy.state.active_hedge_qty == -5

    assert strategy.evaluate_profit_trailing(
        data, current_pnl=50000, premium_spent=data.premium_spent
    ) == ()
    close = strategy.evaluate_profit_trailing(
        data, current_pnl=40000, premium_spent=data.premium_spent
    )
    assert len(close) == 1
    assert close[0].execution_proposal.side == "BUY"
    assert close[0].execution_proposal.proposed_quantity == 5
    strategy.on_execution_result(
        "PROFIT_TAKEN_TRAILING_STOP",
        SimpleNamespace(group_complete=True, position_flat=True),
    )
    assert strategy.state.active_hedge_qty == 0
    assert strategy.state.is_active is False
    assert strategy._exit_pending is False
