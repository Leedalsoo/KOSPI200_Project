import hashlib
import json
from datetime import date

import pytest

from environments.high_speed.validation_only_trading_calendar import (
    ValidationOnlyTradingCalendar,
    load_validation_only_trading_calendar,
)


def _calendar():
    return ValidationOnlyTradingCalendar(
        scenario_id="Q25_TEST_SCENARIO",
        calendar_id="Q25_TEST_CALENDAR_V1",
        trading_days=(
            date(2026, 11, 2),
            date(2026, 11, 3),
            date(2026, 11, 4),
            date(2026, 11, 5),
            date(2026, 11, 6),
            date(2026, 11, 9),
        ),
    )


def test_calendar_uses_only_explicit_schedule_and_skips_weekend():
    calendar = _calendar()

    assert calendar.is_trading_day(date(2026, 11, 6))
    assert not calendar.is_trading_day(date(2026, 11, 7))
    assert calendar.next_trading_day(date(2026, 11, 6)) == date(2026, 11, 9)
    assert calendar.prev_trading_day(date(2026, 11, 9)) == date(2026, 11, 6)


def test_calendar_counts_explicit_three_trading_day_retry_window():
    calendar = _calendar()

    assert calendar.trading_days_between(
        date(2026, 11, 2), date(2026, 11, 4)
    ) == (date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4))
    assert calendar.advance_trading_days(date(2026, 11, 2), 2) == date(2026, 11, 4)


def test_calendar_rejects_weekend_and_unprovenanced_schedule():
    with pytest.raises(ValueError, match="WEEKEND_DATE"):
        ValidationOnlyTradingCalendar(
            scenario_id="bad",
            calendar_id="bad",
            trading_days=(date(2026, 11, 7),),
        )
    with pytest.raises(ValueError, match="SYNTHETIC_ONLY"):
        ValidationOnlyTradingCalendar(
            scenario_id="bad",
            calendar_id="bad",
            trading_days=(date(2026, 11, 6),),
            source_type="KIS",
        )


def test_manifest_loader_requires_synthetic_provenance_and_dataset_hash(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"source":"SYNTHETIC"}\n', encoding="utf-8")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "scenario_id": "Q25_TEST_SCENARIO",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "expiry_is_authoritative": False,
        "dataset_sha256": digest,
        "trading_calendar": {
            "calendar_id": "Q25_TEST_CALENDAR_V1",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": ["2026-11-02", "2026-11-03", "2026-11-04"],
        },
    }), encoding="utf-8")

    calendar = load_validation_only_trading_calendar(manifest, dataset)

    assert calendar is not None
    assert calendar.trading_days == (
        date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
    )


def test_manifest_loader_rejects_dataset_hash_mismatch(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"source":"SYNTHETIC"}\n', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "scenario_id": "Q25_TEST_SCENARIO",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "expiry_is_authoritative": False,
        "dataset_sha256": "0" * 64,
        "trading_calendar": {
            "calendar_id": "Q25_TEST_CALENDAR_V1",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": ["2026-11-02"],
        },
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="DATASET_HASH_MISMATCH"):
        load_validation_only_trading_calendar(manifest, dataset)


def test_generated_s7_s8_v2_datasets_match_explicit_calendar_and_kst_sessions():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for strategy in ("strategy7_weekly", "strategy8_monthly"):
        folder = root / "data" / "derived_scenario" / "q25_strategy7_8_v2" / strategy
        manifest = folder / "manifest.json"
        dataset = folder / "20261103.jsonl"
        calendar = load_validation_only_trading_calendar(manifest, dataset)
        assert calendar is not None

        records = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
        assert len(records) == (216 if strategy == "strategy7_weekly" else 432)
        assert len({record["tick"]["timestamp"] for record in records}) == 54
        for record in records:
            observed = __import__("datetime").datetime.fromisoformat(record["tick"]["timestamp"])
            assert observed.utcoffset().total_seconds() == 9 * 60 * 60
            assert observed.date() in calendar.trading_days
            assert observed.time().isoformat() in {
                "08:45:00", "09:00:00", "09:10:00", "10:00:00", "13:00:00", "15:10:00"
            }


def test_generated_s7_s8_v2_manifests_are_accepted_by_synthetic_replay_adapter():
    from pathlib import Path
    from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter

    root = Path(__file__).resolve().parents[3]
    for strategy in ("strategy7_weekly", "strategy8_monthly"):
        folder = root / "data" / "derived_scenario" / "q25_strategy7_8_v2" / strategy
        adapter = SyntheticReplayAdapter(folder, manifest_path=folder / "manifest.json")
        first_record = json.loads((folder / "20261103.jsonl").read_text(encoding="utf-8").splitlines()[0])
        adapted = adapter.adapt_record(first_record)
        assert adapted["tick"]["instrument_id"].startswith("SYNTHETIC_CONTRACT:")
        assert adapted["tick"]["synthetic_contract_id"] == adapted["tick"]["instrument_id"]
        from environments.high_speed.synthetic_runtime_sources import build_synthetic_option_master
        master = build_synthetic_option_master(folder, validation_only_adapter=adapter)
        identity = master.get_contract_identity(adapted["tick"]["instrument_id"])
        assert identity is not None
        assert identity.instrument_family == "STANDARD"
        assert identity.product_series in {"MONDAY_WEEKLY", "THURSDAY_WEEKLY", "MONTHLY"}


def test_generated_s7_s8_v2_contract_masters_resolve_strategy_pairs():
    from pathlib import Path
    from decimal import Decimal
    from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
    from environments.high_speed.synthetic_runtime_sources import build_synthetic_option_master
    from application.composition.track7_option_contract_source import Track7OptionContractSource
    from application.composition.track8_option_contract_source import Track8OptionContractSource

    root = Path(__file__).resolve().parents[3]
    s7_folder = root / "data" / "derived_scenario" / "q25_strategy7_8_v2" / "strategy7_weekly"
    s7_adapter = SyntheticReplayAdapter(s7_folder, manifest_path=s7_folder / "manifest.json")
    s7_master = build_synthetic_option_master(s7_folder, validation_only_adapter=s7_adapter)
    s7_selection = Track7OptionContractSource(s7_master).select(
        expiry="20261109", reference_price=Decimal("500")
    )
    assert s7_selection.put_strike == Decimal("487.5")
    assert s7_selection.call_strike == Decimal("512.5")

    s8_folder = root / "data" / "derived_scenario" / "q25_strategy7_8_v2" / "strategy8_monthly"
    s8_adapter = SyntheticReplayAdapter(s8_folder, manifest_path=s8_folder / "manifest.json")
    s8_master = build_synthetic_option_master(s8_folder, validation_only_adapter=s8_adapter)
    s8_selection = Track8OptionContractSource(s8_master).select(
        expiry="20261119", current_price=Decimal("500")
    )
    assert s8_selection.put.strike == Decimal("485")
    assert s8_selection.call.strike == Decimal("515")


def test_validation_calendar_composes_market_calendar_hub_without_production_label():
    from datetime import date
    from application.composition.market_calendar_hub import MarketCalendarHub

    calendar = ValidationOnlyTradingCalendar(
        scenario_id="Q25_HUB_TEST",
        calendar_id="Q25_HUB_CALENDAR",
        trading_days=(
            date(2026, 10, 30),
            date(2026, 11, 2),
            date(2026, 11, 3),
        ),
    )
    snapshot = MarketCalendarHub(calendar).snapshot(
        date(2026, 11, 2), expiry=date(2026, 11, 2)
    )

    assert snapshot.available
    assert snapshot.is_trading_day is True
    assert snapshot.is_new_week_start is True
    assert snapshot.is_expiry_day is True
    assert snapshot.source == "SYNTHETIC:Q25_HUB_CALENDAR"
    assert snapshot.source_status == "SYNTHETIC_VALIDATION_ONLY"


def test_s8_retry_window_includes_submission_day_and_blocks_at_third_day_1500_kst():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    calendar = _calendar()
    kst = ZoneInfo("Asia/Seoul")
    submitted = datetime(2026, 11, 2, 10, 0, tzinfo=kst)

    assert calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 2, 10, 1, tzinfo=kst)
    )  # day 1
    assert calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 3, 15, 0, tzinfo=kst)
    )  # day 2
    assert calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 4, 14, 59, 59, tzinfo=kst)
    )  # day 3, immediately before cutoff
    assert not calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 4, 15, 0, 0, tzinfo=kst)
    )  # exact cutoff
    assert not calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 4, 15, 0, 1, tzinfo=kst)
    )
    assert not calendar.is_retry_window_open(
        submitted, datetime(2026, 11, 9, 9, 0, tzinfo=kst)
    )  # later trading day


def test_s8_retry_window_rejects_ambiguous_or_invalid_time_inputs():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    calendar = _calendar()
    kst = ZoneInfo("Asia/Seoul")
    submitted = datetime(2026, 11, 2, 10, 0, tzinfo=kst)

    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        calendar.is_retry_window_open(
            datetime(2026, 11, 2, 10, 0),
            datetime(2026, 11, 2, 10, 1, tzinfo=kst),
        )
    with pytest.raises(ValueError, match="OBSERVED_BEFORE_SUBMISSION"):
        calendar.is_retry_window_open(
            submitted, datetime(2026, 11, 2, 9, 59, tzinfo=kst)
        )
    with pytest.raises(ValueError, match="NOT_TRADING_DAY"):
        calendar.is_retry_window_open(
            datetime(2026, 11, 7, 10, 0, tzinfo=kst),
            datetime(2026, 11, 9, 9, 0, tzinfo=kst),
        )


def test_s8_retry_window_requires_explicit_third_trading_day():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    calendar = ValidationOnlyTradingCalendar(
        scenario_id="Q25_SHORT_WINDOW",
        calendar_id="Q25_SHORT_CALENDAR",
        trading_days=(date(2026, 11, 2), date(2026, 11, 3)),
    )
    kst = ZoneInfo("Asia/Seoul")
    with pytest.raises(ValueError, match="CUTOFF_DATE_UNAVAILABLE"):
        calendar.is_retry_window_open(
            datetime(2026, 11, 2, 10, 0, tzinfo=kst),
            datetime(2026, 11, 3, 10, 0, tzinfo=kst),
        )
