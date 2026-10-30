from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources


SCHEMA = "reference-canonical-market-tick-v1"
IDENTITY_STATUS = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
SYNTHETIC_ID = "SYNTHETIC_CONTRACT:0123456789abcdef01234567"


def _make_dataset(root: Path, *, rows: int = 101) -> Path:
    root.mkdir(parents=True)
    manifest = {
        "schema": SCHEMA,
        "synthetic": True,
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": IDENTITY_STATUS,
        "identity_policy": {
            "mode": "SYNTHETIC_ONLY",
            "synthetic_contract_id_namespace": "SYNTHETIC_CONTRACT:",
            "production_standard_instrument_id_assigned": False,
        },
        "generator_version": "test-fixture-v1",
        "seed": 7,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    data_path = root / "20261008.jsonl"
    start = datetime.fromisoformat("2026-10-08T08:45:00+09:00")
    with data_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(rows):
            tick = {
                "timestamp": (start + timedelta(seconds=index)).isoformat(),
                "underlying_price": 500.0,
                "strike_price": 500.0,
                "option_type": "CALL",
                "contract_multiplier": 250000.0,
                "bid_price": 10.0,
                "ask_price": 10.2,
                "last_price": 10.1,
                "volume": 1,
                "seq_id": index + 1,
                "expiry": "20261008",
                "symbol": "KOSPI200",
                "synthetic_contract_id": SYNTHETIC_ID,
                "source_instrument_code": "B016AA12",
                "instrument_identity_status": IDENTITY_STATUS,
                "contract_class": "monthly",
                "contract_month": "202610",
            }
            record = {
                "schema": SCHEMA,
                "synthetic": True,
                "provenance": "DERIVED_SCENARIO",
                "tick": tick,
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return root


class OffsetFakeClock:
    def __init__(self, *, wall_origin: datetime, monotonic_origin: float) -> None:
        self._wall_origin = wall_origin
        self._monotonic_origin = monotonic_origin
        self._elapsed = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._wall_origin + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        return self._monotonic_origin + self._elapsed

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self.sleeps.append(seconds)
        self._elapsed += seconds


def _semantic_replay(clock: OffsetFakeClock, dataset: Path) -> tuple[tuple[str, str, str], ...]:
    trace: list[tuple[str, str, str]] = []
    runner = HighSpeedReplayRunner(
        dataset,
        synthetic_adapter=SyntheticReplayAdapter(dataset),
        clock=clock,
    )
    report = runner.run(
        speed=float("inf"),
        max_events=100,
        on_event=lambda tick: trace.append(
            (str(tick.seq_id), str(tick.timestamp), str(tick.instrument_id))
        ),
    )
    assert report.events == 100
    assert report.first_timestamp == trace[0][1]
    assert report.last_timestamp == trace[-1][1]
    assert report.elapsed_seconds >= 0
    assert report.events_per_second >= 0
    assert clock.sleeps == []
    return tuple(trace)


def test_semantic_replay_trace_independent_of_wall_and_monotonic_origins(tmp_path: Path):
    dataset = _make_dataset(tmp_path / "dataset")
    clock_a = OffsetFakeClock(wall_origin=datetime(2001, 1, 1), monotonic_origin=1.0)
    clock_b = OffsetFakeClock(
        wall_origin=datetime(2099, 12, 31, 23, 59, 59), monotonic_origin=9_000_000.0
    )
    assert _semantic_replay(clock_a, dataset) == _semantic_replay(clock_b, dataset)


def test_synthetic_source_tickless_fallback_uses_injected_clock():
    clock = OffsetFakeClock(
        wall_origin=datetime(2037, 5, 6, 7, 8, 9),
        monotonic_origin=1234.0,
    )
    source = SyntheticRuntimeSources(clock=clock)
    snapshot = source.snapshot()
    assert snapshot.observed_at == clock.now()


def test_virtual_runtime_semantic_report_independent_of_clock_origins(tmp_path: Path):
    from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

    dataset = _make_dataset(tmp_path / "dataset", rows=101)
    clock_a = OffsetFakeClock(wall_origin=datetime(2001, 1, 1), monotonic_origin=1.0)
    clock_b = OffsetFakeClock(
        wall_origin=datetime(2099, 12, 31, 23, 59, 59), monotonic_origin=9_000_000.0
    )

    def run(clock: OffsetFakeClock):
        runner = HighSpeedVirtualRuntimeReplayRunner(
            dataset,
            run_id="R4-CLOCK-INDEPENDENCE-FIXED",
            validation_only_synthetic=True,
            clock=clock,
        )
        return runner.run(speed=float("inf"), max_events=100)

    report_a = run(clock_a)
    report_b = run(clock_b)
    semantic_fields = (
        "dataset", "run_id", "events", "signals", "approved", "routed", "filled",
        "rejected", "execution_ids", "exhausted", "pnl_status", "multi_leg_decisions",
        "strategy_signal_counts", "strategy_status", "realized_pnl", "unrealized_pnl", "net_pnl",
    )
    assert tuple(getattr(report_a, field) for field in semantic_fields) == tuple(
        getattr(report_b, field) for field in semantic_fields
    )
    assert report_a.events == 100
    assert report_a.exhausted is False
