from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from application.composition.track9_option_contract_source import Track9OptionContractSource
from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource


MASTER_HASH = "a" * 64
EVIDENCE_HASH = "b" * 64
AS_OF = datetime(2026, 10, 21, 15, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def _rows():
    return tuple(
        {
            "short_code": symbol,
            "option_type": "PUT",
            "product_series": "MONTHLY",
            "instrument_family": "STANDARD",
            "strike": Decimal(str(strike)),
        }
        for symbol, strike in (
            ("C01611890", "890.0"),
            ("C01611887", "887.5"),
            ("C01611885", "885.0"),
            ("C01611882", "882.5"),
            ("C01611880", "880.0"),
            ("C01611877", "877.5"),
        )
    )


class _Resolver:
    def __init__(self, market_date, *, project_root):
        self.target_snapshot = SimpleNamespace(archive_sha256=MASTER_HASH)
        self._identities = {
            row["short_code"]: SimpleNamespace(
                expiry="20261112",
                option_type="PUT",
                strike=row["strike"],
            )
            for row in _rows()
        }

    def get_contract_identity(self, symbol):
        return self._identities.get(symbol)

    def get_expiry_record(self, symbol):
        if symbol not in self._identities:
            return None
        return SimpleNamespace(
            expiry_yyyymmdd="20261112",
            target_master_sha256=MASTER_HASH,
            evidence_set_sha256=EVIDENCE_HASH,
        )


class _PositionStore:
    def __init__(self, lots):
        self._lots = tuple(lots)

    def open_lots(self):
        return self._lots


class _QuoteSource:
    def __init__(self, as_of, *, invalid_symbol=None, missing_timestamp=False, volume=100):
        self.as_of = as_of
        self.invalid_symbol = invalid_symbol
        self.missing_timestamp = missing_timestamp
        self.volume = Decimal(str(volume))

    def get_order_book_with_timestamp(self, symbol, *, as_of):
        bid = Decimal("1.00")
        ask = Decimal("1.10")
        if symbol == self.invalid_symbol:
            ask = Decimal("0")
        book = SimpleNamespace(
            symbol=symbol,
            source="HistoricalObservationStore:KIS:H0IOASP0",
            bid_levels=(SimpleNamespace(price=bid, quantity=Decimal("5")),),
            ask_levels=(SimpleNamespace(price=ask, quantity=Decimal("5")),),
        )
        timestamp = None if self.missing_timestamp else self.as_of - timedelta(seconds=1)
        return book, timestamp

    def get_volume_with_timestamp(self, symbol, *, as_of):
        return self.volume, self.as_of - timedelta(seconds=1)


def _lot(*, run_id="run-1", strategy_id="TRACK1_TAIL_DEFENSE", expiry="20261112"):
    return SimpleNamespace(
        run_id=run_id,
        strategy_id=strategy_id,
        side="SELL",
        remaining_quantity=2,
        execution_id="s1-exec-1",
        instrument_identity=SimpleNamespace(
            option_type="PUT",
            expiry=expiry,
            symbol="C01611890",
            instrument_id="C01611890",
            strike=Decimal("890.0"),
        ),
    )


def _source(*, thresholds=True, lots=None, quote_source=None):
    options = {}
    if thresholds:
        options = {
            "max_quote_age_seconds": 5,
            "max_spread_ratio": Decimal("0.10"),
            "min_top_level_quantity": Decimal("1"),
            "min_volume": Decimal("10"),
            "s1_put_link_ratio": Decimal("1"),
            "third_strike_insufficient_action": "BLOCK_FOR_SESSION",
        }
    return Track9OptionContractSource(
        orderbook_source=quote_source or _QuoteSource(AS_OF),
        s1_position_lot_store=_PositionStore([_lot()] if lots is None else lots),
        run_id="run-1",
        project_root=".",
        resolver_factory=lambda day, project_root: _Resolver(day, project_root=project_root),
        rows_loader=lambda snapshot: _rows(),
        **options,
    )


def test_selects_exact_kis_monthly_put_ranks_four_and_three_from_s1_expiry():
    selection = _source().select(current_price=Decimal("891.04"), as_of=AS_OF)

    assert selection.status == "INPUTS_VALID"
    assert selection.expiry_yyyymmdd == "20261112"
    assert selection.s1_short_put_remaining == 2
    assert selection.atm_strike == Decimal("890.0")
    assert selection.rank4 is not None
    assert selection.rank4.strike == Decimal("880.0")
    assert selection.rank4.rank == 4
    assert selection.rank3 is not None
    assert selection.rank3.strike == Decimal("882.5")
    assert selection.rank3.rank == 3
    assert selection.master_sha256 == MASTER_HASH
    assert selection.rank4.expiry_evidence_sha256 == EVIDENCE_HASH


def test_missing_policy_thresholds_fail_closed_without_filling_values():
    selection = _source(thresholds=False).select(
        current_price=Decimal("891.04"), as_of=AS_OF
    )

    assert selection.status == "BLOCKED"
    assert "TRACK9_MIN_VOLUME_UNSET" in selection.blockers
    assert "TRACK9_S1_PUT_LINK_RATIO_UNSET" in selection.blockers
    assert "TRACK9_THIRD_STRIKE_INSUFFICIENT_ACTION_UNSET" in selection.blockers
    assert "TRACK9_QUOTE_FRESHNESS_THRESHOLD_UNSET" in selection.blockers
    assert "TRACK9_QUOTE_SPREAD_THRESHOLD_UNSET" in selection.blockers
    assert "TRACK9_TOP_LEVEL_DEPTH_THRESHOLD_UNSET" in selection.blockers


def test_invalid_two_sided_quote_blocks_selection():
    source = _source(
        quote_source=_QuoteSource(AS_OF, invalid_symbol="C01611880"),
    )
    selection = source.select(current_price=Decimal("891.04"), as_of=AS_OF)

    assert selection.status == "BLOCKED"
    assert selection.rank4 is not None
    assert "TRACK9_OPTION_TWO_SIDED_QUOTE_INVALID" in selection.rank4.blockers


def test_missing_quote_receipt_timestamp_blocks_selection():
    source = _source(quote_source=_QuoteSource(AS_OF, missing_timestamp=True))
    selection = source.select(current_price=Decimal("891.04"), as_of=AS_OF)

    assert selection.status == "BLOCKED"
    assert selection.rank4 is not None
    assert "TRACK9_OPTION_QUOTE_RECEIPT_TIME_UNAVAILABLE" in selection.rank4.blockers


def test_missing_s1_short_put_lots_blocks_without_guessing_expiry():
    source = _source(lots=[])

    with pytest.raises(ValueError, match="TRACK9_S1_SHORT_PUT_POSITION_UNAVAILABLE"):
        source.select(current_price=Decimal("891.04"), as_of=AS_OF)


def test_multiple_s1_expiries_block_instead_of_selecting_nearest_month():
    source = _source(lots=[_lot(), _lot(expiry="20261210")])

    with pytest.raises(ValueError, match="TRACK9_S1_SHORT_PUT_EXPIRY_AMBIGUOUS"):
        source.select(current_price=Decimal("891.04"), as_of=AS_OF)


def test_rest_hhmmss_remains_candidate_and_freshness_unknown():
    observation = SimpleNamespace(
        source="kis_vts_rest",
        collected_at=datetime(2026, 10, 21, 7, 48, tzinfo=timezone.utc),
        provenance=SimpleNamespace(source_timestamps=("154500",)),
    )

    assert HistoricalObservationOptionSource._freshness_timestamp(observation) is None
def test_websocket_hhmmss_and_receipt_time_do_not_verify_freshness():
    received_at = datetime(2026, 10, 21, 6, 30, tzinfo=timezone.utc)
    observation = SimpleNamespace(
        source="KIS:H0IOASP0",
        collected_at=received_at,
        provenance=SimpleNamespace(source_timestamps=("154500",)),
    )

    assert HistoricalObservationOptionSource._freshness_timestamp(observation) is None

