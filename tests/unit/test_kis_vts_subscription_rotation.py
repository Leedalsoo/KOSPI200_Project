import json
from pathlib import Path

from scripts.kis_vts_websocket_collector import (
    _append_subscription_event,
    plan_subscription_rotation,
    write_subscription_events_manifest,
)


def test_rotation_prefers_subscribe_first_when_within_cap():
    active = {('OPT', f'A{i}') for i in range(29)}
    desired = {('OPT', f'A{i}') for i in range(6, 35)}
    plan = plan_subscription_rotation(active, desired, cap=41)
    assert len(plan['additions']) == 6
    assert len(plan['removals']) == 6
    assert plan['subscribe_first'] is True
    assert plan['peak_active'] == 35
    assert plan['gap_expected'] is False


def test_rotation_unsubscribes_first_when_additions_would_exceed_cap():
    active = {('OPT', f'A{i}') for i in range(41)}
    desired = {('OPT', f'A{i}') for i in range(20, 61)}
    plan = plan_subscription_rotation(active, desired, cap=41)
    assert plan['subscribe_first'] is False
    assert plan['peak_active'] == 41
    assert plan['gap_expected'] is True
    assert len(plan['additions']) == 20
    assert len(plan['removals']) == 20


def test_rotation_noop_has_no_gap_or_messages():
    active = {('OPT', 'A1'), ('INDEX', '2001')}
    plan = plan_subscription_rotation(active, active, cap=41)
    assert plan['additions'] == []
    assert plan['removals'] == []
    assert plan['gap_expected'] is False


def test_rotation_rejects_plan_over_cap():
    active = {('OPT', f'A{i}') for i in range(42)}
    try:
        plan_subscription_rotation(active, active, cap=41)
    except ValueError as exc:
        assert 'KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:42' in str(exc)
    else:
        raise AssertionError('expected subscription cap rejection')


def test_subscription_manifest_hashes_sidecar_and_links_raw_evidence(tmp_path: Path):
    day_dir = tmp_path / '2026-10-12'
    events = day_dir / 'kis_vts_subscription_events.jsonl'
    _append_subscription_event(events, event={'event': 'ROTATION_COMPLETED', 'raw_frames_file': 'kis_vts_websocket_raw.jsonl'})
    raw_manifest = {'schema': 'kis-realtime-raw-manifest-v1', 'file_sha256': 'abc123', 'record_count': 7}
    path = write_subscription_events_manifest(day_dir, initial_subscriptions=(('INDEX', '2001'),), raw_manifest=raw_manifest)
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload['event_count'] == 1
    assert len(payload['event_file_sha256']) == 64
    assert payload['raw_manifest_schema'] == 'kis-realtime-raw-manifest-v1'
    assert payload['raw_file_sha256'] == 'abc123'
    assert payload['raw_record_count'] == 7
    assert payload['initial_subscriptions'] == [{'tr_id': 'INDEX', 'symbol': '2001'}]
