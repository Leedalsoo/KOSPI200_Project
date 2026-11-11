"""Validation-only bridge for explicit synthetic S9 contract assumptions.

This module must not be imported by production, KIS, REAL_VTS or Live paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Any

from core.strategy.track9_independent_policy import Track9OptionCandidate


class Track9SyntheticProfileError(ValueError):
    """Raised when a synthetic-only profile or contract identity is invalid."""


@dataclass(frozen=True)
class Track9SyntheticContractProfile:
    profile_id: str
    instrument_family: str
    contract_multiplier: Decimal
    tradable: bool
    provenance: str = "SYNTHETIC"

    @classmethod
    def load(cls, path: str | Path) -> "Track9SyntheticContractProfile":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROFILE_UNREADABLE") from exc
        required_false = (
            "runtime_eligible", "production_runtime_eligible", "kis_api_allowed",
            "real_vts_allowed", "live_api_allowed", "account_api_allowed", "orders_allowed",
        )
        if payload.get("provenance") != "SYNTHETIC" or payload.get("validation_only") is not True:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROFILE_VALIDATION_ONLY_REQUIRED")
        if any(payload.get(key) is not False for key in required_false):
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROFILE_PRODUCTION_GUARD_REQUIRED")
        if payload.get("instrument_family") != "STANDARD":
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROFILE_STANDARD_FAMILY_REQUIRED")
        if payload.get("tradability_basis") != "SYNTHETIC_SCENARIO_ELIGIBILITY_ONLY":
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_TRADABILITY_BASIS_REQUIRED")
        try:
            multiplier = Decimal(str(payload["contract_multiplier"]))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_MULTIPLIER_INVALID") from exc
        if not multiplier.is_finite() or multiplier <= 0:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_MULTIPLIER_INVALID")
        if not isinstance(payload.get("tradable"), bool):
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_TRADABILITY_INVALID")
        profile_id = str(payload.get("profile_id") or "").strip()
        if not profile_id:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROFILE_ID_REQUIRED")
        return cls(
            profile_id=profile_id,
            instrument_family="STANDARD",
            contract_multiplier=multiplier,
            tradable=payload["tradable"],
        )

    def build_candidates(self, identities: Iterable[Any]) -> tuple[Track9OptionCandidate, ...]:
        if self.provenance != "SYNTHETIC":
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_PROVENANCE_REQUIRED")
        candidates: list[Track9OptionCandidate] = []
        seen: set[str] = set()
        for identity in identities:
            symbol = str(getattr(identity, "shrn_iscd", "") or "").strip()
            expiry_text = str(getattr(identity, "expiry", "") or "").strip()
            option_type = str(getattr(identity, "option_type", "") or "").upper()
            family = str(getattr(identity, "instrument_family", "") or "").upper()
            strike_value = getattr(identity, "strike", None)
            if not symbol or symbol in seen:
                raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_CONTRACT_SYMBOL_MISSING_OR_DUPLICATE")
            if family != self.instrument_family:
                continue
            try:
                expiry = date.fromisoformat(expiry_text)
                strike = Decimal(str(strike_value))
            except (TypeError, ValueError, InvalidOperation) as exc:
                raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_CONTRACT_IDENTITY_INVALID") from exc
            if option_type not in {"PUT", "CALL"} or strike <= 0:
                raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_CONTRACT_IDENTITY_INVALID")
            seen.add(symbol)
            candidates.append(Track9OptionCandidate(
                symbol=symbol,
                expiry=expiry,
                option_type=option_type,
                strike=strike,
                instrument_family=family,
                contract_multiplier=self.contract_multiplier,
                tradable=self.tradable,
            ))
        if not candidates:
            raise Track9SyntheticProfileError("TRACK9_SYNTHETIC_STANDARD_CONTRACTS_UNAVAILABLE")
        return tuple(candidates)


__all__ = ["Track9SyntheticContractProfile", "Track9SyntheticProfileError"]