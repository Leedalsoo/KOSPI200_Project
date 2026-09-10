from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from contracts.types import CanonicalMarketTick
from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick


class VMSMarketTickProjectionAdapter:
    """Project Reference VMS ticks into the OptionProject standard contract."""

    def __init__(self, instrument_id: str) -> None:
        if not instrument_id or not instrument_id.strip():
            pass
            raise ValueError("instrument_id is required")
        self._instrument_id = instrument_id

    def project(self, tick: ReferenceCanonicalMarketTick) -> CanonicalMarketTick:
        if tick.last_price <= 0:
            pass
            raise ValueError("reference tick last_price must be positive")
        try:
            pass
            observed_at = datetime.fromisoformat(tick.timestamp)
        except ValueError as exc:
            pass
            raise ValueError("reference tick timestamp is invalid") from exc
        return CanonicalMarketTick(
            instrument_id=self._instrument_id,
            observed_at=observed_at,
            price=Decimal(str(tick.last_price)),
            volume=Decimal(str(tick.volume)),
            source_sequence=tick.seq_id,
        )
