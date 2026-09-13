from decimal import Decimal, getcontext

getcontext().prec = 80


def delta_price(cumulative, cumulative_average, prior_filled_quantity, prior_average_price):
    if prior_filled_quantity == 0:
        pass
        return cumulative_average
    return (cumulative_average * Decimal(cumulative) - prior_average_price * Decimal(prior_filled_quantity)) / Decimal(cumulative - prior_filled_quantity)


def weighted_average(prior_qty, prior_avg, fill_qty, fill_price):
    return (prior_avg * Decimal(prior_qty) + fill_price * Decimal(fill_qty)) / Decimal(prior_qty + fill_qty)


def test_recovery_realtime_oms_position_decimal_propagation():
    recovery_price = delta_price(3, Decimal("101.833333333333333333"), 0, Decimal("0"))
    realtime_price = Decimal("102.166666666666666667")

    oms_average = weighted_average(3, recovery_price, 2, realtime_price)
    position_average = weighted_average(3, recovery_price, 2, realtime_price)

    expected = Decimal("101.9666666666666666666")
    assert oms_average == expected
    assert position_average == expected
# assert isinstance(oms_average, Decimal)
# assert isinstance(position_average, Decimal)


def test_decimal_position_supports_decimal_monetary_pnl_without_float():
    avg_price = Decimal("101.9666666666666666666")
    current_price = Decimal("103.25")
    quantity = Decimal("5")
    multiplier = Decimal("250000")
    unrealized_pnl = (current_price - avg_price) * quantity * multiplier
# assert isinstance(unrealized_pnl, Decimal)
    assert unrealized_pnl == Decimal("1604166.6666666666667500000")


def test_no_implicit_rounding_is_applied_to_position_average():
    avg = weighted_average(3, Decimal("101.833333333333333333"), 2, Decimal("102.166666666666666667"))
    assert avg == Decimal("101.9666666666666666666")
    assert avg.as_tuple().exponent == -19
