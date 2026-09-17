from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.canonical_signal_adapter import (
RuntimeSignalContext,
signal_to_canonical,
)


def make_track1_option_signal() -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        requested_price=None,
        side="BUY",
        track_id="TRACK1_TAIL_DEFENSE",
        tag_id="1",
        option_type="CALL",
        strike=Decimal("350.0"),
    )
    return Signal(
        "TRACK1_TAIL_DEFENSE",
        "LONG",
1.0,
        "FENCE_BUILD:CALL:350.0",
        execution_proposal=proposal,
    )


def make_identity() -> OptionInstrumentIdentity:
    return OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-C-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="CALL",
        strike=Decimal("350.0"),
    )


def make_runtime() -> RuntimeSignalContext:
    return RuntimeSignalContext(
        signal_id="tick-100:TRACK1_TAIL_DEFENSE:0",
        track_id="TRACK1_TAIL_DEFENSE",
        price=1.25,
        timestamp="2026-09-06T09:01:00",
    )


def test_track1_option_signal_accepts_external_authoritative_identity():
    canonical = signal_to_canonical(
        make_track1_option_signal(),
        make_runtime(),
        instrument_identity=make_identity(),
    )

    assert canonical.signal_id == "tick-100:TRACK1_TAIL_DEFENSE:0"
    assert canonical.track_id == "TRACK1_TAIL_DEFENSE"
    assert canonical.qty == 1
    assert canonical.symbol == "KRXOPT"
    assert canonical.expiry == "2026-10-08"
    assert canonical.strike == 350.0
    assert canonical.option_type.value == "CALL"


def test_track1_proposal_and_external_identity_mismatch_fails_closed():
    bad_identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-P-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="PUT",
        strike=Decimal("350.0"),
    )

    with pytest.raises(ValueError, match="OPTION_TYPE_IDENTITY_MISMATCH"):
        signal_to_canonical(
            make_track1_option_signal(),
            make_runtime(),
            instrument_identity=bad_identity,
        )


def test_signal_identity_and_external_identity_mismatch_fails_closed():
    signal = Signal(
        "TRACK1_TAIL_DEFENSE",
        "LONG",
1.0,
        "FENCE_BUILD:CALL:350.0",
        instrument_identity=make_identity(),
        execution_proposal=make_track1_option_signal().execution_proposal,
    )
    bad_identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-P-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="PUT",
        strike=Decimal("350.0"),
    )

    with pytest.raises(ValueError, match="OPTION_IDENTITY_MISMATCH"):
        signal_to_canonical(signal, make_runtime(), instrument_identity=bad_identity)


def test_track1_option_without_authoritative_identity_stays_fail_closed():
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        signal_to_canonical(make_track1_option_signal(), make_runtime())

# Consolidated from tests\integration\test_canonical_signal_adapter_track4_seam.py; retained because it covers the same production boundary.

from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.strategy.canonical_signal_adapter import RuntimeSignalContext, signal_to_canonical
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def make_track4_futures_signal() -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="FUTURES",
        requested_price=Decimal("350.25"),
        side="BUY",
        track_id="TRACK4_GAMMA_SCALPING",
        tag_id="DELTA_HEDGE",
    )
    return Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "DELTA_HEDGE", execution_proposal=proposal)


def make_track4_runtime() -> RuntimeSignalContext:
    return RuntimeSignalContext(
        signal_id="tick-200:TRACK4_GAMMA_SCALPING:0",
        track_id="TRACK4_GAMMA_SCALPING",
        price=351.10,
        timestamp="2026-09-06T09:02:00",
    )


def test_track4_proposal_semantics_are_preserved_at_canonical_boundary():
    signal = make_track4_futures_signal()
    canonical = signal_to_canonical(signal, make_track4_runtime())
    assert canonical.signal_id == "tick-200:TRACK4_GAMMA_SCALPING:0"
    assert canonical.track_id == "TRACK4_GAMMA_SCALPING"
    assert canonical.asset_type.value == "FUTURES"
    assert canonical.side.value == "BUY"
    assert canonical.qty == 2
    assert canonical.tag_id == "DELTA_HEDGE"
    assert canonical.price == 351.10
    # requested_price와 Runtime canonical price는 다른 의미이며 서로 덮어쓰지 않는다.
    assert signal.execution_proposal.requested_price == Decimal("350.25")
    assert canonical.price != float(signal.execution_proposal.requested_price)


def test_track4_missing_execution_proposal_fails_closed():
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "DELTA_HEDGE", execution_proposal=None)
    with pytest.raises(ValueError, match="EXECUTION_PROPOSAL_REQUIRED"):
        signal_to_canonical(signal, make_track4_runtime())


def test_option_canonical_boundary_requires_authoritative_identity():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", requested_price=Decimal("1.50"),
        side="BUY", track_id="TRACK4_GAMMA_SCALPING", tag_id="OPTION_HEDGE",
        option_type="CALL", strike=Decimal("350"),
    )
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "OPTION_HEDGE", execution_proposal=proposal)
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        signal_to_canonical(signal, make_track4_runtime())


def test_option_identity_fields_are_preserved_without_synthetic_identity():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", requested_price=Decimal("1.50"),
        side="BUY", track_id="TRACK4_GAMMA_SCALPING", tag_id="OPTION_HEDGE",
        option_type="CALL", strike=Decimal("350"),
    )
    identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-C-2026-10", symbol="KRXOPT", expiry="2026-10-08",
        option_type="CALL", strike=Decimal("350"),
    )
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "OPTION_HEDGE",
                    execution_proposal=proposal, instrument_identity=identity)
    canonical = signal_to_canonical(signal, make_track4_runtime())
    assert canonical.asset_type.value == "OPTION"
    assert canonical.side.value == "BUY"
    assert canonical.qty == 1
    assert canonical.symbol == "KRXOPT"
    assert canonical.expiry == "2026-10-08"
    assert canonical.option_type.value == "CALL"
    assert canonical.strike == 350.0
    assert canonical.price == 351.10
