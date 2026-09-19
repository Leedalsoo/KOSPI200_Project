from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from infrastructure.kis.kis_weekday_collection_plan import (
    CollectionWindow,
    build_collection_plan,
    is_collection_day,
    should_stop,
)


def test_strategy_contract_plan_covers_all_required_offsets_and_futures() -> None:
    plan = build_collection_plan(
        reference_price=Decimal("1090.23"),
        option_master_paths=(
            "data_2801_20260919.xlsx",
        ),
        weekly_master_paths=(
            "data_2923_20260919.xlsx",
            "data_2935_20260919.xlsx",
        ),
        standard_futures_symbol="A01609",
        mini_futures_symbol="A05609",
        as_of=date(2026, 9, 21),
    )

    option_symbols = {s for tr_id, s in plan.subscriptions if tr_id == "H0IOCNT0"}
    assert len(option_symbols) == 30
    assert {"B016AA29", "C016AA29"} <= option_symbols
    assert plan.monthly_strikes == (
        Decimal("1075.0"),
        Decimal("1077.5"),
        Decimal("1080.0"),
        Decimal("1082.5"),
        Decimal("1085.0"),
        Decimal("1087.5"),
        Decimal("1090.0"),
        Decimal("1092.5"),
        Decimal("1095.0"),
        Decimal("1097.5"),
        Decimal("1100.0"),
        Decimal("1102.5"),
        Decimal("1105.0"),
    )
    assert any(s.startswith(("B016", "C016")) for s in option_symbols)
    assert plan.standard_futures_symbol == "A01609"
    assert plan.mini_futures_symbol == "A05609"
    assert len(plan.subscriptions) <= 41


def test_collection_window_only_allows_monday_to_wednesday() -> None:
    window = CollectionWindow(
        start=date(2026, 9, 21),
        end=date(2026, 9, 23),
    )
    assert is_collection_day(date(2026, 9, 21), window)
    assert is_collection_day(date(2026, 9, 22), window)
    assert is_collection_day(date(2026, 9, 23), window)
    assert not is_collection_day(date(2026, 9, 24), window)
    assert not is_collection_day(date(2026, 9, 20), window)


def test_should_stop_at_end_of_wednesday() -> None:
    window = CollectionWindow(
        start=date(2026, 9, 21),
        end=date(2026, 9, 23),
    )
    assert not should_stop("2026-09-23T14:59:59+09:00", window)
    assert should_stop("2026-09-24T00:00:00+09:00", window)
    assert should_stop("2026-09-23T23:59:59+09:00", window)


def test_plan_does_not_include_unresolved_contracts(tmp_path: Path) -> None:
    plan = build_collection_plan(
        reference_price=Decimal("1090.23"),
        option_master_paths=(
            "data_2801_20260919.xlsx",
        ),
        weekly_master_paths=(
            "data_2923_20260919.xlsx",
            "data_2935_20260919.xlsx",
        ),
        standard_futures_symbol="A01609",
        mini_futures_symbol="A05609",
        as_of=date(2026, 9, 21),
    )
    assert all(symbol for _, symbol in plan.subscriptions)
