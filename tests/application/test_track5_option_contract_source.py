from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track5_option_contract_source import Track5OptionContractSource


class _Master:
    def list_contract_identities(self, expiry):
        assert expiry == "20261112"
        return tuple(
            SimpleNamespace(
                expiry=expiry,
                strike=Decimal(strike),
                option_type="CALL",
                contract_multiplier=Decimal("250000"),
                shrn_iscd=f"B{strike}",
            )
            for strike in ("875", "880", "885", "887.5")
        )


class _Books:
    def get_order_book(self, symbol):
        return SimpleNamespace(
            bid_levels=(SimpleNamespace(price=Decimal("4.0"), quantity=Decimal("2")),),
            ask_levels=(SimpleNamespace(price=Decimal("4.2"), quantity=Decimal("3")),),
        )


def test_track5_selects_exact_atm_not_second_or_third_otm():
    result = Track5OptionContractSource(_Master(), _Books()).select(
        expiry="20261112",
        current_price=Decimal("879.8"),
        option_type="CALL",
    )

    assert result.atm_strike == Decimal("880")
    assert result.selected_strike == Decimal("880")
    assert result.contract.shrn_iscd == "B880"
    assert result.strike_rank == 0


def test_track5_blocks_when_authoritative_two_sided_quote_is_unavailable():
    with pytest.raises(ValueError, match="TRACK5_ATM_ORDERBOOK_SOURCE_REQUIRED"):
        Track5OptionContractSource(_Master()).select(
            expiry="20261112",
            current_price=Decimal("879.8"),
            option_type="CALL",
        )


def test_track5_blocks_one_sided_or_empty_top_of_book():
    source = Track5OptionContractSource(
        _Master(),
        SimpleNamespace(
            get_order_book=lambda _symbol: SimpleNamespace(
                bid_levels=(SimpleNamespace(price=Decimal("4.0"), quantity=Decimal("1")),),
                ask_levels=(),
            )
        ),
    )
    with pytest.raises(ValueError, match="TRACK5_ATM_TWO_SIDED_ORDERBOOK_REQUIRED"):
        source.select(
            expiry="20261112",
            current_price=Decimal("879.8"),
            option_type="CALL",
        )
