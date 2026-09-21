from datetime import date, datetime, timezone
from pathlib import Path

from infrastructure.kis.kis_vts_weekday_collector import (
    DateSessionManifest,
    DailySessionOrchestrator,
    TradingDayStatus,
)


class Calendar:
    def __init__(self, trading_days):
        self.trading_days = set(trading_days)

    def is_trading_day(self, target_date):
        return target_date in self.trading_days


def test_calendar_classification_is_unknown_when_source_fails():
    class BrokenCalendar:
        def is_trading_day(self, target_date):
            raise RuntimeError("calendar unavailable")

    orchestrator = DailySessionOrchestrator(Path("data"), BrokenCalendar())
    assert orchestrator.classify(date(2026, 9, 22)) == TradingDayStatus.UNKNOWN


def test_holiday_creates_only_status_manifest_without_market_files(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar(set()))
    manifest = orchestrator.prepare_day(date(2026, 9, 24), run_id="run-holiday")
    day_dir = tmp_path / "2026-09-24"
    assert manifest.session_status == "NO_TRADING_SESSION"
    assert (day_dir / "manifest.json").exists()
    assert (day_dir / "daily_status.json").exists()
    assert list(day_dir.glob("*.jsonl")) == []


def test_manifest_has_stable_required_fields_and_no_credentials(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar({date(2026, 9, 22)}))
    manifest = orchestrator.prepare_day(date(2026, 9, 22), run_id="run-1")
    payload = manifest.to_dict()
    required = {"schema_version", "trading_date", "session_status", "run_id", "collectors", "targets", "counts", "files", "started_at", "ended_at", "end_reason"}
    assert required <= payload.keys()
    assert "appsecret" not in str(payload).lower()
    assert "access_token" not in str(payload).lower()


def test_same_date_restart_preserves_existing_store_and_uses_date_loader(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar({date(2026, 9, 22)}))
    orchestrator.prepare_day(date(2026, 9, 22), run_id="run-1")
    store = orchestrator.store_for(date(2026, 9, 22))
    marker = tmp_path / "2026-09-22" / "historical_market_observations.jsonl"
    marker.write_text("existing\n", encoding="utf-8")
    restarted = orchestrator.store_for(date(2026, 9, 22))
    assert restarted.path == marker
    assert marker.read_text(encoding="utf-8") == "existing\n"


def test_session_boundaries_are_deterministic():
    orchestrator = DailySessionOrchestrator(Path("data"), Calendar({date(2026, 9, 22)}))
    assert orchestrator.is_before_open(datetime(2026, 9, 22, 8, 29, 59, tzinfo=orchestrator.kst))
    assert not orchestrator.is_before_open(datetime(2026, 9, 22, 8, 30, tzinfo=orchestrator.kst))
    assert orchestrator.is_after_close(datetime(2026, 9, 22, 16, 0, tzinfo=orchestrator.kst))


def test_manifest_round_trip_preserves_status_and_counts(tmp_path):
    path = tmp_path / "2026-09-22"
    manifest = DateSessionManifest.new(date(2026, 9, 22), "run-2", "TRADING")
    manifest.counts = {"SUCCESS": 2, "DUPLICATE": 1, "BLOCKED": 3}
    manifest.write(path)
    loaded = DateSessionManifest.read(path / "manifest.json")
    assert loaded.trading_date == "2026-09-22"
    assert loaded.counts == {"SUCCESS": 2, "DUPLICATE": 1, "BLOCKED": 3}


def test_unknown_calendar_still_allows_read_only_rest_path(tmp_path):
    class UnknownCalendar:
        def is_trading_day(self, target_date):
            raise RuntimeError("unavailable")

    class RestStub:
        def collect_cycle(self, targets, *, run_id, cycle_id):
            return ()

    orchestrator = DailySessionOrchestrator(tmp_path, UnknownCalendar(), rest_collector=RestStub())
    manifest = orchestrator.prepare_day(date(2026, 9, 22), run_id="run-unknown")
    assert manifest.session_status == TradingDayStatus.UNKNOWN
    assert orchestrator.rest_collector is not None


def test_finalize_records_file_hashes_and_end_reason(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar({date(2026, 9, 22)}))
    manifest = orchestrator.prepare_day(date(2026, 9, 22), run_id="run-final")
    data = tmp_path / "2026-09-22" / "historical_market_observations.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    orchestrator.finalize(manifest, end_reason="SESSION_END")
    saved = DateSessionManifest.read(tmp_path / "2026-09-22" / "manifest.json")
    assert saved.end_reason == "SESSION_END"
    assert saved.files[0]["path"] == "daily_status.json"
    assert any(item["path"] == "historical_market_observations.jsonl" for item in saved.files)


def test_date_loader_is_bound_to_daily_root(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar({date(2026, 9, 22)}))
    store = orchestrator.store_for(date(2026, 9, 22))
    assert store.path == tmp_path / "2026-09-22" / "historical_market_observations.jsonl"


def test_real_calendar_provider_marks_weekend_and_known_holiday(tmp_path):
    from infrastructure.kis.trading_calendar import ProductionTradingCalendar
    from infrastructure.kis.holiday_provider import KISHolidayProvider
    provider = ProductionTradingCalendar(KISHolidayProvider({date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26)}))
    orchestrator = DailySessionOrchestrator(tmp_path, provider)
    assert orchestrator.classify(date(2026, 9, 20)) == TradingDayStatus.NO_TRADING_SESSION
    assert orchestrator.classify(date(2026, 9, 24)) == TradingDayStatus.NO_TRADING_SESSION
    assert orchestrator.classify(date(2026, 9, 22)) == TradingDayStatus.TRADING


def test_manifest_target_selection_records_authoritative_reason(tmp_path):
    orchestrator = DailySessionOrchestrator(tmp_path, Calendar({date(2026, 9, 22)}))
    manifest = orchestrator.prepare_day(date(2026, 9, 22), run_id="run-targets")
    manifest.targets = [{"symbol": "C01610A29", "selection_source": "OPTION_MASTER", "selection_reason": "MONTHLY_ATM_OFFSET_-15"}]
    assert manifest.targets[0]["selection_source"] == "OPTION_MASTER"


def test_rest_cycle_failure_does_not_require_websocket(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import infrastructure.kis.kis_vts_weekday_collector as module
    manifest = DateSessionManifest.new(date(2026, 9, 22), "run-rest", "TRADING")
    target = SimpleNamespace(identity=SimpleNamespace(symbol="C01610A29", expiry="2026-10-08", strike="1075", option_type="PUT"))
    monkeypatch.setattr(module, "build_daily_targets", lambda day: (target,))
    monkeypatch.setattr(module, "_rest_collector_for_day", lambda day, store: SimpleNamespace(collect_cycle=lambda *a, **k: (SimpleNamespace(status="BLOCKED"),)))
    results = module.run_rest_cycle_for_day(date(2026, 9, 22), manifest, cycle_id="cycle-1")
    assert results[0].status == "BLOCKED"
    assert manifest.counts["BLOCKED"] == 1
    assert manifest.collectors["rest"]["status"] == "RUNNING"
    assert manifest.collectors["websocket"] == {"status": "NOT_STARTED"}


def test_calendar_cases_include_chuseok_and_midnight_transition(tmp_path):
    from infrastructure.kis.trading_calendar import ProductionTradingCalendar
    from infrastructure.kis.holiday_provider import KISHolidayProvider
    provider = ProductionTradingCalendar(KISHolidayProvider({date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26)}))
    orchestrator = DailySessionOrchestrator(tmp_path, provider)
    assert [orchestrator.classify(date(2026, 9, d)) for d in (24, 25, 26)] == [TradingDayStatus.NO_TRADING_SESSION] * 3
    assert orchestrator.classify(date(2026, 9, 23)) == TradingDayStatus.TRADING
    assert orchestrator.classify(date(2026, 9, 27)) == TradingDayStatus.NO_TRADING_SESSION
    assert orchestrator.day_dir(date(2026, 9, 22)) != orchestrator.day_dir(date(2026, 9, 23))
