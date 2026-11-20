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
    if isinstance(value, dict):
        if "$type" in value:
            if set(value) != {"$type", "value"}:
                raise ValueError("TRACK7_SNAPSHOT_TAGGED_VALUE_INVALID")
            if value["$type"] == "decimal":
                try:
                    return Decimal(value["value"])
                except Exception as exc:
                    raise ValueError("TRACK7_SNAPSHOT_DECIMAL_INVALID") from exc
            if value["$type"] == "datetime":
                try:
                    return datetime.fromisoformat(value["value"])
                except Exception as exc:
                    raise ValueError("TRACK7_SNAPSHOT_DATETIME_INVALID") from exc
            raise ValueError("TRACK7_SNAPSHOT_TAG_UNSUPPORTED")
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
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
    if (type(config["insurance_qty"]) is not int or config["insurance_qty"] <= 0
            or type(config["runtime_config_verified"]) is not bool
            or type(config["risk_limits_available"]) is not bool):
        raise ValueError("TRACK7_SNAPSHOT_CONFIG_TYPES_INVALID")
    strategy = Track7VolatilitySkewWeeklyInsurance(**config)
    strategy._legacy_state = _state_from_payload(payload["legacy_state"])

    raw_states = payload["states_by_expiry"]
    if not isinstance(raw_states, list):
        raise ValueError("TRACK7_SNAPSHOT_EXPIRY_STATES_INVALID")
    states = {}
    for pair in raw_states:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("TRACK7_SNAPSHOT_EXPIRY_STATE_INVALID")
        expiry, raw_state = pair
        if not isinstance(expiry, str) or not expiry:
            raise ValueError("TRACK7_SNAPSHOT_EXPIRY_ID_INVALID")
        state = _state_from_payload(raw_state)
        if expiry in states or state.expiry != expiry:
            raise ValueError("TRACK7_SNAPSHOT_EXPIRY_STATE_CONFLICT")
        states[expiry] = state
    strategy._states_by_expiry = states

    raw_groups = payload["group_expiry"]
    if not isinstance(raw_groups, list):
        raise ValueError("TRACK7_SNAPSHOT_GROUP_BINDINGS_INVALID")
    groups = {}
    for pair in raw_groups:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("TRACK7_SNAPSHOT_GROUP_BINDING_INVALID")
        group, expiry = pair
        if not isinstance(group, str) or not group or not isinstance(expiry, str) or not expiry:
            raise ValueError("TRACK7_SNAPSHOT_GROUP_BINDING_ID_INVALID")
        if group in groups:
            raise ValueError("TRACK7_SNAPSHOT_DUPLICATE_GROUP_BINDING")
        if expiry not in states:
            raise ValueError("TRACK7_SNAPSHOT_GROUP_EXPIRY_UNKNOWN")
        groups[group] = expiry
    strategy._group_expiry = groups

    strategy._active_expiry = payload["active_expiry"]
    if (strategy._active_expiry is not None
            and (not isinstance(strategy._active_expiry, str) or not strategy._active_expiry)):
        raise ValueError("TRACK7_SNAPSHOT_ACTIVE_EXPIRY_INVALID")
    if strategy._active_expiry is not None and strategy._active_expiry not in states:
        raise ValueError("TRACK7_SNAPSHOT_ACTIVE_EXPIRY_UNKNOWN")
    if type(payload["legacy_exit_pending"]) is not bool:
        raise ValueError("TRACK7_SNAPSHOT_LEGACY_EXIT_PENDING_INVALID")
    pending_expiries = payload["exit_pending_expiries"]
    if (not isinstance(pending_expiries, list)
            or any(not isinstance(item, str) for item in pending_expiries)
            or len(pending_expiries) != len(set(pending_expiries))):
        raise ValueError("TRACK7_SNAPSHOT_EXIT_PENDING_EXPIRIES_INVALID")
    strategy._legacy_exit_pending = payload["legacy_exit_pending"]
    strategy._exit_pending_expiries = set(pending_expiries)
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


def _restore_aggregate_into(target, envelope, *, x2_latched=False, expected_config=None):
    """Test-only staged restore: validate a complete candidate before swapping state."""
    staged, gate = _restore_aggregate(
        envelope, x2_latched=x2_latched, expected_config=expected_config
    )
    target.__dict__ = staged.__dict__.copy()
    return gate


def _compare_restored_group_observations(strategy, observations):
    """Read-only synthetic comparison; it neither mutates state nor triggers actions."""
    comparisons = {}
    for group_id, observed in observations.items():
        expiry = strategy._group_expiry.get(group_id)
        if expiry is None:
            comparisons[group_id] = {"status": "UNMAPPED_GROUP"}
            continue
        if observed.get("expiry") != expiry:
            comparisons[group_id] = {
                "status": "EXPIRY_MISMATCH",
                "snapshot_expiry": expiry,
                "observed_expiry": observed.get("expiry"),
            }
            continue
        state = strategy._states_by_expiry.get(expiry)
        if state is None:
            comparisons[group_id] = {"status": "SNAPSHOT_STATE_MISSING", "expiry": expiry}
            continue
        expected_marks = {
            "put_peak_mark": state.put_peak_mark,
            "call_peak_mark": state.call_peak_mark,
        }
        mark_mismatches = {
            key: {"snapshot": value, "observed": observed.get(key)}
            for key, value in expected_marks.items()
            if value != observed.get(key)
        }
        comparisons[group_id] = {
            "status": "MATCH" if not mark_mismatches else "MARK_MISMATCH",
            "expiry": expiry,
            "mark_mismatches": mark_mismatches,
        }
    return comparisons


def _restore_observe_then_gate(envelope, *, x2_latched, reconcile_observation, side_effect_action):
    """Test-only ordering harness; re-reads the explicit X2 gate after observation."""
    strategy, _ = _restore_aggregate(envelope)
    events = ["state_restored"]
    reconcile_observation(strategy)
    events.append("authoritative_observation_reconciled")

    # A previously latched state is never inferred to be open. The current
    # gate must return an explicit bool; read errors/unknown values suppress action.
    try:
        current_x2_latched = x2_latched() if callable(x2_latched) else x2_latched
    except Exception:
        events.append("x2_gate_read_failed")
        return strategy, events

    if type(current_x2_latched) is not bool:
        events.append("x2_gate_read_invalid")
        return strategy, events

    events.append("x2_gate_rechecked_latched" if current_x2_latched else "x2_gate_rechecked_open")
    if not current_x2_latched:
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
    assert observed == ["state_restored", "authoritative_observation_reconciled", "x2_gate_rechecked_open", "side_effect_action"]
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
    assert observed == ["state_restored", "authoritative_observation_reconciled", "x2_gate_rechecked_latched"]
    assert [item[0] for item in events] == ["reconcile"]



def test_track7_restore_rechecks_x2_and_suppresses_action_if_latched_during_observation():
    events = []
    gate = {"latched": False}

    def reconcile(strategy):
        events.append(("reconcile", strategy._active_expiry))
        gate["latched"] = True

    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=lambda: gate["latched"],
        reconcile_observation=reconcile,
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )

    assert restored._active_expiry == "20261203"
    assert observed == [
        "state_restored", "authoritative_observation_reconciled",
        "x2_gate_rechecked_latched",
    ]
    assert [item[0] for item in events] == ["reconcile"]


def test_track7_latched_x2_is_not_auto_unlatched():
    events = []
    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=True,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )

    assert restored._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert observed[-1] == "x2_gate_rechecked_latched"
    assert [item[0] for item in events] == ["reconcile"]


def test_track7_explicit_open_gate_read_is_required_before_action():
    events = []
    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=lambda: False,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )

    assert restored._active_expiry == "20261203"
    assert observed == [
        "state_restored", "authoritative_observation_reconciled",
        "x2_gate_rechecked_open", "side_effect_action",
    ]
    assert [item[0] for item in events] == ["reconcile", "action"]


def test_track7_restore_x2_gate_read_exception_preserves_state_and_suppresses_action():
    events = []

    def failed_gate_read():
        raise RuntimeError("synthetic gate read failure")

    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=failed_gate_read,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )

    assert restored._active_expiry == "20261203"
    assert restored._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert observed == [
        "state_restored", "authoritative_observation_reconciled", "x2_gate_read_failed"
    ]
    assert [item[0] for item in events] == ["reconcile"]


@pytest.mark.parametrize("unknown_gate_value", [None, "OPEN", 0, 1])
def test_track7_restore_x2_gate_unknown_value_preserves_state_and_suppresses_action(
    unknown_gate_value,
):
    events = []
    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=lambda: unknown_gate_value,
        reconcile_observation=lambda strategy: events.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: events.append(("action", strategy._active_expiry)),
    )

    assert restored._active_expiry == "20261203"
    assert observed == [
        "state_restored", "authoritative_observation_reconciled", "x2_gate_read_invalid"
    ]
    assert [item[0] for item in events] == ["reconcile"]


def test_track7_aggregate_snapshot_rejects_duplicate_expiry_state_records():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["states_by_expiry"].append(payload["states_by_expiry"][0])
    with pytest.raises(ValueError, match="EXPIRY_STATE_CONFLICT"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_duplicate_exit_pending_expiry():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["exit_pending_expiries"].append(payload["exit_pending_expiries"][0])
    with pytest.raises(ValueError, match="EXIT_PENDING_EXPIRIES_INVALID"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_invalid_tagged_decimal_datetime_and_unknown_tag():
    for field, invalid in (
        ("reference_price", {"$type": "decimal", "value": "not-a-decimal"}),
        ("put_entry_filled_at", {"$type": "datetime", "value": "not-a-datetime"}),
        ("reference_price", {"$type": "pickle", "value": "opaque"}),
    ):
        payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
        payload["states_by_expiry"][0][1][field] = invalid
        expected = (
            "DECIMAL_INVALID" if invalid["$type"] == "decimal"
            else "DATETIME_INVALID" if invalid["$type"] == "datetime"
            else "TAG_UNSUPPORTED"
        )
        with pytest.raises(ValueError, match=expected):
            _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_config_type_confusion():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["config"]["insurance_qty"] = True
    with pytest.raises(ValueError, match="CONFIG_TYPES_INVALID"):
        _restore_aggregate(_seal(payload))


def test_track7_aggregate_snapshot_rejects_malformed_tagged_value_envelope():
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["states_by_expiry"][0][1]["reference_price"] = {
        "$type": "decimal", "value": "1.25", "unexpected": "field"
    }
    with pytest.raises(ValueError, match="TAGGED_VALUE_INVALID"):
        _restore_aggregate(_seal(payload))



def test_track7_aggregate_restore_validation_failure_leaves_target_state_unchanged():
    target = _multi_expiry_strategy()
    before = target.__dict__.copy()
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    payload["states_by_expiry"][0][1]["reference_price"] = {
        "$type": "decimal", "value": "not-a-decimal"
    }

    with pytest.raises(ValueError, match="DECIMAL_INVALID"):
        _restore_aggregate_into(target, _seal(payload))

    assert target.__dict__ == before


def test_track7_aggregate_restore_config_mismatch_leaves_target_state_unchanged():
    target = _multi_expiry_strategy()
    before = target.__dict__.copy()
    expected = {
        "insurance_qty": 3,
        "runtime_config_verified": True,
        "risk_limits_available": True,
    }

    with pytest.raises(ValueError, match="CONFIG_MISMATCH"):
        _restore_aggregate_into(
            target, _capture_aggregate(_multi_expiry_strategy()),
            expected_config=expected,
        )

    assert target.__dict__ == before


def test_track7_aggregate_restore_swaps_state_only_after_full_validation():
    target = Track7VolatilitySkewWeeklyInsurance(
        insurance_qty=1, runtime_config_verified=False, risk_limits_available=False
    )
    before = target.__dict__.copy()

    gate = _restore_aggregate_into(
        target, _capture_aggregate(_multi_expiry_strategy()), x2_latched=True
    )

    assert target.__dict__ != before
    assert target._active_expiry == "20261203"
    assert target._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert gate == {"state_restored": True, "side_effect_actions_allowed": False}



@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda payload: payload["states_by_expiry"].append(
                ["20261210", {**payload["states_by_expiry"][1][1], "expiry": "20261217"}]
            ),
            "EXPIRY_STATE_CONFLICT",
        ),
        (
            lambda payload: payload["group_expiry"].append(["", "20261126"]),
            "GROUP_BINDING_ID_INVALID",
        ),
        (
            lambda payload: payload["group_expiry"].append(["synthetic-group-c", "20261210"]),
            "GROUP_EXPIRY_UNKNOWN",
        ),
        (
            lambda payload: payload.update({"active_expiry": 17}),
            "ACTIVE_EXPIRY_INVALID",
        ),
    ],
)
def test_track7_aggregate_restore_late_multi_expiry_group_failure_is_atomic(mutate, error):
    target = _multi_expiry_strategy()
    before = target.__dict__.copy()
    payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
    mutate(payload)

    with pytest.raises(ValueError, match=error):
        _restore_aggregate_into(target, _seal(payload))

    assert target.__dict__ == before


def test_track7_aggregate_snapshot_rejects_non_list_expiry_and_group_collections():
    for field, invalid in (
        ("states_by_expiry", {"20261126": {"expiry": "20261126"}}),
        ("group_expiry", {"synthetic-group-a": "20261126"}),
    ):
        payload = _open_sealed(_capture_aggregate(_multi_expiry_strategy()))
        payload[field] = invalid
        expected = "EXPIRY_STATES_INVALID" if field == "states_by_expiry" else "GROUP_BINDINGS_INVALID"
        with pytest.raises(ValueError, match=expected):
            _restore_aggregate(_seal(payload))



def test_track7_restored_multi_group_routing_matches_synthetic_observations_read_only():
    source = _multi_expiry_strategy()
    restored, _ = _restore_aggregate(_capture_aggregate(source))
    before = restored.__dict__.copy()
    observations = {
        "synthetic-group-a": {
            "expiry": "20261126",
            "put_peak_mark": Decimal("1.25"),
            "call_peak_mark": Decimal("0"),
        },
        "synthetic-group-b": {
            "expiry": "20261203",
            "put_peak_mark": Decimal("0"),
            "call_peak_mark": Decimal("2.75"),
        },
    }

    result = _compare_restored_group_observations(restored, observations)

    assert {group: item["status"] for group, item in result.items()} == {
        "synthetic-group-a": "MATCH",
        "synthetic-group-b": "MATCH",
    }
    assert restored.__dict__ == before


def test_track7_restored_observation_discrepancies_are_reported_without_state_mutation():
    source = _multi_expiry_strategy()
    restored, _ = _restore_aggregate(_capture_aggregate(source))
    before = restored.__dict__.copy()
    observations = {
        "synthetic-group-a": {
            "expiry": "20261203",
            "put_peak_mark": Decimal("1.25"),
            "call_peak_mark": None,
        },
        "synthetic-group-b": {
            "expiry": "20261203",
            "put_peak_mark": None,
            "call_peak_mark": Decimal("2.50"),
        },
        "synthetic-group-unmapped": {
            "expiry": "20261203",
            "put_peak_mark": None,
            "call_peak_mark": None,
        },
    }

    result = _compare_restored_group_observations(restored, observations)

    assert result["synthetic-group-a"] == {
        "status": "EXPIRY_MISMATCH",
        "snapshot_expiry": "20261126",
        "observed_expiry": "20261203",
    }
    assert result["synthetic-group-b"]["status"] == "MARK_MISMATCH"
    assert result["synthetic-group-unmapped"] == {"status": "UNMAPPED_GROUP"}
    assert restored.__dict__ == before


def _read_x2_gate_with_test_retries(reads):
    """Test-only explicit gate-read retry probe; never invokes side-effect ports."""
    diagnostics = []
    for read_result in reads:
        try:
            value = read_result() if callable(read_result) else read_result
        except Exception:
            diagnostics.append("read_failed")
            continue
        if type(value) is not bool:
            diagnostics.append("read_invalid")
            continue
        state = "latched" if value else "open"
        diagnostics.append(f"read_{state}")
        return state, diagnostics
    return "unavailable", diagnostics


def test_track7_x2_retry_does_not_unlatch_after_read_failure_without_explicit_open():
    def failed_read():
        raise RuntimeError("synthetic unavailable")

    state, diagnostics = _read_x2_gate_with_test_retries([failed_read, None, "OPEN", 1])

    assert state == "unavailable"
    assert diagnostics == ["read_failed", "read_invalid", "read_invalid", "read_invalid"]


def test_track7_x2_retry_preserves_latched_state_when_later_read_is_latched():
    def failed_read():
        raise RuntimeError("synthetic unavailable")

    state, diagnostics = _read_x2_gate_with_test_retries([failed_read, True])

    assert state == "latched"
    assert diagnostics == ["read_failed", "read_latched"]


def test_track7_x2_retry_only_recognizes_explicit_exact_false_as_open():
    def failed_read():
        raise RuntimeError("synthetic unavailable")

    state, diagnostics = _read_x2_gate_with_test_retries([failed_read, False])

    assert state == "open"
    assert diagnostics == ["read_failed", "read_open"]


def test_track7_x2_retry_never_invokes_side_effects_and_requires_fresh_open_recheck():
    effects = []

    def failed_read():
        raise RuntimeError("synthetic unavailable")

    retry_state, retry_diagnostics = _read_x2_gate_with_test_retries([failed_read, False])
    assert retry_state == "open"
    assert retry_diagnostics == ["read_failed", "read_open"]
    assert effects == []

    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=lambda: False,
        reconcile_observation=lambda strategy: effects.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: effects.append(("action", strategy._active_expiry)),
    )

    assert restored._active_expiry == "20261203"
    assert observed[-2:] == ["x2_gate_rechecked_open", "side_effect_action"]
    assert [item[0] for item in effects] == ["reconcile", "action"]


def test_track7_x2_retry_later_latched_read_suppresses_all_side_effects():
    effects = []

    retry_state, _ = _read_x2_gate_with_test_retries([True, True])
    assert retry_state == "latched"

    restored, observed = _restore_observe_then_gate(
        _capture_aggregate(_multi_expiry_strategy()),
        x2_latched=lambda: True,
        reconcile_observation=lambda strategy: effects.append(("reconcile", strategy._active_expiry)),
        side_effect_action=lambda strategy: effects.append(("action", strategy._active_expiry)),
    )

    assert restored._states_by_expiry["20261203"].entry_stage == "CALL_PENDING"
    assert observed[-1] == "x2_gate_rechecked_latched"
    assert [item[0] for item in effects] == ["reconcile"]



def test_track7_x2_latched_state_changes_only_after_later_explicit_false_read():
    prior_state, _ = _read_x2_gate_with_test_retries([True])
    later_state, diagnostics = _read_x2_gate_with_test_retries([False])

    assert prior_state == "latched"
    assert later_state == "open"
    assert diagnostics == ["read_open"]



def _dispatch_test_actions_with_fresh_x2_reads(actions, gate_reads):
    """Test-only per-action gate probe; callbacks are synthetic recorders only."""
    events = []
    read_iter = iter(gate_reads)
    for action_name, callback in actions:
        try:
            gate = next(read_iter)
            gate = gate() if callable(gate) else gate
        except (StopIteration, Exception):
            events.append((action_name, "gate_unavailable"))
            continue
        if type(gate) is not bool:
            events.append((action_name, "gate_invalid"))
            continue
        if gate is True:
            events.append((action_name, "x2_latched"))
            continue
        callback()
        events.append((action_name, "synthetic_callback_invoked"))
    return events


def test_track7_x2_each_side_effect_candidate_requires_its_own_fresh_gate_read():
    invoked = []
    actions = [
        ("cancel", lambda: invoked.append("cancel")),
        ("repair", lambda: invoked.append("repair")),
        ("retry", lambda: invoked.append("retry")),
        ("flatten", lambda: invoked.append("flatten")),
        ("new_submission", lambda: invoked.append("new_submission")),
    ]

    events = _dispatch_test_actions_with_fresh_x2_reads(
        actions, [False, False, False, False, False]
    )

    assert invoked == ["cancel", "repair", "retry", "flatten", "new_submission"]
    assert all(status == "synthetic_callback_invoked" for _, status in events)


def test_track7_x2_gate_transition_suppresses_later_action_candidates():
    invoked = []
    actions = [
        ("cancel", lambda: invoked.append("cancel")),
        ("repair", lambda: invoked.append("repair")),
        ("retry", lambda: invoked.append("retry")),
        ("flatten", lambda: invoked.append("flatten")),
        ("new_submission", lambda: invoked.append("new_submission")),
    ]

    events = _dispatch_test_actions_with_fresh_x2_reads(
        actions, [False, True, True, True, True]
    )

    assert invoked == ["cancel"]
    assert events == [
        ("cancel", "synthetic_callback_invoked"),
        ("repair", "x2_latched"),
        ("retry", "x2_latched"),
        ("flatten", "x2_latched"),
        ("new_submission", "x2_latched"),
    ]


def test_track7_x2_invalid_or_failed_per_action_read_suppresses_only_that_candidate():
    invoked = []

    def failed_read():
        raise RuntimeError("synthetic gate read failure")

    actions = [
        ("cancel", lambda: invoked.append("cancel")),
        ("repair", lambda: invoked.append("repair")),
        ("retry", lambda: invoked.append("retry")),
        ("flatten", lambda: invoked.append("flatten")),
        ("new_submission", lambda: invoked.append("new_submission")),
    ]

    events = _dispatch_test_actions_with_fresh_x2_reads(
        actions, [False, None, failed_read, 1, False]
    )

    assert invoked == ["cancel", "new_submission"]
    assert events == [
        ("cancel", "synthetic_callback_invoked"),
        ("repair", "gate_invalid"),
        ("retry", "gate_unavailable"),
        ("flatten", "gate_invalid"),
        ("new_submission", "synthetic_callback_invoked"),
    ]


def test_track7_x2_missing_gate_read_never_reuses_previous_open_value():
    invoked = []
    actions = [
        ("cancel", lambda: invoked.append("cancel")),
        ("repair", lambda: invoked.append("repair")),
    ]

    events = _dispatch_test_actions_with_fresh_x2_reads(actions, [False])

    assert invoked == ["cancel"]
    assert events == [
        ("cancel", "synthetic_callback_invoked"),
        ("repair", "gate_unavailable"),
    ]


def test_track7_x2_gate_read_to_callback_window_is_not_atomic():
    gate_state = {"latched": False}
    callback_gate_states = []

    def read_then_transition():
        observed = gate_state["latched"]
        # Deterministic scheduler-boundary stand-in: X2 latches after the
        # read returns its value but before the dispatcher invokes callback.
        gate_state["latched"] = True
        return observed

    events = _dispatch_test_actions_with_fresh_x2_reads(
        [("cancel", lambda: callback_gate_states.append(gate_state["latched"]))],
        [read_then_transition],
    )

    # Characterize the existing limitation; this is not a safety-pass claim.
    # A stale open read can reach the callback after X2 has become latched.
    assert gate_state["latched"] is True
    assert callback_gate_states == [True]
    assert events == [("cancel", "synthetic_callback_invoked")]


def test_track7_x2_final_gate_recheck_still_has_callback_toctou_window():
    gate_state = {"latched": False}
    callback_gate_states = []
    read_count = {"value": 0}

    def gate_read():
        read_count["value"] += 1
        observed = gate_state["latched"]
        if read_count["value"] == 2:
            # X2 latches after the final read returns but before callback.
            gate_state["latched"] = True
        return observed

    def final_recheck_then_callback():
        if gate_read() is False:
            callback_gate_states.append(gate_state["latched"])

    events = _dispatch_test_actions_with_fresh_x2_reads(
        [("cancel", final_recheck_then_callback)],
        [gate_read],
    )

    # A second read narrows the window but cannot make check-and-act atomic.
    assert read_count["value"] == 2
    assert gate_state["latched"] is True
    assert callback_gate_states == [True]
    assert events == [("cancel", "synthetic_callback_invoked")]
