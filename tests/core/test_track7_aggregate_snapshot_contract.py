import hashlib
import json
from dataclasses import fields
from datetime import datetime
from decimal import Decimal

import pytest

from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7State,
    Track7VolatilitySkewWeeklyInsurance,
)


SCHEMA_VERSION = 1


def _encode_value(value):
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"unsupported Track7 snapshot value: {type(value).__name__}")


def _decode_value(value):
    if isinstance(value, dict) and value.get("$type") == "decimal":
        return Decimal(value["value"])
    if isinstance(value, dict) and value.get("$type") == "datetime":
        return datetime.fromisoformat(value["value"])
    return value


def _state_to_payload(state):
    return {item.name: _encode_value(getattr(state, item.name)) for item in fields(Track7State)}


def _state_from_payload(payload):
    expected = {item.name for item in fields(Track7State)}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("TRACK7_SNAPSHOT_STATE_FIELDS_INVALID")
    return Track7State(**{key: _decode_value(value) for key, value in payload.items()})


def _seal(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"payload": payload, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _open_sealed(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise ValueError("TRACK7_SNAPSHOT_ENVELOPE_INVALID")
    payload = envelope["payload"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != envelope["sha256"]:
        raise ValueError("TRACK7_SNAPSHOT_INTEGRITY_MISMATCH")
    return payload


def _capture_aggregate(strategy):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": strategy.strategy_id,
        "strategy_version": strategy.version,
        "config": {
            "insurance_qty": strategy.insurance_qty,
            "runtime_config_verified": strategy.runtime_config_verified,
            "risk_limits_available": strategy.risk_limits_available,
        },
        "legacy_state": _state_to_payload(strategy._legacy_state),
        "active_expiry": strategy._active_expiry,
        "states_by_expiry": [
            [expiry, _state_to_payload(state)]
            for expiry, state in sorted(strategy._states_by_expiry.items())
        ],
        "group_expiry": [[group, expiry] for group, expiry in sorted(strategy._group_expiry.items())],
        "legacy_exit_pending": strategy._legacy_exit_pending,
        "exit_pending_expiries": sorted(strategy._exit_pending_expiries),
    }
    return _seal(payload)


def _restore_aggregate(envelope, *, x2_latched=False, expected_config=None):
    payload = _open_sealed(envelope)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("TRACK7_SNAPSHOT_SCHEMA_VERSION_UNSUPPORTED")
    if payload.get("strategy_id") != Track7VolatilitySkewWeeklyInsurance.strategy_id:
        raise ValueError("TRACK7_SNAPSHOT_STRATEGY_ID_MISMATCH")
    if payload.get("strategy_version") != Track7VolatilitySkewWeeklyInsurance.version:
        raise ValueError("TRACK7_SNAPSHOT_STRATEGY_VERSION_MISMATCH")
    required = {
        "schema_version", "strategy_id", "strategy_version", "config", "legacy_state",
        "active_expiry", "states_by_expiry", "group_expiry", "legacy_exit_pending",
        "exit_pending_expiries",
    }
    if set(payload) != required:
        raise ValueError("TRACK7_SNAPSHOT_FIELDS_INVALID")

    config = payload["config"]
    if not isinstance(config, dict) or set(config) != {
        "insurance_qty", "runtime_config_verified", "risk_limits_available"
    }:
        raise ValueError("TRACK7_SNAPSHOT_CONFIG_INVALID")
    if expected_config is not None and config != expected_config:
        raise ValueError("TRACK7_SNAPSHOT_CONFIG_MISMATCH")
    strategy = Track7VolatilitySkewWeeklyInsurance(**config)
    strategy._legacy_state = _state_from_payload(payload["legacy_state"])

    states = {}
    for pair in payload["states_by_expiry"]:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("TRACK7_SNAPSHOT_EXPIRY_STATE_INVALID")
        expiry, raw_state = pair
        state = _state_from_payload(raw_state)
        if expiry in states or state.expiry != expiry:
            raise ValueError("TRACK7_SNAPSHOT_EXPIRY_STATE_CONFLICT")
        states[expiry] = state
    strategy._states_by_expiry = states

    groups = {}
    for pair in payload["group_expiry"]:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("TRACK7_SNAPSHOT_GROUP_BINDING_INVALID")
        group, expiry = pair
        if group in groups:
            raise ValueError("TRACK7_SNAPSHOT_DUPLICATE_GROUP_BINDING")
        if expiry not in states:
            raise ValueError("TRACK7_SNAPSHOT_GROUP_EXPIRY_UNKNOWN")
        groups[group] = expiry
    strategy._group_expiry = groups

    strategy._active_expiry = payload["active_expiry"]
    if strategy._active_expiry is not None and strategy._active_expiry not in states:
        raise ValueError("TRACK7_SNAPSHOT_ACTIVE_EXPIRY_UNKNOWN")
    strategy._legacy_exit_pending = payload["legacy_exit_pending"]
    strategy._exit_pending_expiries = set(payload["exit_pending_expiries"])
    if not strategy._exit_pending_expiries.issubset(states):
        raise ValueError("TRACK7_SNAPSHOT_EXIT_PENDING_EXPIRY_UNKNOWN")

    # X2 is an admission/action gate, not a reason to discard observed strategy state.
    return strategy, {"state_restored": True, "side_effect_actions_allowed": not x2_latched}


def _multi_expiry_strategy():
    strategy = Track7VolatilitySkewWeeklyInsurance(
        insurance_qty=2, runtime_config_verified=True, risk_limits_available=True
    )
    first = Track7State(
        expiry="20261126", insurance_active=True, put_open=True,
        reference_price=Decimal("512.5"), put_peak_mark=Decimal("1.25"),
        put_entry_filled_at=datetime.fromisoformat("2026-11-20T09:10:00+09:00"),
    )
    second = Track7State(
        expiry="20261203", entry_pending=True, entry_stage="CALL_PENDING",
        call_client_order_id="synthetic-call-2",
        call_submitted_at=datetime.fromisoformat("2026-11-20T09:11:00+09:00"),
        call_peak_mark=Decimal("2.75"),
    )
    strategy._states_by_expiry = {first.expiry: first, second.expiry: second}
    strategy._active_expiry = second.expiry
    strategy._group_expiry = {"synthetic-group-a": first.expiry, "synthetic-group-b": second.expiry}
    strategy._exit_pending_expiries = {first.expiry}
    strategy._legacy_state = Track7State(entry_block_reason="legacy-preserved")
    strategy._legacy_exit_pending = True
    return strategy


def test_track7_aggregate_snapshot_round_trips_multiple_expiries_groups_and_legacy_state():
    source = _multi_expiry_strategy()
    restored, gate = _restore_aggregate(_capture_aggregate(source))

    assert restored._legacy_state == source._legacy_state
    assert restored._active_expiry == source._active_expiry
    assert restored._states_by_expiry == source._states_by_expiry
    assert restored._group_expiry == source._group_expiry
    assert restored._legacy_exit_pending is True
    assert restored._exit_pending_expiries == source._exit_pending_expiries
    assert restored.insurance_qty == 2
    assert gate == {"state_restored": True, "side_effect_actions_allowed": True}


def test_track7_aggregate_snapshot_rejects_unsupported_schema_version():
    envelope = _capture_aggregate(_multi_expiry_strategy())
    envelope["payload"]["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="SCHEMA_VERSION_UNSUPPORTED"):
        _restore_aggregate(_seal(envelope["payload"]))


def test_track7_aggregate_snapshot_rejects_corruption_and_missing_state_fields():
    envelope = _capture_aggregate(_multi_expiry_strategy())
    envelope["payload"]["active_expiry"] = "20261126"
    with pytest.raises(ValueError, match="INTEGRITY_MISMATCH"):
        _restore_aggregate(envelope)

    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    del payload["states_by_expiry"][0][1]["put_open"]
    with pytest.raises(ValueError, match="STATE_FIELDS_INVALID"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_duplicate_group_binding():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["group_expiry"].append(payload["group_expiry"][0])
    with pytest.raises(ValueError, match="DUPLICATE_GROUP_BINDING"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_group_binding_to_unknown_expiry():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["group_expiry"][0][1] = "20261210"
    with pytest.raises(ValueError, match="GROUP_EXPIRY_UNKNOWN"):
        _restore_aggregate(_seal(payload))


def test_track7_x2_latched_restore_preserves_state_but_disallows_side_effect_actions():
    restored, gate = _restore_aggregate(_capture_aggregate(_multi_expiry_strategy()), x2_latched=True)

    assert restored._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert restored._group_expiry["synthetic-group-b"] == "20261203"
    assert gate["state_restored"] is True
    assert gate["side_effect_actions_allowed"] is False


def _restore_observe_then_gate(envelope, *, x2_latched, reconcile_observation, side_effect_action):
    """Test-only ordering harness; it does not call any broker or runtime port."""
    strategy, gate = _restore_aggregate(envelope, x2_latched=x2_latched)
    events = ["state_restored"]
    reconcile_observation(strategy)
    events.append("authoritative_observation_reconciled")
    if gate["side_effect_actions_allowed"]:
        side_effect_action(strategy)
        events.append("side_effect_action")
    return strategy, events


def test_track7_aggregate_snapshot_rejects_strategy_identity_and_version_mismatch():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["strategy_id"] = "different.synthetic.strategy"
    with pytest.raises(ValueError, match="STRATEGY_ID_MISMATCH"):
        _restore_aggregate(_seal(payload))

    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["strategy_version"] = "999.synthetic"
    with pytest.raises(ValueError, match="STRATEGY_VERSION_MISMATCH"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_expected_validation_config_mismatch():
    source = _multi_expiry_strategy()
    expected = {
        "insurance_qty": 3,
        "runtime_config_verified": True,
        "risk_limits_available": True,
    }
    with pytest.raises(ValueError, match="CONFIG_MISMATCH"):
        _restore_aggregate(_capture_aggregate(source), expected_config=expected)


def test_track7_aggregate_snapshot_rejects_unknown_active_and_exit_pending_expiry():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["active_expiry"] = "20261210"
    with pytest.raises(ValueError, match="ACTIVE_EXPIRY_UNKNOWN"):
        _restore_aggregate(_seal(payload))

    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["exit_pending_expiries"] = ["20261210"]
    with pytest.raises(ValueError, match="EXIT_PENDING_EXPIRY_UNKNOWN"):
        _restore_aggregate(_seal(payload))


def test_track7_restore_order_reconciles_observations_before_any_action_when_x2_open():
    events = []
    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=False,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )
    assert restored._active_expiry == "20261203"
    assert observed == ["state_restored", "authoritative_observation_reconciled", "side_effect_action"]
    assert [item[0] for item in events] == ["reconcile", "action"]


def test_track7_restore_order_under_x2_reconciles_observation_but_skips_side_effects():
    events = []
    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=True,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )
    assert restored._active_expiry == "20261203"
    assert restored._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert observed == ["state_restored", "authoritative_observation_reconciled"]
    assert [item[0] for item in events] == ["reconcile"]
