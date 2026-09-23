from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_MASTER_FILE_RE = re.compile(r"^data_(2801|2923|2935)_(\d{8})\.xlsx$")
_FAMILIES = {"monthly": "2801", "weekly_thursday": "2923", "weekly_monday": "2935"}


class KRXOptionMasterRefreshRequired(RuntimeError):
    """The local KRX authoritative master cannot cover the requested date."""


def _candidates(data_root: Path, family_code: str, target_day: date) -> list[tuple[date, Path]]:
    rows: list[tuple[date, Path]] = []
    for path in data_root.glob(f"data_{family_code}_*.xlsx"):
        match = _MASTER_FILE_RE.match(path.name)
        if not match or match.group(1) != family_code:
            continue
        raw = match.group(2)
        snapshot = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        if snapshot <= target_day:
            rows.append((snapshot, path))
    return sorted(rows, key=lambda item: (item[0], item[1].name))


def _latest_family(data_root: Path, family_code: str, target_day: date) -> tuple[date, Path]:
    rows = _candidates(data_root, family_code, target_day)
    if not rows:
        raise KRXOptionMasterRefreshRequired(
            f"KRX_OPTION_MASTER_REFRESH_REQUIRED:{family_code}:{target_day.isoformat()}:NO_SNAPSHOT"
        )
    return rows[-1]


def resolve_option_master_paths_for_day(
    data_root: str | Path,
    target_day: date,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Select the newest KRX master snapshot available on/before target_day.

    KRX remains the authoritative contract source. This function never substitutes
    a broker master and never selects a future-dated snapshot.
    """
    root = Path(data_root)
    _, monthly = _latest_family(root, _FAMILIES["monthly"], target_day)
    _, thursday = _latest_family(root, _FAMILIES["weekly_thursday"], target_day)
    _, monday = _latest_family(root, _FAMILIES["weekly_monday"], target_day)
    return (monthly,), (thursday, monday)


def discover_master_snapshot_dates(data_root: str | Path, target_day: date) -> dict[str, date]:
    root = Path(data_root)
    return {
        family: _latest_family(root, code, target_day)[0]
        for family, code in _FAMILIES.items()
    }
