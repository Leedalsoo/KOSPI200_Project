from decimal import Decimal

from environments.high_speed.validation_only_option_fee_model import calculate_option_fee


def test_kospi200_standard_online_mid_price_fee_includes_broker_and_exchange_costs():
    result = calculate_option_fee("1.26", 250000, 1)

    assert result["tier"] == "0_42_TO_BELOW_2_47_POINT"
    assert result["notional_krw"] == Decimal("315000.00")
    assert result["brokerage_fee_raw_krw"] == Decimal("1206.1350000000")
    assert result["exchange_fee_raw_krw"] == Decimal("39.8601000000")
    assert result["total_fee_krw"] == 1246
    assert result["tax_krw"] == 0


def test_kospi200_low_and_high_price_tiers_use_exchange_fixed_fee():
    low = calculate_option_fee("0.30", 250000, 1)
    high = calculate_option_fee("2.50", 250000, 1)

    assert low["tier"] == "BELOW_0_42_POINT"
    assert low["exchange_fee_raw_krw"] == Decimal("13")
    assert high["tier"] == "2_47_POINT_AND_ABOVE"
    assert high["exchange_fee_raw_krw"] == Decimal("78")


def test_kospi200_fee_model_rejects_non_positive_fill_inputs():
    import pytest

    with pytest.raises(ValueError, match="SYNTHETIC_OPTION_FEE_INPUT_MUST_BE_POSITIVE"):
        calculate_option_fee("0", 250000, 1)
