from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from contracts.kis_option_product_spec import KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
from typing import Any


@dataclass(frozen=True)
class Track2OptionContractSelection:
    expiry: str
    atm_strike: Decimal
    put: Any
    call: Any
    source: str = "OptionMaster.list_contract_identities"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc


class Track2OptionContractSource:
    """Resolve Track2 ATM strike from authoritative listed Option Master identities."""

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        text = str(value or "").strip().lower()
        return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)

    @classmethod
    def _has_exact_expiry_provenance(cls, identity: Any) -> bool:
        source = str(getattr(identity, "expiry_source", "") or "").strip().upper()
        expiry_master_hash = getattr(identity, "expiry_master_sha256", None)
        master_hash = getattr(identity, "master_sha256", None)
        if not (
            cls._valid_sha256(expiry_master_hash)
            and cls._valid_sha256(master_hash)
            and str(expiry_master_hash).lower() == str(master_hash).lower()
        ):
            return False
        endpoint = str(getattr(identity, "expiry_endpoint", "") or "")
        tr_id = str(getattr(identity, "expiry_tr_id", "") or "")
        if source == "KIS_REST:FUTS_LAST_TR_DATE":
            return (
                cls._valid_sha256(getattr(identity, "expiry_response_sha256", None))
                and endpoint == "/uapi/domestic-futureoption/v1/quotations/inquire-price"
                and tr_id == "FHMIF10000000"
                and bool(getattr(identity, "expiry_observed_at", None))
            )
        if source == "KIS_OFFICIAL_PRODUCT_SPEC:MONTHLY_SECOND_THURSDAY":
            return (
                endpoint == "https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp"
                and tr_id == "KIS_PRODUCT_GUIDE_MONTHLY_OPTION_EXPIRY"
            )
        if source == "KIS_OFFICIAL_INDEX_MASTER:EXACT_DATE":
            return (
                endpoint == "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"
                and tr_id == "KIS_MST_EXACT_EXPIRY"
            )
        return False

    def nearest_expiry(self, *, as_of: date) -> str:
        if self.option_master is None:
            raise ValueError("TRACK2_OPTION_MASTER_REQUIRED")
        expiries = sorted({
            str(identity.expiry).replace("-", "")[:8]
            for identity in self.option_master.list_contract_identities()
            if getattr(identity, "expiry", None)
            and getattr(identity, "shrn_iscd", "")
            and str(getattr(identity, "instrument_family", "") or "").upper() == "STANDARD"
            and str(getattr(identity, "product_series", "") or "").upper() == "MONTHLY"
            and self._has_exact_expiry_provenance(identity)
        })
        if not expiries:
            raise ValueError("TRACK2_OPTION_EXPIRY_NOT_FOUND")
        candidates = [value for value in expiries if value >= as_of.strftime("%Y%m%d")]
        if not candidates:
            raise ValueError("TRACK2_OPTION_EXPIRY_NOT_FOUND")
        return candidates[0]

    def resolve_identity(self, *, expiry: str, option_type: str, strike: Decimal) -> Any:
        """Resolve exactly one listed STANDARD/MONTHLY KIS identity for a planned leg."""
        if self.option_master is None:
            raise ValueError("TRACK2_OPTION_MASTER_REQUIRED")
        exact_expiry = require_exact_option_expiry(str(expiry))
        normalized_type = str(option_type or "").upper()
        if normalized_type not in {"PUT", "CALL"}:
            raise ValueError("TRACK2_OPTION_TYPE_INVALID")
        target_strike = Decimal(str(strike))
        matches = [
            identity for identity in self.option_master.list_contract_identities(exact_expiry)
            if str(getattr(identity, "instrument_family", "") or "").upper() == "STANDARD"
            and str(getattr(identity, "product_series", "") or "").upper() == "MONTHLY"
            and self._has_exact_expiry_provenance(identity)
            and str(getattr(identity, "option_type", "") or "").upper() == normalized_type
            and getattr(identity, "strike", None) is not None
            and Decimal(str(identity.strike)) == target_strike
            and str(getattr(identity, "shrn_iscd", "") or "").strip()
        ]
        if len(matches) != 1:
            raise ValueError("TRACK2_MONTHLY_LISTED_CONTRACT_NOT_UNIQUE")
        identity = matches[0]
        multiplier = getattr(identity, "contract_multiplier", None)
        if multiplier is None:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_REQUIRED")
        if Decimal(str(multiplier)) != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_MISMATCH")
        return identity

    def select(self, *, expiry: str, current_price: Decimal) -> Track2OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK2_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK2_OPTION_EXPIRY_REQUIRED")
        if current_price is None or Decimal(str(current_price)) <= 0:
            raise ValueError("TRACK2_UNDERLYING_PRICE_REQUIRED")

        identities = tuple(self.option_master.list_contract_identities(expiry))
        calls: dict[Decimal, Any] = {}
        puts: dict[Decimal, Any] = {}
        for identity in identities:
            if (
                str(getattr(identity, "instrument_family", "") or "").upper() != "STANDARD"
                or str(getattr(identity, "product_series", "") or "").upper() != "MONTHLY"
                or not self._has_exact_expiry_provenance(identity)
            ):
                continue
            option_type = str(getattr(identity, "option_type", "")).upper()
            strike = getattr(identity, "strike", None)
            if option_type not in {"CALL", "PUT"} or strike is None:
                continue
            strike = Decimal(str(strike))
            if strike <= 0 or not getattr(identity, "shrn_iscd", ""):
                continue
            (calls if option_type == "CALL" else puts)[strike] = identity

        listed_strikes = sorted(set(calls) & set(puts))
        if not listed_strikes:
            raise ValueError("TRACK2_LISTED_STRIKE_NOT_FOUND")
        underlying = Decimal(str(current_price))
        atm = min(listed_strikes, key=lambda strike: (abs(strike - underlying), strike))
        put = puts[atm]
        call = calls[atm]
        put_multiplier = getattr(put, "contract_multiplier", None)
        call_multiplier = getattr(call, "contract_multiplier", None)
        if put_multiplier is None or call_multiplier is None:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_REQUIRED")
        put_multiplier = Decimal(str(put_multiplier))
        call_multiplier = Decimal(str(call_multiplier))
        if put_multiplier <= 0 or call_multiplier <= 0:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_REQUIRED")
        if put_multiplier != call_multiplier:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_MISMATCH")
        return Track2OptionContractSelection(str(expiry).replace("-", "")[:8], atm, put, call)


__all__ = ("Track2OptionContractSelection", "Track2OptionContractSource")
