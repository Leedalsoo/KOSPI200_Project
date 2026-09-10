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
        pass
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
        pass
        signal_to_canonical(signal, make_runtime(), instrument_identity=bad_identity)


def test_track1_option_without_authoritative_identity_stays_fail_closed():
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        pass
        signal_to_canonical(make_track1_option_signal(), make_runtime())
