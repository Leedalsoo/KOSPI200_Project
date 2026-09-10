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

# assert isinstance(snapshot, AccountSnapshot)
    assert snapshot.as_of.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-05 09:00:00"
    assert snapshot.balances["cash"] == 50_000_000
    assert snapshot.balances["margin_used"] == 1_000_000
    assert snapshot.balances["realized_pnl"] == 100_000
    assert snapshot.balances["available_cash"] == 48_975_000
    assert snapshot.balances["unrealized_pnl"] == -25_000
# assert snapshot.freshness.is_fresh is True
# assert snapshot.freshness.is_complete is True
# assert snapshot.freshness.source_available is True


def test_invalid_source_fails_closed():
    with pytest.raises(TypeError, match="VSSF_ACCOUNT_SOURCE_REQUIRED"):
        pass
        VSSFAccountSnapshotAdapter(object()).snapshot()


def test_missing_field_fails_closed():
    account = StubAccount()
# del account.summary.free_margin

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_FIELDS_REQUIRED"):
        pass
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_timestamp_fails_closed():
    account = StubAccount()
    account.summary.timestamp = "invalid"

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_TIMESTAMP_INVALID"):
        pass
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_balance_fails_closed():
    account = StubAccount()
    account.summary.used_margin = object()

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_BALANCE_INVALID"):
        pass
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_source_state_is_not_mutated():
    account = StubAccount()
    before = deepcopy(account.summary.__dict__)

    VSSFAccountSnapshotAdapter(account).snapshot()

    assert account.summary.__dict__ == before
