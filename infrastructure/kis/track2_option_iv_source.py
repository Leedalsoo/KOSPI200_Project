from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from contracts.track2_option_iv_source import Track2OptionIVObservation
from core.option.option_master import IOptionContractMaster


class KISTrack2OptionIVSource:
    """Authoritative CALL/PUT IV chain projected from KIS H0IOCNT0 events."""

    def __init__(self, option_master: IOptionContractMaster) -> None:
        self.option_master = option_master
        self._observations: dict[tuple[str, str, Decimal], Track2OptionIVObservation] = {}

    @staticmethod
    def _observed_at(raw: str, session_date: date) -> datetime:
        value = raw.strip()
        if len(value) == 6:
            parsed = datetime.strptime(value, "%H%M%S")
        elif len(value) == 9:
            parsed = datetime.strptime(value, "%H%M%S%f")
        else:
            raise ValueError("AUTHORITATIVE_OPTION_IV_OBSERVED_HOUR_INVALID")
        return datetime.combine(session_date, parsed.time())

    def update_observation(self, observation: KisIndexOptionMarketObservation, *, session_date: date) -> Track2OptionIVObservation:
        if observation.source != "KIS:H0IOCNT0":
            raise ValueError("AUTHORITATIVE_OPTION_IV_SOURCE_REQUIRED")
        iv = observation.implied_volatility
        if iv is None or not iv.is_finite() or iv <= 0:
            raise ValueError("AUTHORITATIVE_OPTION_IV_NOT_PRESENT")
        identity = self.option_master.get_contract_identity(observation.shrn_iscd)
        if identity is None or identity.option_type not in {"CALL", "PUT"} or identity.strike is None:
            raise ValueError("AUTHORITATIVE_OPTION_IV_IDENTITY_UNAVAILABLE")
        record = Track2OptionIVObservation(
            symbol=identity.shrn_iscd,
            expiry=identity.expiry,
            option_type=identity.option_type,
            strike=identity.strike,
            implied_volatility=iv,
            observed_at=self._observed_at(observation.observed_hour, session_date),
            source=observation.source,
        )
        key_expiry = record.expiry.replace("-", "")[:6]
        self._observations[(key_expiry, record.option_type, record.strike)] = record
        return record

    def get_iv(self, *, expiry: str, option_type: str, strike: Decimal) -> Decimal | None:
        key_expiry = str(expiry).replace("-", "")[:6]
        record = self._observations.get((key_expiry, str(option_type).upper(), Decimal(str(strike))))
        return record.implied_volatility if record is not None else None

    def get_observation(self, *, expiry: str, option_type: str, strike: Decimal) -> Track2OptionIVObservation | None:
        return self._observations.get((str(expiry), str(option_type).upper(), Decimal(str(strike))))
