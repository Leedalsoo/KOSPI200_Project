from decimal import Decimal

from environments.virtual.account.track9_margin_read_model import VSSFTrack9MarginReadModel
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount


def test_vssf_margin_snapshot_preserves_account_state_and_observation_time():
    account = PaperTradingAccount(initial_capital=25000000)
    adapter = VSSFAccountSnapshotAdapter(account)
    model = VSSFTrack9MarginReadModel(adapter)

    snapshot = model.snapshot(run_id="RUN-MARGIN-1")

    assert snapshot is not None
    assert snapshot.run_id == "RUN-MARGIN-1"
    assert snapshot.account_id == "ACC-VSSF-001"
    assert snapshot.total_balance == Decimal("25000000.0")
    assert snapshot.used_margin == Decimal("0")
    assert snapshot.free_margin == Decimal("25000000.0")
    assert snapshot.observed_at == adapter.snapshot().as_of
    assert snapshot.source == "VSSF:AccountSnapshot"


def test_margin_ratio_is_derived_only_from_the_same_authoritative_snapshot():
    account = PaperTradingAccount(initial_capital=10000000)
    adapter = VSSFAccountSnapshotAdapter(account)
    model = VSSFTrack9MarginReadModel(adapter)

    snapshot = model.snapshot(run_id="RUN-MARGIN-2")

    assert snapshot is not None
    ratio = snapshot.used_margin / snapshot.total_balance
    assert ratio == Decimal("0")


def test_missing_run_id_is_fail_closed():
    account = PaperTradingAccount()
    model = VSSFTrack9MarginReadModel(VSSFAccountSnapshotAdapter(account))

    assert model.snapshot(run_id="") is None
