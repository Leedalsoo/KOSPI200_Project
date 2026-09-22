from decimal import Decimal
from types import SimpleNamespace

from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.authoritative_vssf.canonical import VSSFOrderResult


def test_option_market_pnl_uses_contract_last_price_not_underlying():
    vssf = VirtualSecuritiesFirmRuntime(initial_capital=250_000_000.0)
    command = SimpleNamespace(
        client_order_id="PNL-1", qty=1, side="BUY", track_id="TRACK1",
        asset_type="OPTION", symbol="C01610A43",
    )
    # Seed the authoritative option position as if the preceding VSSF fill occurred.
    vssf.account.position_mgr.positions["C01610A43"] = {
        "qty": 1, "avg_price": 33.6, "side": "BUY"
    }
    tick = SimpleNamespace(
        timestamp="2026-09-22T07:00:00", bid_price=25.9, ask_price=26.1,
        last_price=26.0, underlying_price=1114.5, instrument_id="C01610A43"
    )

    vssf.process_market_data(tick)

    assert vssf.account.unrealized_pnl == Decimal("-1900000.0")
