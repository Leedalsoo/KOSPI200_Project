from datetime import date
import pytest

from contracts.option_expiry import CanonicalOptionExpiryError, normalize_option_expiry


def test_normalize_exact_yyyymmdd():
    value = normalize_option_expiry("2026-10-15")
    assert value.exact == "20261015"
    assert value.contract_month == "202610"
    assert not value.requires_authoritative_resolution


def test_normalize_date_object():
    value = normalize_option_expiry(date(2026, 10, 15))
    assert value.exact == "20261015"


def test_normalize_month_without_inventing_day():
    value = normalize_option_expiry("202610")
    assert value.exact is None
    assert value.contract_month == "202610"
    assert value.requires_authoritative_resolution
    with pytest.raises(CanonicalOptionExpiryError, match="EXACT_DATE_REQUIRED"):
        value.require_exact()


def test_normalize_invalid_date():
    with pytest.raises(CanonicalOptionExpiryError, match="INVALID_DATE"):
        normalize_option_expiry("20261340")


def test_normalize_invalid_month():
    with pytest.raises(CanonicalOptionExpiryError, match="INVALID_MONTH"):
        normalize_option_expiry("202613")
