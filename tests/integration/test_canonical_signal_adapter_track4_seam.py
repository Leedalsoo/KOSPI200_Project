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


def make_runtime() -> RuntimeSignalContext:
    return RuntimeSignalContext(
        signal_id="tick-200:TRACK4_GAMMA_SCALPING:0",
        track_id="TRACK4_GAMMA_SCALPING",
        price=351.10,
        timestamp="2026-09-06T09:02:00",
    )


def test_track4_proposal_semantics_are_preserved_at_canonical_boundary():
    signal = make_track4_futures_signal()
    canonical = signal_to_canonical(signal, make_runtime())
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
        pass
        signal_to_canonical(signal, make_runtime())


def test_option_canonical_boundary_requires_authoritative_identity():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", requested_price=Decimal("1.50"),
        side="BUY", track_id="TRACK4_GAMMA_SCALPING", tag_id="OPTION_HEDGE",
        option_type="CALL", strike=Decimal("350"),
    )
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "OPTION_HEDGE", execution_proposal=proposal)
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        pass
        signal_to_canonical(signal, make_runtime())


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
    canonical = signal_to_canonical(signal, make_runtime())
    assert canonical.asset_type.value == "OPTION"
    assert canonical.side.value == "BUY"
    assert canonical.qty == 1
    assert canonical.symbol == "KRXOPT"
    assert canonical.expiry == "2026-10-08"
    assert canonical.option_type.value == "CALL"
    assert canonical.strike == 350.0
    assert canonical.price == 351.10
