from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.option.option_master import KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER


@dataclass(frozen=True)
class Track6OptionContractSelection:
    atm_strike: Decimal
    put: Any
    call: Any
    source: str = "OptionMaster.list_contract_identities"


@dataclass(frozen=True)
class Track6RankedOptionContractSelection:
    rank: int
    atm_strike: Decimal
    put: Any
    call: Any


class Track6OptionContractSource:
    """Resolve Track6 insurance contracts from listed Option Master identities."""

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def select(self, *, expiry: str, current_price: Decimal,
               identity_prefix: str | None = None) -> Track6OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK6_OPTION_MASTER_REQUIRED")
        identities = tuple(self.option_master.list_contract_identities(expiry))
        if identity_prefix is not None:
            prefix = str(identity_prefix).strip()
            if not prefix.startswith("SYNTHETIC_CONTRACT:"):
                raise ValueError("TRACK6_SYNTHETIC_IDENTITY_SCOPE_INVALID")
            identities = tuple(
                identity for identity in identities
                if str(getattr(identity, "shrn_iscd", "")).startswith(prefix + "-")
            )
            if not identities:
                raise ValueError("TRACK6_SYNTHETIC_IDENTITY_SCOPE_EMPTY")
        calls = {}
        puts = {}
        for identity in identities:
            multiplier = getattr(identity, "contract_multiplier", None)
            if multiplier is None or Decimal(str(multiplier)) != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
                continue
            option_type = str(getattr(identity, "option_type", "")).upper()
            strike = getattr(identity, "strike", None)
            if option_type not in {"CALL", "PUT"} or strike is None:
                continue
            strike = Decimal(str(strike))
            if strike <= 0 or not getattr(identity, "shrn_iscd", ""):
                continue
            target = calls if option_type == "CALL" else puts
            target[strike] = identity

        listed_strikes = sorted(set(calls) & set(puts))
        if not listed_strikes:
            raise ValueError("TRACK6_LISTED_STRIKE_NOT_FOUND")
        offset = Decimal("12.5")
        valid_centers = [strike for strike in listed_strikes if strike-offset in puts and strike+offset in calls]
        if valid_centers:
            # Prefer the configured 12.5-point structure whenever the listed
            # master actually contains both legs.
            atm = min(valid_centers, key=lambda strike: (abs(strike - current_price), strike))
            put_strike = atm - offset
            call_strike = atm + offset
        else:
            # Far-month KRX strike ladders may not contain an exact 12.5-point
            # symmetric pair. Strategy 6 requires listed PUT/CALL identities,
            # not a fixed offset, so choose the nearest listed OTM legs without
            # inventing strikes or accepting a one-sided ladder.
            put_candidates = [strike for strike in puts if strike < current_price]
            call_candidates = [strike for strike in calls if strike > current_price]
            if not put_candidates or not call_candidates:
                raise ValueError("TRACK6_LISTED_STRIKE_NOT_FOUND")
            put_strike = min(put_candidates, key=lambda strike: (abs(strike - (current_price-offset)), strike))
            call_strike = min(call_candidates, key=lambda strike: (abs(strike - (current_price+offset)), strike))
            if put_strike > call_strike:
                raise ValueError("TRACK6_LISTED_STRIKE_NOT_FOUND")
            atm = (put_strike + call_strike) / Decimal("2")
        put = puts.get(put_strike)
        call = calls.get(call_strike)
        if put is None or call is None:
            raise ValueError("TRACK6_LISTED_STRIKE_NOT_FOUND")
        if put.contract_multiplier is None or call.contract_multiplier is None:
            raise ValueError("TRACK6_CONTRACT_MULTIPLIER_REQUIRED")
        if Decimal(str(put.contract_multiplier)) <= 0 or Decimal(str(call.contract_multiplier)) <= 0:
            raise ValueError("TRACK6_CONTRACT_MULTIPLIER_REQUIRED")
        if Decimal(str(put.contract_multiplier)) != Decimal(str(call.contract_multiplier)):
            raise ValueError("TRACK6_CONTRACT_MULTIPLIER_MISMATCH")
        return Track6OptionContractSelection(atm, put, call)

    def select_ranked_candidates(self, *, expiry: str, current_price: Decimal,
                                 identity_prefix: str | None = None) -> tuple[Track6RankedOptionContractSelection, ...]:
        """Return only listed rank-5/rank-6 symmetric pairs; never invent strikes."""
        if self.option_master is None:
            raise ValueError("TRACK6_OPTION_MASTER_REQUIRED")
        if current_price is None or Decimal(str(current_price)) <= 0:
            raise ValueError("TRACK6_CURRENT_PRICE_REQUIRED")
        identities = tuple(self.option_master.list_contract_identities(expiry))
        if identity_prefix is not None:
            prefix = str(identity_prefix).strip()
            if not prefix.startswith("SYNTHETIC_CONTRACT:"):
                raise ValueError("TRACK6_SYNTHETIC_IDENTITY_SCOPE_INVALID")
            identities = tuple(
                identity for identity in identities
                if str(getattr(identity, "shrn_iscd", "")).startswith(prefix + "-")
            )
            if not identities:
                raise ValueError("TRACK6_SYNTHETIC_IDENTITY_SCOPE_EMPTY")
        calls: dict[Decimal, Any] = {}
        puts: dict[Decimal, Any] = {}
        for identity in identities:
            multiplier = getattr(identity, "contract_multiplier", None)
            if multiplier is None or Decimal(str(multiplier)) != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
                continue
            option_type = str(getattr(identity, "option_type", "")).upper()
            strike_value = getattr(identity, "strike", None)
            if option_type not in {"CALL", "PUT"} or strike_value is None:
                continue
            strike = Decimal(str(strike_value))
            if strike <= 0 or not getattr(identity, "shrn_iscd", ""):
                continue
            (calls if option_type == "CALL" else puts)[strike] = identity

        centers = sorted(set(calls) & set(puts))
        ranked: list[Track6RankedOptionContractSelection] = []
        for rank, offset in ((5, Decimal("12.5")), (6, Decimal("15.0"))):
            valid_centers = [
                center for center in centers
                if center - offset in puts and center + offset in calls
            ]
            if not valid_centers:
                continue
            center = min(valid_centers, key=lambda value: (abs(value - Decimal(str(current_price))), value))
            put, call = puts[center - offset], calls[center + offset]
            if (Decimal(str(put.contract_multiplier)) <= 0
                    or Decimal(str(call.contract_multiplier)) <= 0
                    or Decimal(str(put.contract_multiplier)) != Decimal(str(call.contract_multiplier))):
                continue
            ranked.append(Track6RankedOptionContractSelection(rank, center, put, call))
        return tuple(ranked)

