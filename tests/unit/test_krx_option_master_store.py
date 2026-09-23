from datetime import date
from pathlib import Path

import pytest

from infrastructure.krx.krx_option_master_store import (
    KRXOptionMasterRefreshRequired,
    resolve_option_master_paths_for_day,
)


def test_selects_latest_master_snapshot_not_after_target_day(tmp_path: Path) -> None:
    for name in (
        "data_2801_20260919.xlsx", "data_2923_20260919.xlsx", "data_2935_20260919.xlsx",
        "data_2801_20260922.xlsx", "data_2923_20260922.xlsx", "data_2935_20260922.xlsx",
    ):
        (tmp_path / name).touch()
    monthly, weekly = resolve_option_master_paths_for_day(tmp_path, date(2026, 9, 23))
    assert [p.name for p in monthly] == ["data_2801_20260922.xlsx"]
    assert [p.name for p in weekly] == ["data_2923_20260922.xlsx", "data_2935_20260922.xlsx"]


def test_missing_family_is_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "data_2801_20260922.xlsx").touch()
    with pytest.raises(KRXOptionMasterRefreshRequired):
        resolve_option_master_paths_for_day(tmp_path, date(2026, 9, 23))
