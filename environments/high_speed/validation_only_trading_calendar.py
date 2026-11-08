from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ValidationOnlyCalendarResolution:
    status: str
    source: str


@dataclass(frozen=True)
class ValidationOnlyTradingCalendar:
    """Explicit synthetic trading-day schedule; never an exchange calendar."""

    scenario_id: str
    calendar_id: str
    trading_days: tuple[date, ...]
    source_type: str = "SYNTHETIC"
    timezone: str = "Asia/Seoul"
    authoritative: bool = False
    strategy7_entry_dates: tuple[date, ...] = ()
    strategy7_entry_date_by_expiry: tuple[tuple[str, date], ...] = ()

    def __post_init__(self) -> None:
        days = tuple(self.trading_days)
        if self.source_type != "SYNTHETIC" or self.authoritative:
            raise ValueError("VALIDATION_CALENDAR_SYNTHETIC_ONLY_REQUIRED")
        if not self.scenario_id or not self.calendar_id or not days:
            raise ValueError("VALIDATION_CALENDAR_PROVENANCE_REQUIRED")
        if days != tuple(sorted(set(days))):
            raise ValueError("VALIDATION_CALENDAR_DATES_MUST_BE_SORTED_UNIQUE")
        if self.timezone != "Asia/Seoul":
            raise ValueError("VALIDATION_CALENDAR_TIMEZONE_MUST_BE_ASIA_SEOUL")
        if any(day.weekday() >= 5 for day in days):
            raise ValueError("VALIDATION_CALENDAR_WEEKEND_DATE_NOT_ALLOWED")
        entry_dates = tuple(self.strategy7_entry_dates)
        if any(day not in days for day in entry_dates) or len(set(entry_dates)) != len(entry_dates):
            raise ValueError("VALIDATION_CALENDAR_STRATEGY7_ENTRY_DATES_INVALID")
        expiry_entries = tuple((str(expiry), value) for expiry, value in self.strategy7_entry_date_by_expiry)
        if (any(len(expiry) != 8 or not expiry.isdigit() or value not in days for expiry, value in expiry_entries)
                or len({expiry for expiry, _ in expiry_entries}) != len(expiry_entries)):
            raise ValueError("VALIDATION_CALENDAR_STRATEGY7_EXPIRY_ENTRY_MAP_INVALID")
        object.__setattr__(self, "trading_days", days)
        object.__setattr__(self, "strategy7_entry_dates", entry_dates)
        object.__setattr__(self, "strategy7_entry_date_by_expiry", expiry_entries)

    def is_trading_day(self, value: date) -> bool:
        return value in self.trading_days

    def holiday_resolution(self, year: int) -> ValidationOnlyCalendarResolution:
        if not any(day.year == year for day in self.trading_days):
            raise ValueError("VALIDATION_CALENDAR_YEAR_UNAVAILABLE")
        return ValidationOnlyCalendarResolution(
            status="SYNTHETIC_VALIDATION_ONLY",
            source=f"SYNTHETIC:{self.calendar_id}",
        )

    def prev_trading_day(self, value: date) -> date:
        candidates = [day for day in self.trading_days if day < value]
        if not candidates:
            raise ValueError("VALIDATION_CALENDAR_PREVIOUS_DAY_UNAVAILABLE")
        return candidates[-1]

    def next_trading_day(self, value: date) -> date:
        candidates = [day for day in self.trading_days if day > value]
        if not candidates:
            raise ValueError("VALIDATION_CALENDAR_NEXT_DAY_UNAVAILABLE")
        return candidates[0]

    def trading_days_between(self, start: date, end: date) -> tuple[date, ...]:
        if end < start:
            raise ValueError("VALIDATION_CALENDAR_RANGE_INVALID")
        return tuple(day for day in self.trading_days if start <= day <= end)

    def advance_trading_days(self, start: date, count: int) -> date:
        if count < 0 or start not in self.trading_days:
            raise ValueError("VALIDATION_CALENDAR_START_OR_COUNT_INVALID")
        index = self.trading_days.index(start) + count
        if index >= len(self.trading_days):
            raise ValueError("VALIDATION_CALENDAR_FORWARD_RANGE_UNAVAILABLE")
        return self.trading_days[index]

    def is_retry_window_open(
        self, submitted_at: datetime, observed_at: datetime
    ) -> bool:
        """Return whether the three-trading-day retry window is still open.

        The submission date is day one. Retries are blocked at and after
        15:00:00 KST on day three. This is validation-only policy evaluation;
        it does not schedule or perform retries.
        """
        kst = ZoneInfo("Asia/Seoul")
        if (
            submitted_at.tzinfo is None
            or submitted_at.utcoffset() is None
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise ValueError("VALIDATION_RETRY_TIMESTAMP_TIMEZONE_REQUIRED")
        submitted = submitted_at.astimezone(kst)
        observed = observed_at.astimezone(kst)
        if observed < submitted:
            raise ValueError("VALIDATION_RETRY_OBSERVED_BEFORE_SUBMISSION")
        if not self.is_trading_day(submitted.date()):
            raise ValueError("VALIDATION_RETRY_SUBMISSION_NOT_TRADING_DAY")
        index = self.trading_days.index(submitted.date())
        cutoff_index = index + 2
        if cutoff_index >= len(self.trading_days):
            raise ValueError("VALIDATION_RETRY_CUTOFF_DATE_UNAVAILABLE")
        cutoff = datetime.combine(
            self.trading_days[cutoff_index], time(15, 0, 0), tzinfo=kst
        )
        return observed < cutoff

    @property
    def validation_only_week_start_dates(self) -> tuple[date, ...] | None:
        return self.strategy7_entry_dates or None

    @property
    def validation_only_entry_date_by_expiry(self) -> dict[str, date] | None:
        return dict(self.strategy7_entry_date_by_expiry) or None

    def is_new_week_start(self, value: date) -> bool:
        if not self.is_trading_day(value):
            raise ValueError("VALIDATION_CALENDAR_DATE_NOT_TRADING_DAY")
        if self.strategy7_entry_dates:
            return value in self.strategy7_entry_dates
        try:
            previous = self.prev_trading_day(value)
        except ValueError:
            return True
        return previous.isocalendar().week != value.isocalendar().week


def load_validation_only_trading_calendar(
    manifest_path: str | Path,
    dataset_path: str | Path,
) -> ValidationOnlyTradingCalendar | None:
    manifest_file = Path(manifest_path)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    schedule = payload.get("trading_calendar")
    if schedule is None:
        return None
    dataset_file = Path(dataset_path)
    if dataset_file.is_dir():
        candidates = sorted(dataset_file.glob("*.jsonl"))
        if len(candidates) != 1:
            raise ValueError("VALIDATION_CALENDAR_DATASET_FILE_AMBIGUOUS")
        dataset_file = candidates[0]
    if payload.get("source_type") != "DERIVED_SCENARIO" or payload.get("provenance") != "DERIVED_SCENARIO" or payload.get("synthetic") is not True or payload.get("validation_only") is not True:
        raise ValueError("VALIDATION_CALENDAR_MANIFEST_PROVENANCE_INVALID")
    if payload.get("runtime_eligible") is not False or payload.get("production_runtime_eligible") is not False or payload.get("expiry_is_authoritative") is not False:
        raise ValueError("VALIDATION_CALENDAR_RUNTIME_PROMOTION_FORBIDDEN")
    expected_hash = str(payload.get("dataset_sha256") or "").lower()
    actual_hash = hashlib.sha256(dataset_file.read_bytes()).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("VALIDATION_CALENDAR_DATASET_HASH_MISMATCH")
    if schedule.get("source_type") != "SYNTHETIC" or schedule.get("authoritative") is not False:
        raise ValueError("VALIDATION_CALENDAR_AUTHORITY_INVALID")
    try:
        days = tuple(date.fromisoformat(item) for item in schedule["trading_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("VALIDATION_CALENDAR_SCHEDULE_INVALID") from exc
    policy = payload.get("strategy_policy_inputs") or {}
    group_entry_dates = {str(group): date.fromisoformat(str(value)) for group, value in (policy.get("strategy7_group_entry_dates") or {}).items()}
    strategy7_dates = tuple(group_entry_dates.values())
    group_expiries = payload.get("strategy7_group_expiry_by_id") or {}
    expiry_entry_dates = tuple((str(group_expiries[group]), entry_date) for group, entry_date in group_entry_dates.items() if group in group_expiries)
    return ValidationOnlyTradingCalendar(
        scenario_id=str(payload.get("scenario_id") or ""),
        calendar_id=str(schedule.get("calendar_id") or ""),
        trading_days=days,
        source_type=str(schedule.get("source_type") or ""),
        timezone=str(schedule.get("timezone") or ""),
        authoritative=bool(schedule.get("authoritative", True)),
        strategy7_entry_dates=strategy7_dates,
        strategy7_entry_date_by_expiry=expiry_entry_dates,
    )
