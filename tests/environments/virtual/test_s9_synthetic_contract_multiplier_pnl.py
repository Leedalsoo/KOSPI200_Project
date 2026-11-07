from decimal import Decimal

from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalExecutionReport, CanonicalOptionType, CanonicalOrderSide,
)


def report(*, exec_id: str, side: CanonicalOrderSide, price: float) -> CanonicalExecutionReport:
    return CanonicalExecutionReport(
        exec_id=exec_id, client_order_id=f"client-{exec_id}", track_id="S9",
        asset_type=CanonicalAssetType.OPTION, side=side, executed_qty=1,
        executed_price=price, fee=0.0, slippage=0.0, timestamp="2026-11-06T15:00:00+09:00",
        symbol="SYNTHETIC_CONTRACT:S9-PUT", option_type=CanonicalOptionType.PUT,
        strike=500.0, expiry="20261112", strategy_id="track9_event_overnight_insurance",
        group_id="S9-GROUP", leg_id="put", instrument_id="SYNTHETIC_CONTRACT:S9-PUT",
        contract_multiplier=100000.0, identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def test_virtual_account_uses_synthetic_contract_multiplier_for_realized_pnl() -> None:
    account = PaperTradingAccount(initial_capital=10_000_000)
    account.apply_execution(report(exec_id="buy", side=CanonicalOrderSide.BUY, price=5.0))
    assert account.position_mgr.positions["SYNTHETIC_CONTRACT:S9-PUT"]["contract_multiplier"] == 100000.0
    account.apply_execution(report(exec_id="sell", side=CanonicalOrderSide.SELL, price=10.0))
    assert account.pnl_engine.realized_pnl == Decimal("500000.0")
    assert account.position_mgr.positions == {}


def test_unrealized_pnl_uses_each_position_multiplier() -> None:
    account = PaperTradingAccount(initial_capital=10_000_000)
    account.position_mgr.positions = {
        "S9": {"qty": 1, "avg_price": 5.0, "side": "BUY", "contract_multiplier": 100000.0},
        "DEFAULT": {"qty": 1, "avg_price": 5.0, "side": "BUY"},
    }
    assert account.pnl_engine.calculate_unrealized(account.position_mgr.positions, 10.0) == Decimal("1750000.0")
