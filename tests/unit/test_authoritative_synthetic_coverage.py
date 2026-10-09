from decimal import Decimal

from scripts.generate_authoritative_option_synthetic_3m import select_monthly_strikes_for_coverage


def test_coverage_uses_any_authoritative_listed_pair_when_scenario_spot_moves_beyond_25_points():
    listed = [Decimal(value) for value in ("937.5", "950", "962.5", "975", "1000")]

    selected, daily_pair_available, monthly_pair_available = select_monthly_strikes_for_coverage(
        listed, spot=990.0
    )

    assert set(selected).issubset(set(listed))
    assert len(selected) == 5
    assert daily_pair_available is True
    assert monthly_pair_available is False
