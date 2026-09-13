from decimal import Decimal, getcontext


def delta_price(cumulative, cumulative_average, prior_filled_quantity, prior_average_price):
    if prior_filled_quantity == 0:
        pass
        return cumulative_average
    return (cumulative_average * Decimal(cumulative) - prior_average_price * Decimal(prior_filled_quantity)) / Decimal(cumulative - prior_filled_quantity)


def test_decimal_delta_price_is_exact_without_float_conversion():
    getcontext().prec = 80
    result = delta_price(3, Decimal("100.01"), 2, Decimal("100.00"))
    assert result == Decimal("100.03")


def test_high_precision_cumulative_average_preserves_decimal_precision():
    getcontext().prec = 80
    current_avg = Decimal("100.123456789")
    prior_avg = Decimal("99.987654321")
    result = delta_price(7, current_avg, 3, prior_avg)
    expected = (current_avg * 7 - prior_avg * 3) / 4
    assert result == expected
# assert isinstance(result, Decimal)


def test_rounding_boundary_is_not_implicitly_rounded():
    getcontext().prec = 80
    below = delta_price(3, Decimal("100.0000001"), 2, Decimal("100.0000000"))
    at = delta_price(3, Decimal("100.00000005"), 2, Decimal("100.0000000"))
    above = delta_price(3, Decimal("100.00000006"), 2, Decimal("100.0000000"))
    assert below == Decimal("100.0000003")
    assert at == Decimal("100.00000015")
    assert above == Decimal("100.00000018")


def test_sequential_recovery_preserves_weighted_average_invariant():
    getcontext().prec = 80
    first_qty = 2
    first_avg = Decimal("101.25")
    second_cumulative_qty = 5
    second_cumulative_avg = Decimal("101.60")

    first_price = delta_price(first_qty, first_avg, 0, Decimal("0"))
    second_price = delta_price(second_cumulative_qty, second_cumulative_avg, first_qty, first_avg)

    assert first_price == Decimal("101.25")
    assert (first_price * first_qty + second_price * 3) / second_cumulative_qty == second_cumulative_avg
