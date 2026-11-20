import pytest

from verification.analyze_q25_a8_s5_reversal_persistence_20261117 import (
    _add_peak_retracement,
    first_persistent_time,
)


def _rows(values):
    return [
        {"second": second, "adverse": adverse, "favorable": favorable}
        for second, adverse, favorable in values
    ]


def test_persistence_requires_consecutive_observed_seconds():
    rows = _rows([(1, 1.2, 0), (2, 1.3, 0), (3, 1.1, 0)])
    assert first_persistent_time(rows, "adverse", 1.0, 3) == 3


def test_missing_second_breaks_persistence():
    rows = _rows([(1, 1.2, 0), (2, 1.3, 0), (4, 1.1, 0), (5, 1.2, 0)])
    assert first_persistent_time(rows, "adverse", 1.0, 3) is None


def test_pre_advance_confirmation_must_complete_strictly_before_advance():
    rows = _rows([(1, 1.2, 0), (2, 1.3, 0), (3, 1.1, 0), (4, 0, 1.0)])
    assert first_persistent_time(rows, "adverse", 1.0, 3, before_sec=3) is None
    assert first_persistent_time(rows, "adverse", 1.0, 3, before_sec=4) == 3


def test_peak_retracement_resets_when_new_favorable_peak_is_made():
    rows = _rows([(1, 0, 1.0), (2, 0, 2.0), (3, 0, 1.4), (4, 0, 2.2), (5, 0, 1.4)])
    retraced = _add_peak_retracement(rows, advance_second=1)
    assert [row["retrace"] for row in retraced] == pytest.approx([0.0, 0.0, 0.6, 0.0, 0.8])
