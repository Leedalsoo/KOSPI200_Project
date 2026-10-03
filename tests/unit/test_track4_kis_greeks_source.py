from datetime import datetime, timezone
from decimal import Decimal

from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource


def test_realtime_source_accepts_h0iocnt0_and_retains_provider():
    values = [""] * 58
    values[0] = "201S11305"
    values[28] = "0.5123"
    values[29] = "0.0182"
    values[31] = "-0.034"
    values[33] = "0.247"
    frame = f"0|H0IOCNT0|58|{'^'.join(values)}"
    source = KISTrack4GreeksRealtimeSource()
    provider = source.accept_frame(frame, observed_at=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc))
    assert provider is source.provider
    assert provider.current_delta() == Decimal("0.5123")
    assert provider.current_gamma() == Decimal("0.0182")
    assert provider.current_theta() == Decimal("-0.034")
    assert provider.active_vol() == Decimal("0.247")


def test_non_greeks_frame_does_not_replace_provider():
    source = KISTrack4GreeksRealtimeSource()
    assert source.accept_frame("0|H0IFCNT0|1|A", observed_at=datetime(2026, 9, 22, 10, 0)) is None


def test_realtime_source_facade_updates_after_accept_frame():
    from datetime import datetime, timezone
    from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource
    values = [""] * 58
    values[0] = "201S11305"
    values[28] = "0.41"
    values[29] = "0.017"
    values[31] = "-0.03"
    values[33] = "0.22"
    source = KISTrack4GreeksRealtimeSource()
    observed_at = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)
    assert source.provider is None
    source.accept_frame(f"0|H0IOCNT0|58|{'^'.join(values)}", observed_at=observed_at)
    assert source.current_delta() == Decimal("0.41")
    assert source.current_gamma() == Decimal("0.017")
    assert source.snapshot.observed_at == observed_at.isoformat()
