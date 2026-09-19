from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from contracts.historical_market_ohlc import HistoricalDailyOHLC


class KRXDailyNormalizationError(ValueError):
    """Raised when KRX daily data cannot be proven safe for canonical use."""


class KRXDailyHistoricalNormalizer:
    """Normalize KRX daily rows using an injected authoritative identity source."""

    def __init__(self, *, option_master: Any, futures_master: Any) -> None:
        if option_master is None or not callable(getattr(option_master, "get_contract_identity", None)):
            raise KRXDailyNormalizationError("OPTION_MASTER_REQUIRED")
        if futures_master is None or not callable(getattr(futures_master, "get_contract_identity", None)):
            raise KRXDailyNormalizationError("FUTURES_MASTER_REQUIRED")
        self._option_master = option_master
        self._futures_master = futures_master

    @staticmethod
    def _date(raw: Any) -> date:
        value = str(raw or "").strip()
        if len(value) != 8 or not value.isdigit():
            raise KRXDailyNormalizationError("INVALID_BAS_DD")
        try:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except ValueError as exc:
            raise KRXDailyNormalizationError("INVALID_BAS_DD") from exc

    @staticmethod
    def _price(row: dict[str, Any], field: str) -> Decimal:
        raw = str(row.get(field, "")).strip()
        if not raw:
            raise KRXDailyNormalizationError("OHLC_PRICE_REQUIRED")
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise KRXDailyNormalizationError("OHLC_PRICE_INVALID") from exc
        if value <= 0:
            raise KRXDailyNormalizationError("OHLC_PRICE_INVALID")
        return value

    @classmethod
    def _ohlc(cls, row: dict[str, Any]) -> tuple[date, Decimal, Decimal, Decimal, Decimal]:
        trading_date = cls._date(row.get("BAS_DD"))
        opening = cls._price(row, "TDD_OPNPRC")
        high = cls._price(row, "TDD_HGPRC")
        low = cls._price(row, "TDD_LWPRC")
        close = cls._price(row, "TDD_CLSPRC")
        if high < max(opening, close) or low > min(opening, close):
            raise KRXDailyNormalizationError("OHLC_RANGE_INVALID")
        return trading_date, opening, high, low, close

    @staticmethod
    def _identity_code(row: dict[str, Any]) -> str:
        code = str(row.get("ISU_CD", "")).strip()
        if not code:
            raise KRXDailyNormalizationError("INSTRUMENT_CODE_REQUIRED")
        return code

    @staticmethod
    def _validate_option_identity(identity: Any) -> None:
        if identity is None or not identity.shrn_iscd or not identity.expiry:
            raise KRXDailyNormalizationError("OPTION_IDENTITY_REQUIRED")
        if identity.option_type not in {"CALL", "PUT"} or identity.strike is None or identity.strike <= 0:
            raise KRXDailyNormalizationError("OPTION_IDENTITY_INCOMPLETE")
        if identity.contract_multiplier is None or identity.contract_multiplier <= 0:
            raise KRXDailyNormalizationError("OPTION_MULTIPLIER_REQUIRED")

    @staticmethod
    def _validate_futures_identity(identity: Any) -> None:
        if identity is None or not identity.shrn_iscd:
            raise KRXDailyNormalizationError("FUTURES_IDENTITY_REQUIRED")
        if identity.contract_multiplier is None or identity.contract_multiplier <= 0:
            raise KRXDailyNormalizationError("FUTURES_MULTIPLIER_REQUIRED")

    def normalize_option_row(self, row: dict[str, Any]) -> HistoricalDailyOHLC:
        code = self._identity_code(row)
        identity = self._option_master.get_contract_identity(code)
        self._validate_option_identity(identity)
        trading_date, opening, high, low, close = self._ohlc(row)
        return HistoricalDailyOHLC(
            symbol=identity.shrn_iscd,
            trading_date=trading_date,
            open=opening,
            high=high,
            low=low,
            close=close,
            observed_at=datetime.combine(trading_date, time.min),
            source=f"KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD={code}",
        )

    def normalize_futures_row(self, row: dict[str, Any]) -> HistoricalDailyOHLC:
        code = self._identity_code(row)
        identity = self._futures_master.get_contract_identity(code)
        self._validate_futures_identity(identity)
        trading_date, opening, high, low, close = self._ohlc(row)
        return HistoricalDailyOHLC(
            symbol=identity.shrn_iscd,
            trading_date=trading_date,
            open=opening,
            high=high,
            low=low,
            close=close,
            observed_at=datetime.combine(trading_date, time.min),
            source=f"KRX_OPEN_API:fut_bydd_trd;KRX_ISU_CD={code}",
        )
