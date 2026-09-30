from datetime import datetime, timedelta
from decimal import Decimal

from application.composition.track1_runtime_input_provider import Track1RuntimeInputProvider
from contracts.position_provenance import PositionRole, PositionLotProvenance
from contracts.types import OptionInstrumentIdentity


class StubLots:
    def __init__(self, lots):
        self._lots = tuple(lots)

    def open_lots(self):
        return self._lots


class StubDelta:
    def get_delta(self, *, expiry, option_type, strike, as_of, instrument_id=None):
        assert expiry == "202610"
        assert option_type == "CALL"
        assert strike == Decimal("1000")
        assert as_of == datetime(2026, 9, 30, 10, 0)
        assert instrument_id == "OPT1"
        return Decimal("0.5")


def make_lot(*, side="SELL", quantity=2, role=PositionRole.NONE):
    identity = OptionInstrumentIdentity(
        instrument_id="OPT1",
        symbol="OPT1",
        expiry="202610",
        option_type="CALL",
        strike=Decimal("1000"),
        contract_multiplier=Decimal("250000"),
        identity_source="OPTION_MASTER",
    )
    return PositionLotProvenance(
        run_id="run",
        instrument_id="OPT1",
        strategy_id="TRACK1_TAIL_DEFENSE",
        group_id="g",
        leg_id="l",
        client_order_id="o",
        execution_id=f"e-{side}-{role}",
        side=side,
        opened_quantity=quantity,
        remaining_quantity=quantity,
        execution_timestamp=datetime(2026, 9, 30, 9, 0),
        instrument_identity=identity,
        contract_multiplier=Decimal("250000"),
        identity_source="OPTION_MASTER",
        position_role=role,
    )


def test_track1_builds_momentum_and_position_metrics():
    as_of = datetime(2026, 9, 30, 10, 0)
    history = tuple(
        (as_of - timedelta(minutes=5 * (12 - i)), Decimal("1000") + Decimal(i))
        for i in range(13)
    )
    provider = Track1RuntimeInputProvider(
        fence_type_source=lambda: "CALL",
        position_lot_store=StubLots([make_lot()]),
        option_delta_source=StubDelta(),
    )

    result = provider.build(
        as_of=as_of,
        active_vol=Decimal("1"),
        base_vol=Decimal("1"),
        days_to_expiry=10,
        underlying_history=history,
    )

    assert result.missing_sources == ()
    assert result.payload is not None
    assert result.payload.momentum_confirmed is True
    assert result.payload.coverage_ratio == 0.0
    assert result.payload.short_option_net_delta == Decimal("-250000.0")


def test_track1_position_metrics_are_unavailable_without_short_target_but_momentum_remains_usable():
    as_of = datetime(2026, 9, 30, 10, 0)
    history = tuple(
        (as_of - timedelta(minutes=5 * (12 - i)), Decimal("1000") + Decimal(i))
        for i in range(13)
    )
    provider = Track1RuntimeInputProvider(
        fence_type_source=lambda: "CALL",
        position_lot_store=StubLots([]),
        option_delta_source=StubDelta(),
    )

    result = provider.build(
        as_of=as_of,
        active_vol=Decimal("1"),
        base_vol=Decimal("1"),
        days_to_expiry=10,
        underlying_history=history,
    )

    assert result.payload is not None
    assert result.payload.momentum_confirmed is True
    assert result.payload.coverage_ratio is None
    assert result.payload.short_option_net_delta is None


def test_track1_fails_closed_during_roc_warmup():
    as_of = datetime(2026, 9, 30, 10, 0)
    history = tuple(
        (as_of - timedelta(minutes=5 * (3 - i)), Decimal("1000") + Decimal(i))
        for i in range(4)
    )
    provider = Track1RuntimeInputProvider(
        fence_type_source=lambda: "CALL",
        position_lot_store=StubLots([]),
        option_delta_source=StubDelta(),
    )

    result = provider.build(
        as_of=as_of,
        active_vol=Decimal("1"),
        base_vol=Decimal("1"),
        days_to_expiry=10,
        underlying_history=history,
    )

    assert result.payload is None
    assert "momentum" in result.missing_sources