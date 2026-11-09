from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track5_option_contract_source import Track5OptionContractSource
from environments.high_speed.validation_only_s15b_option_adapter import S15BOptionValidationAdapter


AS_OF = datetime(2026, 11, 9, 9, 1, tzinfo=timezone.utc)


class _Master:
    def __init__(self, *, multiplier=Decimal("250000")):
        self.multiplier = multiplier

    def list_contract_identities(self, expiry):
        assert expiry == "20261112"
        return tuple(
            SimpleNamespace(
                expiry=expiry,
                strike=Decimal(strike),
                option_type=option_type,
                info_type="5" if option_type == "CALL" else "6",
                instrument_family="STANDARD",
                contract_multiplier=self.multiplier,
                shrn_iscd=f"{option_type[0]}{strike}",
            )
            for option_type in ("CALL", "PUT")
            for strike in ("875", "880", "885", "887.5")
        )


class _Books:
    def __init__(self, *, observed_at=AS_OF - timedelta(seconds=1), one_sided=False, source="KIS_VTS"):
        self.observed_at = observed_at
        self.one_sided = one_sided
        self.source = source

    def get_order_book(self, symbol):
        return SimpleNamespace(
            bid_levels=(SimpleNamespace(price=Decimal("4.0"), quantity=Decimal("2")),),
            ask_levels=() if self.one_sided else (
                SimpleNamespace(price=Decimal("4.2"), quantity=Decimal("3")),
            ),
            observed_at=self.observed_at,
            source=self.source,
        )


def _select(source, **overrides):
    values = dict(
        expiry="20261112",
        current_price=Decimal("879.8"),
        option_type="CALL",
        as_of=AS_OF,
        max_quote_age_seconds=30,
    )
    values.update(overrides)
    return source.select(**values)


def test_track5_selects_exact_atm_and_returns_fresh_two_sided_quote():
    result = _select(Track5OptionContractSource(_Master(), _Books()))
    assert result.atm_strike == Decimal("880")
    assert result.selected_strike == Decimal("880")
    assert result.contract.shrn_iscd == "C880"
    assert result.strike_rank == 0
    assert result.bid_price == Decimal("4.0")
    assert result.ask_price == Decimal("4.2")
    assert result.observed_at == AS_OF - timedelta(seconds=1)
    assert result.contract_multiplier == Decimal("250000")
    assert result.validation_only is False
    assert result.provenance == "KIS_VTS"
    assert Track5OptionContractSource(_Master(), _Books()).validation_only_max_quote_age_seconds is None


def test_track5_rejects_atm_tie_until_tie_break_is_approved():
    with pytest.raises(ValueError, match="TRACK5_ATM_TIE_BREAK_UNAPPROVED"):
        _select(
            Track5OptionContractSource(_Master(), _Books()),
            current_price=Decimal("882.5"),
        )


def test_track5_blocks_when_quote_freshness_policy_is_missing():
    with pytest.raises(ValueError, match="TRACK5_QUOTE_FRESHNESS_POLICY_UNSET"):
        _select(
            Track5OptionContractSource(_Master(), _Books()),
            max_quote_age_seconds=None,
        )


def test_track5_blocks_when_source_timestamp_is_missing():
    source = Track5OptionContractSource(
        _Master(),
        SimpleNamespace(
            get_order_book=lambda _symbol: SimpleNamespace(
                bid_levels=(SimpleNamespace(price=Decimal("4.0"), quantity=Decimal("1")),),
                ask_levels=(SimpleNamespace(price=Decimal("4.2"), quantity=Decimal("1")),),
                source="KIS_VTS",
            )
        ),
    )
    with pytest.raises(ValueError, match="TRACK5_ORDERBOOK_SOURCE_TIMESTAMP_UNAVAILABLE"):
        _select(source)


def test_track5_blocks_stale_or_future_source_timestamp():
    stale = Track5OptionContractSource(
        _Master(), _Books(observed_at=AS_OF - timedelta(seconds=31))
    )
    with pytest.raises(ValueError, match="TRACK5_ORDERBOOK_SOURCE_STALE"):
        _select(stale)

    future = Track5OptionContractSource(
        _Master(), _Books(observed_at=AS_OF + timedelta(seconds=1))
    )
    with pytest.raises(ValueError, match="TRACK5_ORDERBOOK_SOURCE_TIMESTAMP_IN_FUTURE"):
        _select(future)


def test_track5_blocks_one_sided_or_empty_top_of_book():
    source = Track5OptionContractSource(_Master(), _Books(one_sided=True))
    with pytest.raises(ValueError, match="TRACK5_ATM_TWO_SIDED_ORDERBOOK_REQUIRED"):
        _select(source)


def test_track5_does_not_invent_missing_kis_multiplier():
    result = _select(Track5OptionContractSource(_Master(multiplier=None), _Books()))
    assert result.contract_multiplier is None
    assert result.provenance == "KIS_VTS"


def test_track5_blocks_when_standard_product_family_is_not_proven():
    class UnknownFamilyMaster:
        def list_contract_identities(self, expiry):
            return (
                SimpleNamespace(
                    expiry=expiry,
                    strike=Decimal("880"),
                    option_type="CALL",
                    contract_multiplier=None,
                    shrn_iscd="C880",
                ),
            )

    with pytest.raises(ValueError, match="TRACK5_LISTED_STANDARD_OPTION_NOT_FOUND"):
        _select(Track5OptionContractSource(UnknownFamilyMaster(), _Books()))


def test_track5_active_position_refresh_uses_exact_original_contract_not_new_atm():
    source = Track5OptionContractSource(_Master(), _Books())
    result = source.select_exact(
        expiry="20261112",
        strike=Decimal("875"),
        option_type="CALL",
        as_of=AS_OF,
        max_quote_age_seconds=30,
    )
    assert result.selected_strike == Decimal("875")
    assert result.contract.shrn_iscd == "C875"
    assert result.strike_rank == -1


def test_no1469_s15b_synthetic_orderbook_is_usable_only_for_anchored_validation_contracts():
    adapter = S15BOptionValidationAdapter()
    source = Track5OptionContractSource(adapter, adapter)
    assert source.validation_only_max_quote_age_seconds == 600
    as_of = datetime.fromisoformat("2026-11-06T10:00:00.100000+09:00")
    result = source.select(
        expiry="20261112",
        current_price=Decimal("885.00"),
        option_type="CALL",
        as_of=as_of,
        max_quote_age_seconds=600,
    )
    assert result.contract.symbol == "B01611885"
    assert result.selected_strike == Decimal("885.00")
    assert result.bid_price == Decimal("42.93")
    assert result.ask_price == Decimal("43.37")
    assert result.observed_at == datetime.fromisoformat("2026-11-06T10:00:00+09:00")
    assert result.provenance.startswith("SYNTHETIC:DERIVED_SCENARIO")
    assert result.validation_only is True
    # The synthetic book never supplies an authoritative product multiplier.
    assert result.contract_multiplier is None


def test_no1469_does_not_fabricate_unanchored_opposite_put_contracts():
    adapter = S15BOptionValidationAdapter()
    source = Track5OptionContractSource(adapter, adapter)
    as_of = datetime.fromisoformat("2026-11-06T10:00:00.100000+09:00")
    with pytest.raises(ValueError, match="TRACK5_LISTED_STANDARD_OPTION_NOT_FOUND"):
        source.select(
            expiry="20261112",
            current_price=Decimal("885.00"),
            option_type="PUT",
            as_of=as_of,
            max_quote_age_seconds=600,
        )


def test_track5_rejects_conflicting_mini_family_even_if_info_type_looks_standard():
    class ConflictingMaster:
        def list_contract_identities(self, expiry):
            return (
                SimpleNamespace(
                    expiry=expiry,
                    strike=Decimal("880"),
                    option_type="CALL",
                    info_type="5",
                    instrument_family="MINI",
                    contract_multiplier=None,
                    shrn_iscd="C880",
                ),
            )

    with pytest.raises(ValueError, match="TRACK5_LISTED_STANDARD_OPTION_NOT_FOUND"):
        _select(Track5OptionContractSource(ConflictingMaster(), _Books()))
