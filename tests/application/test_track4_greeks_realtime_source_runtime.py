from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from contracts.track4_kis_greeks_ws_adapter import KISIndexOptionGreeksWebSocketAdapter
from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource


class _Scenario:
    @staticmethod
    def active_config():
        return {}


def _synthetic_h0iocnt0_frame(
    instrument_id: str,
    *,
    delta: str = "0.31",
    gamma: str = "0.017",
    theta: str = "-0.42",
    iv: str = "24.5",
) -> str:
    values = [""] * 58
    values[0] = instrument_id
    values[1] = "101500"
    values[28] = delta
    values[29] = gamma
    values[31] = theta
    values[33] = iv
    return "0|H0IOCNT0|1|" + "^".join(values)


def _tick(instrument_id: str, observed_at: datetime) -> ReferenceCanonicalMarketTick:
    return ReferenceCanonicalMarketTick(
        timestamp=observed_at.isoformat(),
        underlying_price=350.0,
        strike_price=350.0,
        last_price=10.0,
        seq_id=1,
        expiry="20261210",
        symbol=instrument_id,
        instrument_id=instrument_id,
    )


def test_synthetic_h0iocnt0_frame_reaches_virtual_runtime_with_exact_identity_and_time() -> None:
    observed_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    source = KISTrack4GreeksRealtimeSource()

    provider = source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id),
        observed_at=observed_at,
    )

    assert provider is not None
    assert provider.snapshot.instrument_id == instrument_id
    assert provider.snapshot.observed_at == observed_at.isoformat()
    assert provider.current_delta() == Decimal("0.31")
    assert provider.current_gamma() == Decimal("0.017")
    assert provider.current_theta() == Decimal("-0.42")
    assert provider.active_vol() == Decimal("24.5")

    market = type("Market", (), {
        "recent_ticks": [_tick(instrument_id, observed_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    runtime = VirtualRuntimeDataProvider(
        market,
        track4_greeks_provider=source,
    ).snapshot(market.recent_ticks[0])

    assert runtime.option_delta == Decimal("0.31")
    assert runtime.option_gamma == Decimal("0.017")


def test_synthetic_source_refresh_is_visible_to_existing_runtime_provider_facade() -> None:
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    first_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    second_at = datetime(2026, 11, 23, 10, 15, 1, tzinfo=timezone.utc)
    source = KISTrack4GreeksRealtimeSource()
    source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.31", gamma="0.017"),
        observed_at=first_at,
    )
    market = type("Market", (), {
        "recent_ticks": [_tick(instrument_id, second_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    runtime_provider = VirtualRuntimeDataProvider(
        market,
        track4_greeks_provider=source,
    )

    before = runtime_provider.snapshot(market.recent_ticks[0])
    assert before.option_delta is None
    assert before.option_gamma is None

    source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.33", gamma="0.019"),
        observed_at=second_at,
    )
    after = runtime_provider.snapshot(market.recent_ticks[0])

    assert after.option_delta == Decimal("0.33")
    assert after.option_gamma == Decimal("0.019")


def test_realtime_source_uses_caller_timestamp_not_payload_bsop_hour() -> None:
    received_at = datetime(2026, 11, 23, 10, 15, 2, tzinfo=timezone.utc)
    payload_hour = "091501"
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    values = [""] * 58
    values[0] = instrument_id
    values[1] = payload_hour
    values[28] = "0.31"
    values[29] = "0.017"
    values[31] = "-0.42"
    values[33] = "24.5"
    frame = "0|H0IOCNT0|1|" + "^".join(values)

    provider = KISTrack4GreeksRealtimeSource().accept_frame(
        frame,
        observed_at=received_at,
    )

    assert provider is not None
    assert provider.snapshot.observed_at == received_at.isoformat()
    assert provider.snapshot.observed_at != "2026-11-23T09:15:01+09:00"


def test_greeks_adapter_can_decode_each_synthetic_record_but_source_facade_is_single_provider() -> None:
    first = [""] * 58
    second = [""] * 58
    first[0] = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    second[0] = "SYNTHETIC_CONTRACT:TRACK4-PUT-350"
    for values in (first, second):
        values[1] = "091501"
        values[28] = "0.31"
        values[29] = "0.017"
        values[31] = "-0.42"
        values[33] = "24.5"
    frame = "0|H0IOCNT0|2|" + "^".join(first + second)
    observed_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)

    decoded = KISIndexOptionGreeksWebSocketAdapter().adapt_many(
        frame,
        observed_at=observed_at.isoformat(),
    )
    source = KISTrack4GreeksRealtimeSource()
    current = source.accept_frame(frame, observed_at=observed_at)

    assert [item.snapshot.instrument_id for item in decoded] == [
        "SYNTHETIC_CONTRACT:TRACK4-CALL-350",
        "SYNTHETIC_CONTRACT:TRACK4-PUT-350",
    ]
    assert current is not None
    assert current.snapshot.instrument_id == "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    assert source.snapshot.instrument_id != "SYNTHETIC_CONTRACT:TRACK4-PUT-350"


def test_duplicate_synthetic_frame_is_reprocessed_without_deduplication() -> None:
    observed_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    frame = _synthetic_h0iocnt0_frame(
        "SYNTHETIC_CONTRACT:TRACK4-CALL-350",
        delta="0.31",
    )
    source = KISTrack4GreeksRealtimeSource()

    first = source.accept_frame(frame, observed_at=observed_at)
    second = source.accept_frame(frame, observed_at=observed_at)

    assert first is not None
    assert second is not None
    assert first is not second
    assert first.snapshot == second.snapshot
    assert source.provider is second


def test_older_synthetic_frame_overwrites_newer_track4_snapshot() -> None:
    newer_at = datetime(2026, 11, 23, 10, 15, 2, tzinfo=timezone.utc)
    older_at = datetime(2026, 11, 23, 10, 15, 1, tzinfo=timezone.utc)
    source = KISTrack4GreeksRealtimeSource()
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"

    newer = source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.35"),
        observed_at=newer_at,
    )
    older = source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.31"),
        observed_at=older_at,
    )

    assert newer is not None
    assert older is not None
    assert source.provider is older
    assert source.snapshot.observed_at == older_at.isoformat()
    assert source.current_delta() == Decimal("0.31")


def test_reordered_payload_clock_is_ignored_in_favor_of_caller_receive_order() -> None:
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    source = KISTrack4GreeksRealtimeSource()
    first_received_at = datetime(2026, 11, 23, 10, 15, 2, tzinfo=timezone.utc)
    second_received_at = datetime(2026, 11, 23, 10, 15, 3, tzinfo=timezone.utc)

    first_values = [""] * 58
    second_values = [""] * 58
    for values, payload_hour, delta in (
        (first_values, "101502", "0.35"),
        (second_values, "101501", "0.31"),
    ):
        values[0] = instrument_id
        values[1] = payload_hour
        values[28] = delta
        values[29] = "0.017"
        values[31] = "-0.42"
        values[33] = "24.5"

    first = source.accept_frame(
        "0|H0IOCNT0|1|" + "^".join(first_values),
        observed_at=first_received_at,
    )
    second = source.accept_frame(
        "0|H0IOCNT0|1|" + "^".join(second_values),
        observed_at=second_received_at,
    )

    assert first is not None
    assert second is not None
    assert second.snapshot.observed_at == second_received_at.isoformat()
    assert second.snapshot.observed_at > first.snapshot.observed_at
    assert source.current_delta() == Decimal("0.31")
