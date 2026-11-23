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


def test_sequential_multi_instrument_frames_expose_only_last_instrument_to_runtime() -> None:
    call_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    put_id = "SYNTHETIC_CONTRACT:TRACK4-PUT-350"
    call_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    put_at = datetime(2026, 11, 23, 10, 15, 1, tzinfo=timezone.utc)
    source = KISTrack4GreeksRealtimeSource()

    call_provider = source.accept_frame(
        _synthetic_h0iocnt0_frame(call_id, delta="0.42", gamma="0.021"),
        observed_at=call_at,
    )
    assert call_provider is not None
    source.accept_frame(
        _synthetic_h0iocnt0_frame(put_id, delta="-0.38", gamma="0.019"),
        observed_at=put_at,
    )

    call_market = type("CallMarket", (), {
        "recent_ticks": [_tick(call_id, call_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    put_market = type("PutMarket", (), {
        "recent_ticks": [_tick(put_id, put_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    call_runtime = VirtualRuntimeDataProvider(
        call_market,
        track4_greeks_provider=source,
    ).snapshot(call_market.recent_ticks[0])
    put_runtime = VirtualRuntimeDataProvider(
        put_market,
        track4_greeks_provider=source,
    ).snapshot(put_market.recent_ticks[0])

    assert call_runtime.option_delta is None
    assert call_runtime.option_gamma is None
    assert put_runtime.option_delta == Decimal("-0.38")
    assert put_runtime.option_gamma == Decimal("0.019")
    assert source.snapshot.instrument_id == put_id
def test_new_collector_session_does_not_reset_existing_greeks_source(tmp_path) -> None:
    import asyncio
    from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    class Transport:
        def __init__(self):
            self.connects = 0
            self.subscriptions = []
            self.closes = 0
        async def connect(self):
            self.connects += 1
        async def subscribe(self, tr_id, symbol):
            self.subscriptions.append((tr_id, symbol))
        async def recv(self):
            raise AssertionError('recv is outside this boundary test')
        async def close(self):
            self.closes += 1

    old_at = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)
    source = KISTrack4GreeksRealtimeSource()
    old_provider = source.accept_frame(
        _synthetic_h0iocnt0_frame('SYNTHETIC_CONTRACT:TRACK4-CALL-350'),
        observed_at=old_at,
    )
    transport = Transport()
    collector = KISRealtimeCollector(
        transport,
        KISRealtimeRawStore(tmp_path / 'raw.jsonl'),
        frame_observer=lambda frame, received_at: source.accept_frame(frame, observed_at=received_at),
    )

    asyncio.run(collector.start('20261123', [('H0IOCNT0', 'SYNTHETIC-CALL-OLD')]))
    asyncio.run(collector.start('20261124', [('H0IOCNT0', 'SYNTHETIC-PUT-NEW')]))

    assert old_provider is not None
    assert transport.connects == 2
    assert transport.subscriptions == [('H0IOCNT0', 'SYNTHETIC-CALL-OLD'), ('H0IOCNT0', 'SYNTHETIC-PUT-NEW')]
    assert transport.closes == 0
    assert not hasattr(transport, 'unsubscribe')
    assert source.provider is old_provider
    assert source.snapshot.instrument_id == 'SYNTHETIC_CONTRACT:TRACK4-CALL-350'
    assert source.snapshot.observed_at == old_at.isoformat()

def test_synthetic_expiry_session_subscription_plan_is_dry_run_only() -> None:
    from infrastructure.kis.kis_subscription_planner import build_subscription_plan

    plan = build_subscription_plan(
        now=datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc),
        trading_day_approved=True,
        active_strategies=['S4'],
        strategy_required_symbols={
            'S4': ['SYNTHETIC_CONTRACT:TRACK4-CALL-350-20261210'],
        },
        contracts={
            'SYNTHETIC_CONTRACT:TRACK4-CALL-350-20261210': {
                'instrument_type': 'OPTION',
                'product_series': 'MONTHLY',
                'option_type': 'CALL',
                'strike': '350',
                'expiry_yyyymmdd': '20261210',
                'identity_valid': True,
                'expiry_provenance_valid': True,
                'master_age_hours': 0,
            },
        },
    )

    assert plan['mode'] == 'DRY_RUN_PLAN_ONLY'
    assert plan['strategy_status']['S4']['status'] == 'PLANNED'
    assert ('H0IOCNT0', 'SYNTHETIC_CONTRACT:TRACK4-CALL-350-20261210') in {
        (item['tr_id'], item['symbol']) for item in plan['subscriptions']
    }
    assert plan['safety']['collector_touched'] is False
    assert plan['safety']['websocket_opened'] is False
    assert plan['rotation']['automatic_rotation_enabled'] is False
    assert plan['rotation']['status'] == 'BLOCKED_THRESHOLDS_UNSET'

def test_synthetic_reconnect_resubscribes_without_unsubscribe_or_ack_wait(tmp_path) -> None:
    import asyncio
    from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    class Transport:
        def __init__(self):
            self.connects = 0
            self.subscriptions = []
            self.closes = 0
            self.recv_calls = 0
        async def connect(self):
            self.connects += 1
        async def subscribe(self, tr_id, symbol):
            self.subscriptions.append((tr_id, symbol))
        async def recv(self):
            self.recv_calls += 1
            if self.recv_calls == 1:
                raise ConnectionError('synthetic disconnect')
            return '0|H0IOCNT0|1|SYNTHETIC-CONTRACT-RECONNECT'
        async def close(self):
            self.closes += 1

    transport = Transport()
    collector = KISRealtimeCollector(
        transport,
        KISRealtimeRawStore(tmp_path / 'reconnect.jsonl'),
        max_reconnects=1,
    )
    asyncio.run(collector.start('20261123', [('H0IOCNT0', 'SYNTHETIC-CONTRACT-RECONNECT')]))
    record = asyncio.run(collector.capture_one())

    assert record['instrument'] == 'SYNTHETIC-CONTRACT-RECONNECT'
    assert transport.connects == 2
    assert transport.subscriptions == [
        ('H0IOCNT0', 'SYNTHETIC-CONTRACT-RECONNECT'),
        ('H0IOCNT0', 'SYNTHETIC-CONTRACT-RECONNECT'),
    ]
    assert transport.closes == 0
    assert transport.recv_calls == 2


def test_synthetic_websocket_subscribe_send_returns_without_ack_correlation() -> None:
    import asyncio
    import json
    from infrastructure.kis.futures_market_transport import KISFuturesMarketTransport

    class Approval:
        def issue(self):
            return 'SYNTHETIC-APPROVAL-KEY'

    class Socket:
        def __init__(self):
            self.sent = []
        async def send(self, payload):
            self.sent.append(payload)

    transport = object.__new__(KISFuturesMarketTransport)
    transport._approval = Approval()
    transport._socket = Socket()
    transport._connected = True
    asyncio.run(transport.subscribe('H0IOCNT0', 'SYNTHETIC-CONTRACT-ACK'))

    assert len(transport._socket.sent) == 1
    message = json.loads(transport._socket.sent[0])
    assert message['header']['tr_type'] == '1'
    assert message['body']['input']['tr_id'] == 'H0IOCNT0'
    assert message['body']['input']['tr_key'] == 'SYNTHETIC-CONTRACT-ACK'
    assert not hasattr(transport, 'wait_for_subscription_ack')

def test_synthetic_subscription_ack_json_is_not_accepted_as_market_data_frame(tmp_path) -> None:
    import asyncio
    from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    class Transport:
        async def connect(self):
            return None
        async def subscribe(self, tr_id, symbol):
            return None
        async def recv(self):
            return '{"header":{"tr_id":"H0IOCNT0"},"body":{"msg_cd":"SUBSCRIBE_OK","msg1":"synthetic ack"}}'
        async def close(self):
            return None

    store = KISRealtimeRawStore(tmp_path / 'ack.jsonl')
    collector = KISRealtimeCollector(Transport(), store)
    asyncio.run(collector.start('20261123', [('H0IOCNT0', 'SYNTHETIC-CONTRACT-ACK')]))

    try:
        asyncio.run(collector.capture_one())
    except ValueError as exc:
        assert str(exc) == 'RAW_FRAME_TR_ID_REQUIRED'
    else:
        raise AssertionError('JSON subscription ACK must not be treated as an H0IOCNT0 market frame')
    assert store.count() == 0


def test_synthetic_session_rollover_stale_greeks_are_excluded_by_runtime_identity_and_time() -> None:
    old_at = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)
    new_session_at = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)
    old_id = 'SYNTHETIC_CONTRACT:TRACK4-CALL-350-20261210'
    new_id = 'SYNTHETIC_CONTRACT:TRACK4-CALL-350-20261217'
    source = KISTrack4GreeksRealtimeSource()
    source.accept_frame(_synthetic_h0iocnt0_frame(old_id), observed_at=old_at)

    same_contract_market = type('Market', (), {
        'recent_ticks': [_tick(old_id, new_session_at)],
        'underlying_history': [],
        'scenario': _Scenario(),
    })()
    same_contract = VirtualRuntimeDataProvider(
        same_contract_market, track4_greeks_provider=source,
    ).snapshot(same_contract_market.recent_ticks[0])

    next_expiry_market = type('Market', (), {
        'recent_ticks': [_tick(new_id, old_at)],
        'underlying_history': [],
        'scenario': _Scenario(),
    })()
    next_expiry = VirtualRuntimeDataProvider(
        next_expiry_market, track4_greeks_provider=source,
    ).snapshot(next_expiry_market.recent_ticks[0])

    assert same_contract.option_delta is None
    assert same_contract.option_gamma is None
    assert next_expiry.option_delta is None
    assert next_expiry.option_gamma is None
    replay_market = type('Market', (), {
        'recent_ticks': [_tick(old_id, old_at)],
        'underlying_history': [],
        'scenario': _Scenario(),
    })()
    exact_replay = VirtualRuntimeDataProvider(
        replay_market, track4_greeks_provider=source,
    ).snapshot(replay_market.recent_ticks[0])
    assert exact_replay.option_delta == Decimal('0.31')
    assert exact_replay.option_gamma == Decimal('0.017')

def test_synthetic_json_control_frame_parse_error_bubbles_without_collector_reconnect(tmp_path) -> None:
    import asyncio
    from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    class Transport:
        def __init__(self):
            self.connects = 0
            self.closes = 0

        async def connect(self):
            self.connects += 1

        async def subscribe(self, tr_id, symbol):
            return None

        async def recv(self):
            return '{"header":{"tr_id":"H0IOCNT0"},"body":{"msg_cd":"SUBSCRIBE_OK"}}'

        async def close(self):
            self.closes += 1

    transport = Transport()
    store = KISRealtimeRawStore(tmp_path / 'control-frame.jsonl')
    collector = KISRealtimeCollector(transport, store, max_reconnects=2)
    asyncio.run(collector.start('20261123', [('H0IOCNT0', 'SYNTHETIC-CONTROL-FRAME')]))

    try:
        asyncio.run(collector.capture_one())
    except ValueError as exc:
        assert str(exc) == 'RAW_FRAME_TR_ID_REQUIRED'
    else:
        raise AssertionError('synthetic JSON control frame must remain outside market-frame parsing')

    assert transport.connects == 1
    assert transport.closes == 0
    assert store.count() == 0
