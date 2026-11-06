from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core.strategy.track6_order_lifecycle import Track6LifecycleConfig, Track6OrderLifecycle
from environments.high_speed.validation_only_track6_execution import (
    SYNTHETIC_ID_PREFIX,
    Track6SyntheticExecutionGate,
)

DATASET = "data/derived_scenario/q25_a3_1_s6_budget_fit"
MANIFEST = "reports/synth/Q25_A3_1_S6_BUDGET_FIT_MANIFEST_20261105.json"
RISK_PROFILE = "config/validation_only/q25_s6_v1/risk_profile.json"


def test_track6_lifecycle_persists_group_identity_across_restart():
    lifecycle = Track6OrderLifecycle(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"),
        run_id="Q25-RESTART-GROUP",
        trading_date="20261102",
    )
    lifecycle.start_preflight(
        (SimpleNamespace(rank=5),),
        datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        group_id="Q25-RESTART-GROUP-track6-20261102",
    )
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"),
        lifecycle.export_snapshot(),
    )
    assert restored.snapshot.group_id == "Q25-RESTART-GROUP-track6-20261102"


def test_track6_validation_gate_restores_cumulative_group_budget_after_restart():
    gate = Track6SyntheticExecutionGate(
        dataset=DATASET, manifest_path=MANIFEST, risk_profile_path=RISK_PROFILE,
    )
    group_id = "Q25-RESTART-GROUP-track6-20261102"
    gate.sync_group_reservation(group_id, {
        "put": {
            "client_order_id": "P-RESTORED",
            "instrument_id": f"{SYNTHETIC_ID_PREFIX}PUT",
            "premium_krw": "287500.00",
        },
    })
    assert gate._group_premium_by_leg[group_id]["put"]["premium_krw"] == "287500.00"

    gate.sync_group_reservation(group_id, {
        "put": {
            "client_order_id": "P-RESTORED",
            "instrument_id": f"{SYNTHETIC_ID_PREFIX}PUT",
            "premium_krw": "287500.00",
        },
        "call": {
            "client_order_id": "C-RESTORED",
            "instrument_id": f"{SYNTHETIC_ID_PREFIX}CALL",
            "premium_krw": "335000.00",
        },
    })
    assert set(gate._group_premium_by_leg[group_id]) == {"put", "call"}


def test_track6_validation_gate_fails_closed_when_restored_group_exceeds_budget():
    gate = Track6SyntheticExecutionGate(
        dataset=DATASET, manifest_path=MANIFEST, risk_profile_path=RISK_PROFILE,
    )
    with pytest.raises(ValueError, match="RESTORED_GROUP_BUDGET_EXCEEDED"):
        gate.sync_group_reservation("Q25-OVER-BUDGET", {
            "put": {
                "client_order_id": "P-RESTORED",
                "instrument_id": f"{SYNTHETIC_ID_PREFIX}PUT",
                "premium_krw": "325000.00",
            },
            "call": {
                "client_order_id": "C-RESTORED",
                "instrument_id": f"{SYNTHETIC_ID_PREFIX}CALL",
                "premium_krw": "300000.00",
            },
        })
