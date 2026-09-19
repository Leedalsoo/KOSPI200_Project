from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.risk.position_pnl_exposure import ExposureLine, project_position_pnl_exposure


def test_projection_separates_option_and_futures_exposure():
    snap = project_position_pnl_exposure([
        ExposureLine("OPT", "OPTION", "BUY", 1, Decimal("10"), Decimal("12"), Decimal("250000")),
        ExposureLine("FUT", "FUTURES", "SELL", 1, Decimal("100"), Decimal("99"), Decimal("50000")),
    ], as_of=datetime.now(timezone.utc), realized_pnl=Decimal("100"))
    assert snap.gross_exposure == Decimal("7950000")
    assert snap.option_exposure == Decimal("3000000")
    assert snap.futures_exposure == Decimal("-4950000")
    assert snap.unrealized_pnl == Decimal("550000")
    assert snap.daily_pnl == Decimal("550100")


def test_projection_rejects_unknown_asset_type():
    line = ExposureLine("X", "UNKNOWN", "BUY", 1, Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError, match="EXPOSURE_LINE_ASSET_TYPE_UNSUPPORTED"):
        project_position_pnl_exposure([line], as_of=datetime.now(timezone.utc))
