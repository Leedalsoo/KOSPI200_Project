"""Canonical option-expiry normalization at external/generated data boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


class CanonicalOptionExpiryError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalOptionExpiry:
    """Normalized expiry representation.

    exact is the only value permitted for authoritative contract identity.
    contract_month preserves a source that only identifies YYYYMM; no day is
    invented. Such a value must be resolved by the authoritative Option Master
    before entering an exact-identity execution/position boundary.
    """

    raw: str
    exact: str | None
    contract_month: str
    source_format: str

    @property
    def requires_authoritative_resolution(self) -> bool:
        return self.exact is None

    def require_exact(self) -> str:
        if self.exact is None:
            raise CanonicalOptionExpiryError(
                "OPTION_EXPIRY_EXACT_DATE_REQUIRED"
            )
        return self.exact


def normalize_option_expiry(value: str | date) -> CanonicalOptionExpiry:
    if isinstance(value, date):
        exact = value.strftime("%Y%m%d")
        return CanonicalOptionExpiry(
            raw=value.isoformat(),
            exact=exact,
            contract_month=exact[:6],
            source_format="date",
        )

    raw = str(value or "").strip()
    compact = raw.replace("-", "").replace("/", "")

    if re.fullmatch(r"\d{8}", compact):
        try:
            parsed = date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
        except ValueError as exc:
            raise CanonicalOptionExpiryError("OPTION_EXPIRY_INVALID_DATE") from exc
        exact = parsed.strftime("%Y%m%d")
        return CanonicalOptionExpiry(raw, exact, exact[:6], "YYYYMMDD")

    if re.fullmatch(r"\d{6}", compact):
        year, month = int(compact[:4]), int(compact[4:6])
        if not 1 <= month <= 12:
            raise CanonicalOptionExpiryError("OPTION_EXPIRY_INVALID_MONTH")
        return CanonicalOptionExpiry(raw, None, f"{year:04d}{month:02d}", "YYYYMM")

    raise CanonicalOptionExpiryError("OPTION_EXPIRY_UNSUPPORTED_FORMAT")
