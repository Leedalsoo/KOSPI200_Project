[Child Page] virtual_account.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualAccount(AccountProvider):
    cash: Decimal
    margin_used: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    clock: ClockProvider | None = None

    def available_cash(self) -> Decimal:
        return self.cash - self.margin_used

    def snapshot(self) -> AccountSnapshot:
        if self.clock is None:
            raise RuntimeError("VirtualAccount.snapshot requires an injected ClockProvider")
        return AccountSnapshot(
            as_of=self.clock.now(),
            balances={
                "cash": self.cash,
                "margin_used": self.margin_used,
                "realized_pnl": self.realized_pnl,
                "available_cash": self.available_cash(),
            },
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_account_state",
            ),
        )
```
## Standard Contract 정합화
    - 기존 cash / margin_used / realized_pnl / available_cash() 기능은 유지한다.
    - AccountProvider.snapshot()을 구현하여 Virtual Account의 내부 상태를 canonical AccountSnapshot으로 노출한다.
    - AccountSnapshot.as_of는 Virtual Clock에서 취득한다. 시스템 시간을 직접 호출하지 않는다.
    - 기존 생성 코드와의 호환성을 위해 clock은 optional로 두되, snapshot 시점에는 반드시 주입된 ClockProvider가 있어야 한다.
    - balances에는 기존 계정 상태에서 이미 존재하는 값만 매핑하며 통화 단위나 수수료/증거금 계산 규칙을 새로 발명하지 않는다.
    - 현재 VSSF 계정의 실제 margin/PnL/ledger 정책은 그대로 유지하며 이번 변경에서 재정의하지 않는다.

[Child Page] vssf_account_snapshot_adapter.py
```python
from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality


class VSSFAccountSnapshotAdapter(AccountProvider):
    """Read-only projection of VSSF authoritative account state."""

    def __init__(self, account_source: Any):
        self._account_source = account_source

    def snapshot(self) -> AccountSnapshot:
        getter = getattr(self._account_source, "get_canonical_summary", None)
        if not callable(getter):
            raise TypeError("VSSF_ACCOUNT_SOURCE_REQUIRED")

        summary = getter()
        required = (
            "total_balance",
            "realized_pnl",
            "unrealized_pnl",
            "used_margin",
            "free_margin",
            "timestamp",
        )
        missing = [name for name in required if not hasattr(summary, name)]
        if missing:
            raise TypeError(f"VSSF_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}")

        try:
            as_of = datetime.strptime(str(summary.timestamp), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError) as exc:
            raise TypeError("VSSF_ACCOUNT_TIMESTAMP_INVALID") from exc

        try:
            balances = {
                "cash": Decimal(str(summary.total_balance)),
                "margin_used": Decimal(str(summary.used_margin)),
                "realized_pnl": Decimal(str(summary.realized_pnl)),
                "available_cash": Decimal(str(summary.free_margin)),
                "unrealized_pnl": Decimal(str(summary.unrealized_pnl)),
            }
        except Exception as exc:
            raise TypeError("VSSF_ACCOUNT_BALANCE_INVALID") from exc

        return AccountSnapshot(
            as_of=as_of,
            balances=balances,
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="vssf_authoritative_account_summary",
            ),
        )
```
## 경계
    - VSSF PaperTradingAccount.get_canonical_summary()를 authoritative source로 사용한다.
    - total_balance → cash, used_margin → margin_used, free_margin → available_cash, realized_pnl → realized_pnl, unrealized_pnl → unrealized_pnl로 기존 실제 상태를 그대로 projection한다.
    - Account/PnL/Margin/Ledger 계산이나 mutation은 수행하지 않는다.
    - VSSF summary의 timestamp를 AccountSnapshot.as_of로 변환하며, 변환 실패 시 현재시간으로 대체하지 않고 fail-closed 한다.
    - CanonicalAccountSummary.positions는 Account projection에서 Position 상태로 재해석하지 않는다.
    - VSSF account의 객체 identity와 lifetime을 변경하지 않는다.

[Child Page] test_vssf_account_snapshot_adapter.py
```python
from copy import deepcopy

import pytest

from contracts.types import AccountSnapshot
from environments.virtual.account.vssf_account_snapshot_adapter import (
    VSSFAccountSnapshotAdapter,
)


class StubSummary:
    def __init__(self):
        self.total_balance = 50_000_000.0
        self.realized_pnl = 100_000.0
        self.unrealized_pnl = -25_000.0
        self.used_margin = 1_000_000.0
        self.free_margin = 48_975_000.0
        self.timestamp = "2026-09-05 09:00:00"


class StubAccount:
    def __init__(self):
        self.summary = StubSummary()

    def get_canonical_summary(self):
        return self.summary


def test_authoritative_summary_maps_to_account_snapshot():
    snapshot = VSSFAccountSnapshotAdapter(StubAccount()).snapshot()

    assert isinstance(snapshot, AccountSnapshot)
    assert snapshot.as_of.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-05 09:00:00"
    assert snapshot.balances["cash"] == 50_000_000
    assert snapshot.balances["margin_used"] == 1_000_000
    assert snapshot.balances["realized_pnl"] == 100_000
    assert snapshot.balances["available_cash"] == 48_975_000
    assert snapshot.balances["unrealized_pnl"] == -25_000
    assert snapshot.freshness.is_fresh is True
    assert snapshot.freshness.is_complete is True
    assert snapshot.freshness.source_available is True


def test_invalid_source_fails_closed():
    with pytest.raises(TypeError, match="VSSF_ACCOUNT_SOURCE_REQUIRED"):
        VSSFAccountSnapshotAdapter(object()).snapshot()


def test_missing_field_fails_closed():
    account = StubAccount()
    del account.summary.free_margin

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_FIELDS_REQUIRED"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_timestamp_fails_closed():
    account = StubAccount()
    account.summary.timestamp = "invalid"

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_TIMESTAMP_INVALID"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_balance_fails_closed():
    account = StubAccount()
    account.summary.used_margin = object()

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_BALANCE_INVALID"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_source_state_is_not_mutated():
    account = StubAccount()
    before = deepcopy(account.summary.__dict__)

    VSSFAccountSnapshotAdapter(account).snapshot()

    assert account.summary.__dict__ == before
```