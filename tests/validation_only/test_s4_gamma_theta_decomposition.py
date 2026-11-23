from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest


D = Decimal
S4_STRATEGY = "track4_gamma_scalping"
SYNTHETIC_GROUP = "S4-SYNTH-GAMMA-THETA-01"

# Explicit fixture-only unit convention. These labels are not asserted to be
# the undocumented/raw units of KIS H0IOCNT0 fields.
DELTA_UNIT = "OPTION_PRICE_PER_UNDERLYING_POINT"
GAMMA_UNIT = "OPTION_PRICE_PER_UNDERLYING_POINT_SQUARED"
THETA_UNIT = "OPTION_PRICE_PER_ELAPSED_DAY"
VEGA_UNIT = "OPTION_PRICE_PER_IV_DECIMAL"


@dataclass(frozen=True)
class SyntheticGreeks:
    instrument_id: str
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    delta_unit: str = DELTA_UNIT
    gamma_unit: str = GAMMA_UNIT
    theta_unit: str = THETA_UNIT
    vega_unit: str = VEGA_UNIT


@dataclass(frozen=True)
class SyntheticOptionMark:
    strategy_id: str
    group_id: str
    instrument_id: str
    quantity: int
    multiplier: Decimal
    option_mark_open: Decimal
    option_mark_close: Decimal
    underlying_open: Decimal
    underlying_close: Decimal
    iv_open: Decimal
    iv_close: Decimal
    elapsed_days: Decimal
    greeks: SyntheticGreeks


@dataclass(frozen=True)
class SyntheticLinkedFuturesMark:
    strategy_id: str
    group_id: str
    instrument_id: str
    side: str
    quantity: int
    fill_price: Decimal
    mark_price: Decimal
    multiplier: Decimal


@dataclass(frozen=True)
class SyntheticGreekDecomposition:
    option_mtm_pnl: Decimal
    delta_pnl: Decimal
    gamma_pnl: Decimal
    theta_pnl: Decimal
    theta_decay_cost_diagnostic: Decimal
    vega_pnl: Decimal
    residual_pnl: Decimal
    linked_futures_unrealized_pnl: Decimal
    combined_option_futures_mtm_pnl: Decimal


def _finite(*values: Decimal) -> bool:
    return all(isinstance(value, Decimal) and value.is_finite() for value in values)


def decompose_synthetic_s4_group(
    option: SyntheticOptionMark,
    hedge: SyntheticLinkedFuturesMark,
) -> SyntheticGreekDecomposition:
    """Validation-only Taylor attribution; never a Production accounting source."""
    if option.strategy_id != S4_STRATEGY or option.group_id != SYNTHETIC_GROUP:
        raise ValueError("S4_SYNTHETIC_OPTION_SCOPE_MISMATCH")
    if hedge.strategy_id != option.strategy_id or hedge.group_id != option.group_id:
        raise ValueError("S4_SYNTHETIC_LINKED_HEDGE_GROUP_MISMATCH")
    if not option.instrument_id or option.greeks.instrument_id != option.instrument_id:
        raise ValueError("S4_SYNTHETIC_GREEKS_INSTRUMENT_MISMATCH")
    if not hedge.instrument_id or hedge.side not in {"BUY", "SELL"}:
        raise ValueError("S4_SYNTHETIC_HEDGE_IDENTITY_INVALID")
    if option.quantity <= 0 or hedge.quantity <= 0:
        raise ValueError("S4_SYNTHETIC_QUANTITY_INVALID")
    if option.multiplier <= 0 or hedge.multiplier <= 0 or option.elapsed_days < 0:
        raise ValueError("S4_SYNTHETIC_SCALE_INVALID")
    if (
        option.greeks.delta_unit != DELTA_UNIT
        or option.greeks.gamma_unit != GAMMA_UNIT
        or option.greeks.theta_unit != THETA_UNIT
        or option.greeks.vega_unit != VEGA_UNIT
    ):
        raise ValueError("S4_SYNTHETIC_GREEK_UNIT_CONTRACT_MISMATCH")
    if not _finite(
        option.multiplier, option.option_mark_open, option.option_mark_close,
        option.underlying_open, option.underlying_close, option.iv_open,
        option.iv_close, option.elapsed_days, option.greeks.delta,
        option.greeks.gamma, option.greeks.theta, option.greeks.vega,
        hedge.multiplier, hedge.fill_price, hedge.mark_price,
    ):
        raise ValueError("S4_SYNTHETIC_NON_FINITE_INPUT")
    if min(
        option.option_mark_open, option.option_mark_close,
        option.underlying_open, option.underlying_close,
        option.iv_open, option.iv_close, hedge.fill_price, hedge.mark_price,
    ) <= 0:
        raise ValueError("S4_SYNTHETIC_PRICE_OR_IV_INVALID")

    quantity_scale = D(option.quantity) * option.multiplier
    underlying_move = option.underlying_close - option.underlying_open
    iv_move = option.iv_close - option.iv_open

    option_mtm = (option.option_mark_close - option.option_mark_open) * quantity_scale
    delta_pnl = option.greeks.delta * underlying_move * quantity_scale
    gamma_pnl = D("0.5") * option.greeks.gamma * underlying_move ** 2 * quantity_scale
    theta_pnl = option.greeks.theta * option.elapsed_days * quantity_scale
    vega_pnl = option.greeks.vega * iv_move * quantity_scale
    residual = option_mtm - delta_pnl - gamma_pnl - theta_pnl - vega_pnl

    hedge_direction = D("1") if hedge.side == "BUY" else D("-1")
    hedge_pnl = (
        (hedge.mark_price - hedge.fill_price)
        * hedge.quantity
        * hedge.multiplier
        * hedge_direction
    )
    return SyntheticGreekDecomposition(
        option_mtm_pnl=option_mtm,
        delta_pnl=delta_pnl,
        gamma_pnl=gamma_pnl,
        theta_pnl=theta_pnl,
        theta_decay_cost_diagnostic=-theta_pnl,
        vega_pnl=vega_pnl,
        residual_pnl=residual,
        linked_futures_unrealized_pnl=hedge_pnl,
        combined_option_futures_mtm_pnl=option_mtm + hedge_pnl,
    )


def _fixture(*, group_id: str = SYNTHETIC_GROUP, greek_instrument: str = "SYNTHETIC_CONTRACT:S4-CALL"):
    option = SyntheticOptionMark(
        strategy_id=S4_STRATEGY,
        group_id=group_id,
        instrument_id="SYNTHETIC_CONTRACT:S4-CALL",
        quantity=2,
        multiplier=D("10"),
        option_mark_open=D("100"),
        option_mark_close=D("101.9"),
        underlying_open=D("1000"),
        underlying_close=D("1004"),
        iv_open=D("0.20"),
        iv_close=D("0.22"),
        elapsed_days=D("0.5"),
        greeks=SyntheticGreeks(
            instrument_id=greek_instrument,
            delta=D("0.5"),
            gamma=D("0.1"),
            theta=D("-2"),
            vega=D("5"),
        ),
    )
    hedge = SyntheticLinkedFuturesMark(
        strategy_id=S4_STRATEGY,
        group_id=group_id,
        instrument_id="SYNTHETIC_CONTRACT:S4-MINI",
        side="SELL",
        quantity=1,
        fill_price=D("200"),
        mark_price=D("198"),
        multiplier=D("50"),
    )
    return option, hedge


def test_s4_synthetic_gamma_theta_decomposition_reconciles_to_option_mtm_and_linked_futures():
    option, hedge = _fixture()
    result = decompose_synthetic_s4_group(option, hedge)

    assert result.option_mtm_pnl == D("38")
    assert result.delta_pnl == D("40")
    assert result.gamma_pnl == D("16")
    assert result.theta_pnl == D("-20")
    assert result.theta_decay_cost_diagnostic == D("20")
    assert result.vega_pnl == D("2")
    assert result.residual_pnl == D("0")
    assert result.linked_futures_unrealized_pnl == D("100")
    assert result.combined_option_futures_mtm_pnl == D("138")
    # Gamma/theta are explanatory components of option MTM, not extra PnL.
    assert result.combined_option_futures_mtm_pnl != (
        result.option_mtm_pnl
        + result.linked_futures_unrealized_pnl
        + result.gamma_pnl
        - result.theta_decay_cost_diagnostic
    )


def test_s4_synthetic_decomposition_preserves_unexplained_mark_residual():
    option, hedge = _fixture()
    option = SyntheticOptionMark(
        **{**option.__dict__, "option_mark_close": D("102.4")}
    )
    result = decompose_synthetic_s4_group(option, hedge)
    assert result.residual_pnl == D("10")


def test_s4_synthetic_decomposition_rejects_greek_instrument_mismatch():
    option, hedge = _fixture(greek_instrument="SYNTHETIC_CONTRACT:OTHER")
    with pytest.raises(ValueError, match="S4_SYNTHETIC_GREEKS_INSTRUMENT_MISMATCH"):
        decompose_synthetic_s4_group(option, hedge)


def test_s4_synthetic_decomposition_rejects_unlinked_futures_group():
    option, hedge = _fixture()
    hedge = SyntheticLinkedFuturesMark(
        **{**hedge.__dict__, "group_id": "S4-SYNTH-GROUP-OTHER"}
    )
    with pytest.raises(ValueError, match="S4_SYNTHETIC_LINKED_HEDGE_GROUP_MISMATCH"):
        decompose_synthetic_s4_group(option, hedge)


def test_s4_synthetic_decomposition_rejects_undeclared_greek_units():
    option, hedge = _fixture()
    bad_greeks = SyntheticGreeks(
        instrument_id=option.instrument_id,
        delta=option.greeks.delta,
        gamma=option.greeks.gamma,
        theta=option.greeks.theta,
        vega=option.greeks.vega,
        theta_unit="UNKNOWN",
    )
    option = SyntheticOptionMark(**{**option.__dict__, "greeks": bad_greeks})
    with pytest.raises(ValueError, match="S4_SYNTHETIC_GREEK_UNIT_CONTRACT_MISMATCH"):
        decompose_synthetic_s4_group(option, hedge)


def test_s4_synthetic_decomposition_rejects_negative_elapsed_time():
    option, hedge = _fixture()
    option = SyntheticOptionMark(**{**option.__dict__, "elapsed_days": D("-0.1")})
    with pytest.raises(ValueError, match="S4_SYNTHETIC_SCALE_INVALID"):
        decompose_synthetic_s4_group(option, hedge)


def test_s4_virtual_execution_ledger_exposes_premium_but_not_gamma_or_theta_attribution():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from application.composition.virtual_track4_attribution_source import VirtualTrack4AttributionSource
    from contracts.track4_attribution_provider import Track4AttributionSourceUnavailable

    engine = SimpleNamespace(reports=(
        SimpleNamespace(asset_type="OPTION", side="BUY", executed_price="100", executed_qty=2),
        SimpleNamespace(asset_type="FUTURES", side="SELL", executed_price="200", executed_qty=1),
    ))
    source = VirtualTrack4AttributionSource(
        engine,
        observed_at=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
    )
    snapshot = source.snapshot()

    assert snapshot.premium_spent == D("200")
    assert snapshot.accumulated_gamma_profit is None
    assert snapshot.theta_decay_cost is None
    with pytest.raises(Track4AttributionSourceUnavailable, match="GAMMA_PROFIT_ATTRIBUTION_SOURCE_UNAVAILABLE"):
        source.accumulated_gamma_profit()
    with pytest.raises(Track4AttributionSourceUnavailable, match="THETA_ATTRIBUTION_SOURCE_UNAVAILABLE"):
        source.theta_decay_cost()


def test_s4_market_projection_does_not_claim_attribution_readiness_even_with_ledger_provider():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from application.composition.virtual_track4_attribution_source import VirtualTrack4AttributionSource
    from contracts.track4_market_projection_provider import Track4MarketProjectionProvider

    source = VirtualTrack4AttributionSource(
        SimpleNamespace(reports=()),
        observed_at=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc),
    )
    provider = Track4MarketProjectionProvider(
        snapshot_supplier=lambda: SimpleNamespace(instrument_id="SYNTHETIC_INDEX", as_of=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)),
        price_history_supplier=lambda _instrument: (100, 101),
        attribution_provider=source,
    )
    readiness = provider.readiness()

    assert readiness.attribution is False
