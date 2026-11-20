from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_runtime_invariant_checker import (
    ValidationOnlyRuntimeInvariantChecker,
)
from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from application.composition.validation_only_vssf_runtime_evidence_adapter import (
    ValidationOnlyVSSFRuntimeEvidenceAdapter,
)
from core.oms.track2_u19_recovery import U19RecoveryStatus, evaluate_u19_recovery

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "SYNTHETIC:T7:S2-CANDIDATE-001"


def _runtime_fixture(provider_timestamp: str):
    scenario_time = datetime.fromisoformat(provider_timestamp)
    candidate_path = (
        ROOT / "data" / "derived_scenario"
        / "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
        / "four_leg_quotes.jsonl"
    )
    rows = [
        __import__("json").loads(line)
        for line in candidate_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [row for row in rows if row["candidate_id"] == "S2-CANDIDATE-001"]
    reports = []
    lots = []
    fees = []
    provenance = {}
    execution_legs = {}
    positions = {}
    for row in rows:
        role = row["leg_role"]
        side = (
            "BUY" if role in {"inner_put", "inner_call"} else "SELL"
        )
        instrument_id = row["instrument_id"]
        execution_id = f"SYNTHETIC:T7:EXEC:{role}"
        client_order_id = f"SYNTHETIC:T7:ORDER:{role}"
        price = Decimal(str(row["ask"] if side == "BUY" else row["bid"]))
        multiplier = Decimal(str(row["contract_multiplier"]))
        fee = Decimal(1000)
        report = SimpleNamespace(
            client_order_id=client_order_id,
            broker_order_id=f"SYNTHETIC:T7:BROKER:{role}",
            execution_id=execution_id,
            status="FILLED",
            filled_quantity=1,
            remaining_quantity=0,
            execution_price=price,
            execution_timestamp=scenario_time,
            fee=fee,
            group_id="SYNTHETIC:T7:GROUP",
            leg_id=role,
        )
        reports.append(report)
        provenance[execution_id] = {
            "group_id": report.group_id,
            "leg_id": role,
            "instrument_id": instrument_id,
            "symbol": instrument_id,
        }
        execution_legs[execution_id] = {
            "side": side,
            "contract_multiplier": multiplier,
            "asset_type": "OPTION",
        }
        lots.append(SimpleNamespace(
            run_id=RUN_ID,
            instrument_id=instrument_id,
            execution_id=execution_id,
            side=side,
            opened_quantity=1,
            remaining_quantity=1,
            execution_timestamp=scenario_time,
            contract_multiplier=multiplier,
        ))
        fees.append(SimpleNamespace(
            execution_id=execution_id,
            fee_amount=fee,
            executed_quantity=1,
            executed_price=price,
        ))
        positions[instrument_id] = {
            "side": side,
            "qty": 1,
            "avg_price": price,
            "mark_price": price,
        }
    bridge = SimpleNamespace(
        run_id=RUN_ID,
        groups={"SYNTHETIC:T7:GROUP": tuple(reports)},
        provenance=provenance,
        execution_legs=execution_legs,
        pending_legs={},
        position_lot_store=SimpleNamespace(
            history=lambda: tuple(lots),
            open_lots=lambda: tuple(lots),
            close_events=lambda: (),
        ),
        fee_ledger=SimpleNamespace(snapshot=lambda *, run_id: tuple(fees)),
    )
    runtime = SimpleNamespace(
        account=SimpleNamespace(
            positions=positions,
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
    )
    return bridge, runtime


def _provider(tick_timestamp: str):
    bridge, runtime = _runtime_fixture(tick_timestamp)
    adapter = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge, vssf_runtime=runtime, run_id=RUN_ID,
    )
    return ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=ROOT,
        run_id=RUN_ID,
        vssf_adapter=adapter,
        position_phase="POST_ENTRY",
    )


def test_t7_s2_alternative_builds_independent_broker_snapshot_and_freshness_candidate():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:00+09:00",
    )
    candidate = _provider(tick.timestamp)(tick, ())

    assert candidate is not None
    assert candidate.broker_snapshot.source == "VALIDATION_ONLY:BROKER_EXCHANGE"
    assert candidate.ledger_snapshot.source == "VALIDATION_ONLY:EXECUTION_LEDGER"
    assert candidate.freshness_verdict.status.value == "FRESH"
    assert len(candidate.broker_snapshot.positions) == 4
    assert len(candidate.ledger_snapshot.execution_events) == 4
    assert candidate.broker_snapshot.positions == candidate.ledger_snapshot.positions
    assert candidate.expected_group_manifest.source == "VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST"
    assert len(candidate.expected_group_manifest.leg_instrument_ids) == 4

    decision = evaluate_u19_recovery(
        group_id=candidate.group_id,
        broker_snapshot=candidate.broker_snapshot,
        ledger_snapshot=candidate.ledger_snapshot,
        expected_group_manifest=candidate.expected_group_manifest,
        require_expected_group_manifest=True,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    invariant_inputs = dict(candidate.invariant_inputs)
    invariant_inputs["u19_decision"] = decision
    result = ValidationOnlyRuntimeInvariantChecker().check(**invariant_inputs)
    assert result.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert result.issues == ()


def test_t7_s2_alternative_returns_none_for_unrelated_tick():
    tick = SimpleNamespace(
        candidate_id="OTHER-CANDIDATE",
        timestamp="2026-10-12T09:26:00+09:00",
    )

    assert _provider(tick.timestamp)(tick, ()) is None


def test_t7_s2_alternative_does_not_claim_fresh_after_five_second_synthetic_age():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:06+09:00",
    )
    candidate = _provider(tick.timestamp)(tick, ())

    assert candidate.freshness_verdict.status.value == "STALE"
    assert candidate.freshness_verdict.reason == "SOURCE_AGE_EXCEEDS_APPROVED_THRESHOLD"


def test_t7_s2_alternative_rejects_tick_before_scenario_time():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:25:59+09:00",
    )

    import pytest

    with pytest.raises(ValueError, match="T7_TICK_PRECEDES_SYNTHETIC_SCENARIO"):
        _provider(tick.timestamp)(tick, ())

def test_t7_s2_alternative_runs_after_primary_and_reconciliation_are_unavailable():
    from application.composition.validation_only_runtime_evidence_supervisor import (
        ValidationOnlyRuntimeEvidenceSupervisor,
    )

    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:00+09:00",
    )
    provider = _provider(tick.timestamp)

    class _StopSwitch:
        def __init__(self):
            self.calls = []

        def evaluate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status="ARMED")

    class _Recovery:
        def recover(self, *, group_id, broker_snapshot, ledger_snapshot, expected_group_manifest=None):
            return evaluate_u19_recovery(
                group_id=group_id,
                broker_snapshot=broker_snapshot,
                ledger_snapshot=ledger_snapshot,
                expected_group_manifest=expected_group_manifest,
                require_expected_group_manifest=True,
            )

    stop_switch = _StopSwitch()
    supervisor = ValidationOnlyRuntimeEvidenceSupervisor(
        stop_switch=stop_switch,
        invariant_checker=ValidationOnlyRuntimeInvariantChecker(),
        u19_recovery_coordinator=_Recovery(),
        risk_guard_status_source=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                admission_allowed=True,
                kill_switch_engaged=False,
                reason="HEALTHY",
            )
        ),
        primary_provider=lambda _tick: None,
        reconciliation_provider=lambda _tick, _attempts: None,
        alternative_provider=provider,
    )

    result = supervisor.evaluate(tick)

    assert result.candidate_source == "PROVENANCE_PRESERVING_ALTERNATIVE"
    assert result.attempts == (
        "PRIMARY_ACCEPTED_ORIGINAL:EVIDENCE_UNAVAILABLE",
        "NOTION_AND_SOURCE_RECONCILIATION:EVIDENCE_UNAVAILABLE",
        "PROVENANCE_PRESERVING_ALTERNATIVE:VALIDATED",
    )
    assert result.u19_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.invariant_report.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert result.stop_snapshot.status == "ARMED"
    assert len(stop_switch.calls) == 1


def test_t8_pre_entry_alternative_uses_flat_independent_broker_snapshot():
    tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        underlying_price=1034.62,
    )
    bridge = SimpleNamespace(
        run_id=RUN_ID,
        groups={},
        provenance={},
        execution_legs={},
        pending_legs={},
        position_lot_store=SimpleNamespace(
            history=lambda: (),
            open_lots=lambda: (),
            close_events=lambda: (),
        ),
        fee_ledger=SimpleNamespace(snapshot=lambda *, run_id: ()),
    )
    runtime = SimpleNamespace(
        account=SimpleNamespace(
            positions={},
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
    )
    adapter = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge, vssf_runtime=runtime, run_id=RUN_ID,
    )
    provider = ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=ROOT,
        run_id=RUN_ID,
        vssf_adapter=adapter,
    )

    assert provider.is_applicable(tick)
    candidate = provider(tick, ())

    assert candidate is not None
    assert candidate.broker_snapshot.positions == ()
    assert candidate.ledger_snapshot.positions == ()
    assert candidate.ledger_snapshot.execution_events == ()
    decision = evaluate_u19_recovery(
        group_id=candidate.group_id,
        broker_snapshot=candidate.broker_snapshot,
        ledger_snapshot=candidate.ledger_snapshot,
        expected_group_manifest=candidate.expected_group_manifest,
        require_expected_group_manifest=True,
    )
    assert decision.status is U19RecoveryStatus.FLAT_CONFIRMED
    invariant_inputs = dict(candidate.invariant_inputs)
    invariant_inputs["u19_decision"] = decision
    result = ValidationOnlyRuntimeInvariantChecker().check(**invariant_inputs)
    assert result.status == ValidationOnlyRuntimeInvariantChecker.PASS


def test_t8_provider_matches_real_replay_tick_without_candidate_id():
    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        underlying_price=1034.62,
    )
    assert provider.is_applicable(tick)
    candidate = provider(tick, ())
    assert candidate is not None


def test_t8_supervisor_skips_ticks_outside_all_evidence_scopes():
    from application.composition.validation_only_runtime_evidence_supervisor import (
        ValidationOnlyRuntimeEvidenceSupervisor,
    )
    provider = _provider("2026-10-12T09:26:00+09:00")

    class _ScopedUnavailable:
        def is_applicable(self, tick):
            return provider.is_applicable(tick)

        def __call__(self, tick, *args):
            return None

    class _StopSwitch:
        def __init__(self):
            self.evaluate_calls = 0

        def snapshot(self):
            return SimpleNamespace(status="ARMED")

        def evaluate(self, **kwargs):
            self.evaluate_calls += 1
            return SimpleNamespace(status="TRIPPED")

    class _Recovery:
        def recover(self, *, group_id, broker_snapshot, ledger_snapshot, expected_group_manifest=None):
            return evaluate_u19_recovery(
                group_id=group_id,
                broker_snapshot=broker_snapshot,
                ledger_snapshot=ledger_snapshot,
                expected_group_manifest=expected_group_manifest,
                require_expected_group_manifest=True,
            )

    stop = _StopSwitch()
    scoped = _ScopedUnavailable()
    supervisor = ValidationOnlyRuntimeEvidenceSupervisor(
        stop_switch=stop,
        invariant_checker=ValidationOnlyRuntimeInvariantChecker(),
        u19_recovery_coordinator=_Recovery(),
        risk_guard_status_source=SimpleNamespace(snapshot=lambda: None),
        primary_provider=scoped,
        reconciliation_provider=scoped,
        alternative_provider=provider,
    )

    result = supervisor.evaluate(SimpleNamespace(
        timestamp="2026-10-12T09:27:00+09:00",
        underlying_price=1034.70,
    ))

    assert result.stop_snapshot.status == "ARMED"
    assert result.attempts == (
        "PRIMARY_ACCEPTED_ORIGINAL:TICK_OUTSIDE_EVIDENCE_SCOPE",
        "NOTION_AND_SOURCE_RECONCILIATION:TICK_OUTSIDE_EVIDENCE_SCOPE",
        "PROVENANCE_PRESERVING_ALTERNATIVE:TICK_OUTSIDE_EVIDENCE_SCOPE",
    )
    assert stop.evaluate_calls == 0

def test_t17_market_calibrated_quotes_are_four_leg_synthetic_and_exact_time_scoped():
    from datetime import timedelta

    provider = _provider("2026-10-12T09:26:00+09:00")
    scenario_time = datetime.fromisoformat("2026-10-12T09:26:00+09:00")

    quotes = provider.option_quotes_at(scenario_time)

    assert len(quotes) == 4
    assert {key[0] for key in quotes} == {"CALL", "PUT"}
    assert all(
        row["source"] == "SYNTHETIC:DERIVED_SCENARIO"
        for row in quotes.values()
    )
    assert all(row["validation_only"] is True for row in quotes.values())
    assert all(
        row["contract_identity_authority"] == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
        for row in quotes.values()
    )
    assert provider.option_quotes_at(scenario_time + timedelta(seconds=1)) == {}


def test_t17_synthetic_evidence_retains_anchor_lineage_and_no_lookahead():
    import json

    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:00+09:00",
    )
    provider = _provider(tick.timestamp)
    candidate = provider(tick, ())
    assert candidate is not None

    inputs = candidate.invariant_inputs
    ledger = inputs["ledger_evidence"]
    scenario_time = datetime.fromisoformat("2026-10-12T09:26:00+09:00")
    anchor_time = ledger["source_anchor_as_of"]

    assert inputs["source_namespace"] == "SYNTHETIC:DERIVED_SCENARIO"
    assert inputs["deterministic_rule_id"] == provider.VERSION
    assert len(inputs["source_manifest_sha256"]) == 64
    assert anchor_time.tzinfo is not None
    assert anchor_time <= scenario_time
    assert ledger["scenario_timestamp"] == scenario_time
    assert inputs["source_anchor_refs"]
    assert inputs["evidence_refs"]
    allowed_prefixes = (
        "accepted_runtime_v2_manifest#",
        "s2_scenario_manifest#",
        "source_anchor:",
        "source_observation:",
    )
    assert all(
        ref.startswith(allowed_prefixes)
        for ref in inputs["source_anchor_refs"]
    )

    scenario_dir = (
        ROOT
        / "data"
        / "derived_scenario"
        / "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
    )
    quote_path = scenario_dir / "four_leg_quotes.jsonl"
    quote_rows = [
        json.loads(line)
        for line in quote_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    quote_rows = [
        row for row in quote_rows
        if row["candidate_id"] == "S2-CANDIDATE-001"
    ]
    assert len(quote_rows) == 4

    for row in quote_rows:
        calibration = row["market_calibration"]
        anchor_values = (
            tuple(calibration["iv_anchor_timestamps"])
            + tuple(calibration["spread_anchor_timestamps"])
        )
        assert anchor_values
        assert all(
            datetime.fromisoformat(value) <= scenario_time
            for value in anchor_values
        )
        assert len(calibration["iv_anchor_observation_ids"]) == len(
            calibration["iv_anchor_timestamps"]
        )
        assert len(calibration["spread_anchor_observation_ids"]) == len(
            calibration["spread_anchor_timestamps"]
        )


def test_t17_synthetic_freshness_exact_five_second_boundary_is_fresh():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:05+09:00",
    )
    candidate = _provider(tick.timestamp)(tick, ())

    assert candidate.freshness_verdict.status.value == "FRESH"


def test_t17_source_observed_and_collected_times_remain_separate_from_synthetic_quote_time():
    import json
    from datetime import timezone

    provider = _provider("2026-10-12T09:26:00+09:00")
    manifest, candidate, _profile, quote_rows, _hashes = provider._load_verified_sources()
    candidate_time = datetime.fromisoformat(candidate["observed_at"])
    accepted_day = provider.accepted_manifest_path.parent / "20261012.jsonl"
    accepted_by_id = {}
    for line in accepted_day.read_text(encoding="utf-8").splitlines():
        source_row = json.loads(line)
        metadata = source_row.get("scenario_metadata", {})
        source_id = metadata.get("source_observation_id")
        if source_id:
            accepted_by_id[source_id] = source_row

    anchor_ids = set()
    for quote in quote_rows:
        calibration = quote["market_calibration"]
        anchor_ids.update(calibration["iv_anchor_observation_ids"])
        anchor_ids.update(calibration["spread_anchor_observation_ids"])
        assert quote["timestamp"] == candidate_time.isoformat()
        assert calibration["target_quote_age_seconds"] == 0

    assert len(quote_rows) == 4
    assert len(anchor_ids) == 12
    assert anchor_ids.issubset(accepted_by_id)
    anchor_ages = []
    collection_latencies = []
    for source_id in anchor_ids:
        source_row = accepted_by_id[source_id]
        metadata = source_row["scenario_metadata"]
        observed_at = datetime.fromisoformat(metadata["source_observed_at"])
        collected_at = datetime.fromisoformat(metadata["source_collected_at"])
        assert source_row["tick"]["timestamp"] == observed_at.isoformat()
        assert observed_at.tzinfo is not None and collected_at.tzinfo == timezone.utc
        assert len(metadata["source_raw_sha256"]) == 64
        assert len(metadata["source_canonical_sha256"]) == 64
        anchor_ages.append((candidate_time - observed_at).total_seconds())
        collection_latencies.append(
            (collected_at - observed_at.astimezone(timezone.utc)).total_seconds()
        )

    assert min(anchor_ages) >= 0
    assert max(anchor_ages) == 833
    assert max(anchor_ages) <= manifest["anchor_policy"]["max_source_anchor_age_seconds"]
    assert min(collection_latencies) >= 0
    assert collection_latencies


def test_t17_four_leg_synthetic_quotes_share_candidate_time_while_source_anchor_times_remain_distinct():
    provider = _provider("2026-10-12T09:26:00+09:00")
    manifest, candidate, _profile, quote_rows, _hashes = provider._load_verified_sources()
    candidate_time = datetime.fromisoformat(candidate["observed_at"])

    assert len(quote_rows) == 4
    assert {row["timestamp"] for row in quote_rows} == {candidate_time.isoformat()}
    for row in quote_rows:
        calibration = row["market_calibration"]
        anchors = tuple(calibration["iv_anchor_timestamps"]) + tuple(
            calibration["spread_anchor_timestamps"]
        )
        anchor_times = [datetime.fromisoformat(value) for value in anchors]
        ages = [(candidate_time - value).total_seconds() for value in anchor_times]
        assert len(anchor_times) == 12
        assert min(ages) >= 0
        assert max(ages) <= manifest["anchor_policy"]["max_source_anchor_age_seconds"]
        assert max(ages) - min(ages) > 0
        assert len(set(calibration["iv_anchor_observation_ids"])) == 6
        assert len(set(calibration["spread_anchor_observation_ids"])) == 6


def test_t17_all_s2_candidates_preserve_four_leg_time_alignment_and_source_anchor_lineage():
    import json

    provider = _provider("2026-10-12T09:26:00+09:00")
    manifest, _candidate, _profile, _quotes, _hashes = provider._load_verified_sources()
    scenario_rows = [
        json.loads(line)
        for line in (provider.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted_by_id = {}
    for day in ("20261012", "20261013"):
        source_path = provider.accepted_manifest_path.parent / f"{day}.jsonl"
        for line in source_path.read_text(encoding="utf-8").splitlines():
            source_row = json.loads(line)
            source_id = (source_row.get("scenario_metadata") or {}).get("source_observation_id")
            if source_id:
                accepted_by_id[source_id] = source_row

    all_anchor_ids = set()
    for candidate in manifest["candidate_calibration"]:
        group = [row for row in scenario_rows if row["candidate_id"] == candidate["candidate_id"]]
        candidate_time = datetime.fromisoformat(candidate["timestamp"])
        assert len(group) == 4
        assert {row["timestamp"] for row in group} == {candidate_time.isoformat()}
        assert {row["leg_role"] for row in group} == set(provider.ROLE_SIDE)
        for row in group:
            calibration = row["market_calibration"]
            anchor_pairs = (
                (calibration["iv_anchor_observation_ids"], calibration["iv_anchor_timestamps"]),
                (calibration["spread_anchor_observation_ids"], calibration["spread_anchor_timestamps"]),
            )
            for ids, timestamps in anchor_pairs:
                assert len(ids) == len(timestamps)
                for source_id, timestamp in zip(ids, timestamps):
                    all_anchor_ids.add(source_id)
                    source_row = accepted_by_id[source_id]
                    metadata = source_row["scenario_metadata"]
                    observed_at = datetime.fromisoformat(metadata["source_observed_at"])
                    assert timestamp == observed_at.isoformat()
                    assert source_row["tick"]["timestamp"] == observed_at.isoformat()
                    assert (candidate_time - observed_at).total_seconds() >= 0
                    assert (candidate_time - observed_at).total_seconds() <= manifest["anchor_policy"]["max_source_anchor_age_seconds"]
                    assert len(metadata["source_raw_sha256"]) == 64
                    assert len(metadata["source_canonical_sha256"]) == 64

    assert len(manifest["candidate_calibration"]) == 21
    assert len(scenario_rows) == 84
    assert len(all_anchor_ids) == 160
    assert all_anchor_ids.issubset(accepted_by_id)


def test_t17_cross_type_iv_and_spread_fallbacks_match_recorded_source_contract_types():
    import json

    provider = _provider("2026-10-13T08:49:10+09:00")
    manifest, _candidate, _profile, _quotes, _hashes = provider._load_verified_sources()
    scenario_rows = [
        json.loads(line)
        for line in (provider.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted_by_id = {}
    for day in ("20261012", "20261013"):
        source_path = provider.accepted_manifest_path.parent / f"{day}.jsonl"
        for line in source_path.read_text(encoding="utf-8").splitlines():
            source_row = json.loads(line)
            source_id = (source_row.get("scenario_metadata") or {}).get("source_observation_id")
            if source_id:
                accepted_by_id[source_id] = source_row

    for candidate in manifest["candidate_calibration"]:
        group = [row for row in scenario_rows if row["candidate_id"] == candidate["candidate_id"]]
        actual_cross_type_iv_legs = 0
        for row in group:
            target_type = row["option_type"]
            calibration = row["market_calibration"]
            iv_source_types = {
                accepted_by_id[source_id]["tick"]["option_type"]
                for source_id in calibration["iv_anchor_observation_ids"]
            }
            spread_source_types = {
                accepted_by_id[source_id]["tick"]["option_type"]
                for source_id in calibration["spread_anchor_observation_ids"]
            }
            iv_is_cross_type = str(calibration["iv_anchor_selection"]).startswith("CROSS_TYPE")
            spread_is_cross_type = str(calibration["spread_anchor_selection"]).startswith("CROSS_TYPE")
            expected_iv_type = "CALL" if target_type == "PUT" else "PUT"
            assert iv_source_types == ({expected_iv_type} if iv_is_cross_type else {target_type})
            assert spread_source_types == ({expected_iv_type} if spread_is_cross_type else {target_type})
            actual_cross_type_iv_legs += int(iv_is_cross_type)
        assert actual_cross_type_iv_legs == candidate["cross_type_iv_fallback_legs"]

    assert {
        candidate["candidate_id"]: candidate["cross_type_iv_fallback_legs"]
        for candidate in manifest["candidate_calibration"]
        if candidate["cross_type_iv_fallback_legs"]
    } == {"S2-CANDIDATE-007": 2, "S2-CANDIDATE-008": 2}


def test_t17_all_s2_candidate_iv_and_spread_medians_recompute_from_accepted_anchor_rows():
    import json
    from math import isclose
    from statistics import median
    from verification.track2_synthetic_quote_scenario import _market_implied_volatility

    provider = _provider("2026-10-13T08:49:10+09:00")
    scenario_rows = [
        json.loads(line)
        for line in (provider.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted_by_id = {}
    for day in ("20261012", "20261013"):
        source_path = provider.accepted_manifest_path.parent / f"{day}.jsonl"
        for line in source_path.read_text(encoding="utf-8").splitlines():
            source_row = json.loads(line)
            source_id = (source_row.get("scenario_metadata") or {}).get("source_observation_id")
            if source_id:
                accepted_by_id[source_id] = source_row

    assert len(scenario_rows) == 84
    for row in scenario_rows:
        calibration = row["market_calibration"]
        recomputed_iv = []
        for source_id in calibration["iv_anchor_observation_ids"]:
            source = accepted_by_id[source_id]["tick"]
            observed_at = datetime.fromisoformat(source["timestamp"])
            expiry_at = datetime.strptime(source["expiry"], "%Y%m%d").replace(
                hour=15, minute=20, second=0, microsecond=0, tzinfo=observed_at.tzinfo,
            )
            years = (expiry_at - observed_at).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
            mid = (float(source["bid_price"]) + float(source["ask_price"])) / 2.0
            value = _market_implied_volatility(
                float(source["underlying_price"]),
                float(source["strike_price"]),
                years,
                mid,
                source["option_type"],
            )
            assert value is not None
            recomputed_iv.append(value)
        assert isclose(
            median(recomputed_iv), float(calibration["implied_volatility"]),
            rel_tol=1e-12, abs_tol=1e-12,
        )

        spreads = [
            float(accepted_by_id[source_id]["tick"]["ask_price"])
            - float(accepted_by_id[source_id]["tick"]["bid_price"])
            for source_id in calibration["spread_anchor_observation_ids"]
        ]
        assert isclose(
            median(spreads), float(calibration["empirical_anchor_spread_median"]),
            rel_tol=1e-12, abs_tol=1e-12,
        )


def test_t17_all_84_quote_rows_match_tick_rounding_spread_limit_and_synthetic_provenance():
    import json
    from decimal import ROUND_HALF_UP
    from verification.track2_synthetic_quote_scenario import (
        _market_bs_price,
        validate_quote_snapshot,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    manifest, _candidate, _profile, _quotes, _hashes = provider._load_verified_sources()
    rows = [
        json.loads(line)
        for line in (provider.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tick = Decimal(manifest["u21"]["tick_size"])
    max_spread = Decimal(manifest["u21"]["max_spread"])
    assert len(rows) == 84

    for row in rows:
        bid, ask, last = (Decimal(row[key]) for key in ("bid", "ask", "last"))
        spread = ask - bid
        calibration = row["market_calibration"]
        assert row["source"] == "SYNTHETIC:DERIVED_SCENARIO"
        assert row["provenance"] == "SYNTHETIC"
        assert row["contract_identity_authority"] == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
        assert row["model"] == "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1"
        assert calibration["last_price_basis"] == "MODEL_FAIR_VALUE_NOT_OBSERVED_TRADE"
        assert row["source_manifest_sha256"] and len(row["source_manifest_sha256"]) == 64
        assert row["scenario_profile_sha256"] and len(row["scenario_profile_sha256"]) == 64
        assert row["source_observation_id"]
        assert "raw_payload_sha256" not in row
        assert bid > 0 and ask > bid and spread > 0
        assert bid % tick == ask % tick == last % tick == Decimal("0")
        assert spread <= max_spread

        empirical_spread = Decimal(calibration["empirical_anchor_spread_median"])
        spread_ticks = max(
            1,
            int((empirical_spread / tick).to_integral_value(rounding=ROUND_HALF_UP)),
        )
        expected_spread = Decimal(spread_ticks) * tick
        assert spread == expected_spread
        assert expected_spread <= max_spread

        observed_at = datetime.fromisoformat(row["timestamp"])
        expiry_at = datetime.strptime(row["expiry"], "%Y%m%d").replace(
            hour=15, minute=20, second=0, microsecond=0, tzinfo=observed_at.tzinfo,
        )
        years = (expiry_at - observed_at).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        theoretical_mid = _market_bs_price(
            float(calibration["candidate_underlying_price"]),
            float(row["strike"]),
            years,
            float(calibration["implied_volatility"]),
            row["option_type"],
        )
        expected_mid = (
            Decimal(str(theoretical_mid)) / tick
        ).to_integral_value(rounding=ROUND_HALF_UP) * tick
        assert last == expected_mid
        bid_ticks = spread_ticks // 2
        ask_ticks = spread_ticks - bid_ticks
        assert bid == expected_mid - Decimal(bid_ticks) * tick
        assert ask == expected_mid + Decimal(ask_ticks) * tick
        validate_quote_snapshot(
            row,
            observed_at=observed_at,
            max_age_seconds=Decimal(manifest["u21"]["max_age_seconds"]),
            max_spread=max_spread,
        )


def test_t17_all_84_quote_volume_and_depth_proxy_match_prior_spread_anchor_medians():
    import json
    from statistics import median

    provider = _provider("2026-10-12T09:26:00+09:00")
    _manifest, _candidate, _profile, _quotes, _hashes = provider._load_verified_sources()
    scenario_rows = [
        json.loads(line)
        for line in (provider.scenario_dir / "four_leg_quotes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted_by_id = {}
    for day in ("20261012", "20261013"):
        source_path = provider.accepted_manifest_path.parent / f"{day}.jsonl"
        for line in source_path.read_text(encoding="utf-8").splitlines():
            source_row = json.loads(line)
            source_id = (source_row.get("scenario_metadata") or {}).get("source_observation_id")
            if source_id:
                accepted_by_id[source_id] = source_row

    assert len(scenario_rows) == 84
    for row in scenario_rows:
        calibration = row["market_calibration"]
        source_rows = [
            accepted_by_id[source_id]
            for source_id in calibration["spread_anchor_observation_ids"]
        ]
        source_volumes = [max(1, int(source["tick"].get("volume") or 1)) for source in source_rows]
        source_bid_depth = [
            max(1, int(((source.get("scenario_metadata", {}).get("field_provenance") or {})
                        .get("order_book_quantities") or {}).get("bid_quantity") or 1))
            for source in source_rows
        ]
        source_ask_depth = [
            max(1, int(((source.get("scenario_metadata", {}).get("field_provenance") or {})
                        .get("order_book_quantities") or {}).get("ask_quantity") or 1))
            for source in source_rows
        ]
        assert row["volume"] == max(1, int(round(median(source_volumes))))
        assert row["bid_quantity"] == max(1, int(round(median(source_bid_depth))))
        assert row["ask_quantity"] == max(1, int(round(median(source_ask_depth))))
        assert calibration["volume_basis"] == "MEDIAN_PRIOR_ANCHOR_TRADE_SIZE"
        assert calibration["depth_basis"] == "MEDIAN_ACCEPTED_SYNTHETIC_L1_DEPTH_PROXY"
