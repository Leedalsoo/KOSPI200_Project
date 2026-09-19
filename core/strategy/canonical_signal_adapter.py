from dataclasses import dataclass
from typing import Optional
from contracts.types import OptionInstrumentIdentity
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from core.strategy.contracts import Signal
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide, CanonicalOptionType, CanonicalStrategySignal

@dataclass(frozen=True)
class RuntimeSignalContext:
    signal_id: str
    track_id: str
    price: float
    timestamp: str

def _require_non_empty(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value: raise ValueError(f"{field_name}_REQUIRED")
    return value

def signal_to_canonical(signal: Signal, runtime: RuntimeSignalContext, instrument_identity: Optional[OptionInstrumentIdentity | FuturesInstrumentIdentity] = None) -> CanonicalStrategySignal:
    signal_id = _require_non_empty(runtime.signal_id, "SIGNAL_ID")
    track_id = _require_non_empty(runtime.track_id, "TRACK_ID")
    proposal = signal.execution_proposal
    if proposal is None: raise ValueError("EXECUTION_PROPOSAL_REQUIRED")
    if proposal.proposed_quantity <= 0: raise ValueError("QTY_REQUIRED")
    if not proposal.asset_type: raise ValueError("ASSET_TYPE_REQUIRED")
    if not proposal.side: raise ValueError("SIDE_REQUIRED")
    asset_type = CanonicalAssetType(str(proposal.asset_type))
    side = CanonicalOrderSide(str(proposal.side))
    signal_identity = signal.instrument_identity
    if signal_identity is not None and instrument_identity is not None and signal_identity != instrument_identity:
        if isinstance(signal_identity, OptionInstrumentIdentity) and isinstance(instrument_identity, OptionInstrumentIdentity):
            raise ValueError("OPTION_IDENTITY_MISMATCH")
        raise ValueError("INSTRUMENT_IDENTITY_MISMATCH")
    identity = signal_identity or instrument_identity
    option_type = None; strike = 0.0; symbol = ""; expiry = ""; instrument_id = ""; multiplier = None; identity_source = ""
    if asset_type == CanonicalAssetType.FUTURES and isinstance(identity, FuturesInstrumentIdentity):
        symbol, instrument_id = identity.symbol, identity.instrument_id
        multiplier, identity_source = float(identity.contract_multiplier), identity.identity_source
    if asset_type == CanonicalAssetType.OPTION:
        if not isinstance(identity, OptionInstrumentIdentity): raise ValueError("OPTION_IDENTITY_REQUIRED")
        if not identity.instrument_id or not identity.symbol or not identity.expiry or identity.option_type is None or identity.strike is None:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")
        if proposal.option_type is not None and str(proposal.option_type) != str(identity.option_type): raise ValueError("OPTION_TYPE_IDENTITY_MISMATCH")
        if proposal.strike is not None and proposal.strike != identity.strike: raise ValueError("STRIKE_IDENTITY_MISMATCH")
        option_type = CanonicalOptionType(str(identity.option_type)); strike = float(identity.strike); symbol = identity.symbol; expiry = identity.expiry; instrument_id = identity.instrument_id
        multiplier = float(identity.contract_multiplier) if identity.contract_multiplier is not None else None; identity_source = identity.identity_source or ""
    return CanonicalStrategySignal(signal_id=signal_id, track_id=track_id, asset_type=asset_type, side=side, qty=proposal.proposed_quantity, price=float(runtime.price), option_type=option_type, strike=strike, tag_id=str(proposal.tag_id) if proposal.tag_id is not None else "", reason=signal.reason, timestamp=runtime.timestamp, symbol=symbol, expiry=expiry, instrument_id=instrument_id, contract_multiplier=multiplier, identity_source=identity_source)
