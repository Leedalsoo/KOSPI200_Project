from __future__ import annotations

from datetime import date

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from contracts.track9_iv_timeseries import Track9IVObservation, Track9IVTimeSeriesSource
from core.option.option_master import IOptionContractMaster
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource


class KISTrack2OptionIVObservationSink:
    """Fan out authoritative H0IOCNT0 observations to Track2 and Track9."""

    def __init__(
        self,
        *,
        option_master: IOptionContractMaster,
        iv_source: KISTrack2OptionIVSource,
        session_date: date | None = None,
        history_source: Track9IVTimeSeriesSource | None = None,
    ) -> None:
        self.option_master = option_master
        self.iv_source = iv_source
        self.session_date = session_date
        self.history_source = history_source

    def update(self, observation: KisIndexOptionMarketObservation, *, session_date: date) -> None:
        if self.option_master.get_contract_identity(observation.shrn_iscd) is None:
            raise ValueError("AUTHORITATIVE_OPTION_IV_IDENTITY_UNAVAILABLE")
        record = self.iv_source.update_observation(observation, session_date=session_date)
        if self.history_source is not None:
            self.history_source.append(
                Track9IVObservation(
                    symbol=record.symbol,
                    expiry=record.expiry,
                    option_type=record.option_type,
                    strike=record.strike,
                    implied_volatility=record.implied_volatility,
                    observed_at=record.observed_at,
                    source=record.source,
                )
            )

    def on_observation(self, observation: KisIndexOptionMarketObservation) -> None:
        if self.session_date is None:
            raise RuntimeError("TRACK2_OPTION_IV_SESSION_DATE_REQUIRED")
        self.update(observation, session_date=self.session_date)
