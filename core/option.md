폴더 페이지

[Child Page] black_scholes.py
## 목적
표준 Black-Scholes-Merton 유럽형 옵션 가격·Greeks의 순수 계산 함수다. 외부 source를 조회하거나 risk-free rate, DTE, option type을 추정하지 않는다.
## 산식 및 가정
    - 유럽형 옵션.
    - S, K, sigma, T, r, q는 각각 underlying price, strike, annualized volatility, time-to-expiry in years, continuously compounded risk-free rate, continuous dividend yield.
    - T와 r은 호출자가 authoritative source에서 공급한다.
    - option_type은 명시적인 CALL 또는 PUT만 허용한다.
    - theta는 연율(가격 단위/년)이며 일일 theta는 별도의 day-count convention이 확정된 뒤 변환한다.
    - 계산 자체는 업무적 attribution(수량·승수·KRW PnL)을 수행하지 않는다.
검증 참고: Cboe는 Delta/Gamma/Theta를 옵션 risk sensitivity의 핵심 지표로 설명한다. Black-Scholes 유럽형 Greeks의 폐형식은 https://book.derivative-securities.org/Chapter_BlackScholes.html 및 https://quantpie.co.uk/bsm_formula/bs_summary.php 의 식과 대조했다.
```python
from dataclasses import dataclass
from decimal import Decimal
from math import erf, exp, log, pi, sqrt
from typing import Literal

OptionType = Literal["CALL", "PUT"]

class BlackScholesInputError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class BlackScholesGreeks:
    price: Decimal
    delta: Decimal
    gamma: Decimal
    theta_annual: Decimal

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))

def _pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)

def calculate_black_scholes(*, underlying_price: Decimal, strike: Decimal, time_to_expiry_years: Decimal, volatility: Decimal, risk_free_rate: Decimal, dividend_yield: Decimal, option_type: OptionType) -> BlackScholesGreeks:
    if option_type not in {"CALL", "PUT"}:
        raise BlackScholesInputError("option_type must be CALL or PUT")
    if underlying_price <= 0 or strike <= 0:
        raise BlackScholesInputError("underlying_price and strike must be positive")
    if time_to_expiry_years <= 0:
        raise BlackScholesInputError("time_to_expiry_years must be positive")
    if volatility <= 0:
        raise BlackScholesInputError("volatility must be positive")

    S, K, T = float(underlying_price), float(strike), float(time_to_expiry_years)
    sigma, r, q = float(volatility), float(risk_free_rate), float(dividend_yield)
    sqrt_t = sqrt(T)
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount_r, discount_q = exp(-r * T), exp(-q * T)
    n1 = _pdf(d1)

    if option_type == "CALL":
        price = S * discount_q * _cdf(d1) - K * discount_r * _cdf(d2)
        delta = discount_q * _cdf(d1)
        theta = -discount_q * S * n1 * sigma / (2.0 * sqrt_t) - r * K * discount_r * _cdf(d2) + q * S * discount_q * _cdf(d1)
    else:
        price = K * discount_r * _cdf(-d2) - S * discount_q * _cdf(-d1)
        delta = -discount_q * _cdf(-d1)
        theta = -discount_q * S * n1 * sigma / (2.0 * sqrt_t) + r * K * discount_r * _cdf(-d2) - q * S * discount_q * _cdf(-d1)

    gamma = discount_q * n1 / (S * sigma * sqrt_t)
    return BlackScholesGreeks(Decimal(str(price)), Decimal(str(delta)), Decimal(str(gamma)), Decimal(str(theta)))
```
## 구현 경계
    - Track4OptionValuationInput의 risk_free_rate와 time_to_expiry_years를 이 함수가 생성하지 않는다.
    - KIS가 이미 authoritative Greeks를 공급하는 Track4 runtime에서는 이 계산기로 Greeks를 덮어쓰지 않는다.
    - Production fallback 승격에는 별도 Domain 승인과 source provenance가 필요하다.

[Child Page] option_master.py
```python
# -*- coding: utf-8 -*-
"""Option Contract Master & KIS contract identity registry.

Preserves the legacy expiry lookup while additively retaining authoritative
KIS short/standard-code identity metadata from one raw MST parse boundary.
Calendar behavior is supplied through the standard TradingCalendar contract.
"""
import io
import logging
import re
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from contracts.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)
KIS_FO_IDX_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"


class KisMasterSourceError(Exception):
    pass


class KisMasterDownloadError(KisMasterSourceError):
    pass


class KisMasterParseError(KisMasterSourceError):
    pass


@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: Optional[str]
    expiry: str
    option_type: Optional[str]
    strike: Optional[Decimal]
    info_type: Optional[str] = None


@dataclass(frozen=True)
class KisOptionMasterParseResult:
    legacy_contracts: Dict[str, str]
    identities: Dict[str, KisOptionContractIdentity]


KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": "CALL", "D": "CALL", "L": "CALL",
    "6": "PUT", "E": "PUT", "M": "PUT",
}
_OPTION_INFO_TYPES = {"5", "6", "D", "E", "L", "M", "N", "O", "P", "Q", "R", "S"}
_MONTH_PATTERN = re.compile(r"20\d{4}")
_WEEKLY_PATTERN = re.compile(r"(\d{2})(\d{2})W(\d)")


def _require_calendar(calendar: Optional[TradingCalendar]) -> TradingCalendar:
    if calendar is None:
        raise KisMasterParseError(
            "TradingCalendar injection is required; no production calendar source "
            "is owned by OptionContractMaster."
        )
    return calendar


def calculate_krx_monthly_option_expiry(
    year: int, month: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_date = date(year, month, first_thursday + 7)
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def calculate_krx_weekly_option_expiry(
    year: int, month: int, week_num: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_day = first_thursday + (week_num - 1) * 7
    max_days = (date(year, month + 1, 1) - timedelta(days=1)).day if month < 12 else 31
    target_date = date(year, month, min(target_day, max_days))
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def _is_option_record(prod_type: str, symbol: str, name: str) -> bool:
    return (
        prod_type in _OPTION_INFO_TYPES
        or symbol.startswith(("2", "3", "B", "C"))
        or " C " in name or " P " in name
        or "Call" in name or "Put" in name
    )


def _calculate_expiry(
    symbol: str, name: str, calendar: TradingCalendar
) -> Optional[str]:
    weekly_m = _WEEKLY_PATTERN.search(name) or _WEEKLY_PATTERN.search(symbol)
    if weekly_m:
        try:
            return calculate_krx_weekly_option_expiry(
                2000 + int(weekly_m.group(1)),
                int(weekly_m.group(2)),
                int(weekly_m.group(3)),
                calendar,
            )
        except Exception as exc:
            logger.debug("Weekly option parse note (%s): %s", name, exc)
    month_m = _MONTH_PATTERN.search(name)
    if month_m:
        try:
            ym = month_m.group(0)
            year, month = int(ym[:4]), int(ym[4:6])
            if 1 <= month <= 12:
                return calculate_krx_monthly_option_expiry(year, month, calendar)
        except Exception as exc:
            logger.debug("Monthly option parse note (%s): %s", name, exc)
    return None


def _parse_strike(raw_acpr: str) -> Optional[Decimal]:
    raw_acpr = raw_acpr.strip()
    if not raw_acpr:
        return None
    try:
        value = Decimal(raw_acpr)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def parse_kis_fo_idx_mst_result(
    raw_content: str, calendar: TradingCalendar
) -> KisOptionMasterParseResult:
    if not raw_content or not raw_content.strip():
        return KisOptionMasterParseResult({}, {})
    legacy: Dict[str, str] = {}
    identities: Dict[str, KisOptionContractIdentity] = {}

    for line in raw_content.splitlines():
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        prod_type, symbol, standard_code, name = parts[:4]
        if not _is_option_record(prod_type, symbol, name):
            continue
        expiry = _calculate_expiry(symbol, name, calendar)
        if not symbol or not expiry:
            continue

        legacy[symbol] = expiry
        if standard_code:
            legacy[standard_code] = expiry

        strike = _parse_strike(parts[5]) if len(parts) >= 6 else None
        identity = KisOptionContractIdentity(
            shrn_iscd=symbol,
            stnd_iscd=standard_code or None,
            expiry=expiry,
            option_type=KIS_INFO_TYPE_TO_OPTION_TYPE.get(prod_type),
            strike=strike,
            info_type=prod_type or None,
        )
        existing = identities.get(symbol)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting KIS identity for shrn_iscd '{symbol}'."
            )
        identities[symbol] = identity

    return KisOptionMasterParseResult(legacy, identities)


def parse_kis_fo_idx_mst(
    raw_content: str, calendar: TradingCalendar
) -> Dict[str, str]:
    return parse_kis_fo_idx_mst_result(raw_content, calendar).legacy_contracts


class KisOptionMasterLoader:
    @staticmethod
    def extract_raw_text_from_zip_bytes(zip_bytes: bytes) -> str:
        if not zip_bytes:
            raise KisMasterParseError(
                "Empty zip bytes provided for KIS master loading."
            )
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                names = archive.namelist()
                target = next(
                    (
                        name for name in names
                        if "fo_idx_code_mts" in name
                        or "fo_idx_code" in name
                        or "optcode" in name
                    ),
                    None,
                )
                target = target or (names[0] if names else None)
                if not target:
                    raise KisMasterParseError(
                        "No valid master file found in zip archive."
                    )
                return archive.read(target).decode("cp949", errors="ignore")
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterParseError(
                f"Failed to extract zip archive: {exc}"
            ) from exc

    @classmethod
    def parse_raw_content(
        cls, raw_text: str, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        result = parse_kis_fo_idx_mst_result(raw_text, calendar)
        if not result.legacy_contracts:
            raise KisMasterParseError("Master file parsed 0 contracts.")
        return result

    @classmethod
    def load_result_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        return cls.parse_raw_content(
            cls.extract_raw_text_from_zip_bytes(zip_bytes), calendar
        )

    @classmethod
    def load_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> Dict[str, str]:
        return cls.load_result_from_zip_bytes(
            zip_bytes, calendar
        ).legacy_contracts

    @classmethod
    def load_result_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> KisOptionMasterParseResult:
        cal = _require_calendar(calendar)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return cls.load_result_from_zip_bytes(response.read(), cal)
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterDownloadError(
                f"Failed to download KIS master from {url}: {exc}"
            ) from exc

    @classmethod
    def load_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> Dict[str, str]:
        return cls.load_result_from_url(
            url, timeout, calendar
        ).legacy_contracts


class IOptionContractMaster(ABC):
    @abstractmethod
    def get_expiry(self, symbol: str) -> Optional[str]:
        pass

    @abstractmethod
    def register_contract(self, symbol: str, expiry: str) -> None:
        pass

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return None

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        raise NotImplementedError(
            "This OptionContractMaster does not support identity registration."
        )

    @property
    def is_loaded(self) -> bool:
        return self.total_contracts > 0

    @property
    @abstractmethod
    def total_contracts(self) -> int:
        pass

    @property
    def last_error(self) -> Optional[str]:
        return None


class _IdentityOptionContractMaster(IOptionContractMaster):
    def _init_identity_registry(self) -> None:
        self._contract_identities: Dict[
            str, KisOptionContractIdentity
        ] = {}

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return self._contract_identities.get(
            shrn_iscd.strip()
        ) if shrn_iscd else None

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        key = identity.shrn_iscd.strip()
        if not key:
            raise KisMasterParseError(
                "KIS identity requires non-empty shrn_iscd."
            )
        existing = self._contract_identities.get(key)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting registered KIS identity for shrn_iscd '{key}'."
            )
        self._contract_identities[key] = identity
        self.register_contract(key, identity.expiry)
        if identity.stnd_iscd:
            self.register_contract(identity.stnd_iscd, identity.expiry)

    def _apply_parse_result(self, result: KisOptionMasterParseResult) -> None:
        self._contracts.update(result.legacy_contracts)
        for identity in result.identities.values():
            self.register_contract_identity(identity)


class InMemoryOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        auto_load_kis_source: bool = False,
        calendar: Optional[TradingCalendar] = None,
    ) -> None:
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load_kis_source and not self._contracts:
            self.load_from_kis_source(calendar=calendar)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(
        self,
        calendar: Optional[TradingCalendar] = None,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[InMemoryOptionContractMaster] KIS source load note: %s", exc
            )
            return 0

    def load_from_raw_mst_content(
        self, raw_text: str, calendar: TradingCalendar
    ) -> int:
        result = KisOptionMasterLoader.parse_raw_content(raw_text, calendar)
        self._apply_parse_result(result)
        self._last_error = None
        return len(result.legacy_contracts)

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


class KisProductionOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        calendar: Optional[TradingCalendar] = None,
        auto_load: bool = True,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> None:
        self.calendar = _require_calendar(calendar)
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load and not self._contracts:
            self.load_from_kis_source(url=url)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(self, url: str = KIS_FO_IDX_MASTER_URL) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[KisProductionOptionContractMaster] Source download note: %s",
                exc,
            )
            return 0

    def load_from_raw_mst_content(self, raw_text: str) -> int:
        try:
            result = KisOptionMasterLoader.parse_raw_content(
                raw_text, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def load_from_zip_bytes(self, zip_bytes: bytes) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_zip_bytes(
                zip_bytes, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


def create_default_option_master(
    calendar: Optional[TradingCalendar] = None,
    contracts: Optional[Dict[str, str]] = None,
    auto_load_kis: bool = True,
) -> IOptionContractMaster:
    return KisProductionOptionContractMaster(
        contracts=contracts,
        calendar=calendar,
        auto_load=auto_load_kis,
    )

```

[Child Page] kis_option_master_identity_parser_implementation.md
## 구현 대상
KIS 공식 fo_idx_code_mts.mst를 현재 shared/contracts/option_master.py의 legacy expiry lookup과 충돌 없이 확장한다.
## 현재 원격 구현의 핵심
현재 parse_kis_fo_idx_mst()는 KIS Master 한 줄을 |로 분리하고 다음 4개 필드를 사용한다.
    - parts[0] → prod_type
    - parts[1] → symbol (= KIS shrn_iscd 후보)
    - parts[2] → standard_code (= KIS stnd_iscd)
    - parts[3] → name
옵션 여부를 prod_type, symbol prefix, name으로 확인한 뒤 name/symbol의 월물·위클리 패턴으로 expiry를 계산한다. 결과는 현재 {symbol: expiry, standard_code: expiry} 형태의 Dict[str, str]이다.
## 최소 변경 설계
현재 legacy parser를 바로 Dict[str, KisOptionContractIdentity]로 변경하지 않는다. 다음 3층으로 분리한다.
```plain text
raw MST line
    ↓
_parse_kis_master_record()
    ↓
KisOptionContractIdentity
    ↓
legacy expiry map compatibility wrapper
```
### 1. Raw record parser
공식 9-column 순서를 기준으로 읽는다.
    1. prod_type / info_type
    1. shrn_iscd
    1. stnd_iscd
    1. kor_name
    1. atm_cls_code
    1. acpr
    1. mmsc_cls_code
    1. unas_shrn_iscd
    1. unas_kor_name
중요: parts[4]를 expiry로 해석하지 않는다.
### 2. Identity 변환
옵션에 대해 다음을 만든다.
    - shrn_iscd: raw parts[1]
    - stnd_iscd: raw parts[2] 또는 빈 값이면 None
    - info_type: raw parts[0]
    - option_type: 명시적 KIS mapping 결과
    - strike: acpr 검증 결과
    - expiry: 기존 이름/심볼 기반 계산 결과
instrument_id는 이 계층에서 만들지 않는다. 현재 KisOptionContractIdentity는 KIS Master identity 후보이지 Standard OptionInstrumentIdentity 그 자체가 아니다.
### 3. Legacy compatibility
기존 parse_kis_fo_idx_mst()의 외부 반환형과 기존 호출을 유지한다.
```plain text
symbol(shrn_iscd)     → expiry
standard_code(stnd_iscd) → expiry
```
동시에 새 identity parser/loader 경로에서는
```plain text
shrn_iscd → KisOptionContractIdentity
```
registry를 별도로 유지한다.
## info_type 매핑
허용된 명시적 변환만 사용한다.
```python
5/D/L → CanonicalOptionType.CALL
6/E/M → CanonicalOptionType.PUT
```
미지원 값은 Call/Put으로 추론하지 않는다. 옵션 identity를 생성해야 하는 경로에서는 매핑 실패를 명시적으로 기록하고 해당 identity를 주문 경계까지 전달하지 않는다.
## strike 검증
acpr를 무조건 float 변환하지 않는다.
권장:
    1. trim
    1. 빈 값이면 None
    1. Decimal 변환 실패면 None/parse failure
    1. <= 0이면 유효 strike로 사용하지 않음
    1. 정상 값만 Decimal로 보존
문자열 포맷의 정확한 소수점/공백 규칙은 실제 MST 샘플 대조 후 고정한다.
## expiry 보존
Master의 9개 공식 컬럼에 독립 expiry 컬럼은 없다. 따라서 기존 프로젝트의:
    - 일반 월물: 종목명에서 20YYYYMM 패턴
    - 위클리: YYMMWn 패턴
    - KRX calendar 기반 휴장일 보정
을 그대로 사용한다.
Identity 생성 시 계산된 expiry를 기록하되, expiry 계산 로직 자체는 이번 변경의 대상이 아니다.
## registry API
InMemoryOptionContractMaster와 KisProductionOptionContractMaster에 다음을 additive하게 추가한다.
```python
def get_contract_identity(self, shrn_iscd: str) -> KisOptionContractIdentity | None: ...
def register_contract_identity(self, identity: KisOptionContractIdentity) -> None: ...
```
기존:
```python
get_expiry(symbol)
register_contract(symbol, expiry)
```
은 그대로 유지한다.
새 Master load에서는 identity를 먼저 registry에 넣고, 동일 identity의 shrn_iscd 및 필요 시 stnd_iscd를 legacy expiry alias로 등록한다.
## Standard Identity와의 경계
KisOptionContractIdentity의 shrn_iscd가 곧바로 Standard instrument_id가 되는 것은 아니다.
향후:
```plain text
KIS Master Identity
    ↓ verified contract selection / resolver
Standard OptionInstrumentIdentity
    ├─ instrument_id  ← authoritative source 필요
    ├─ symbol
    ├─ expiry
    ├─ option_type
    └─ strike
```
instrument_id가 아직 authoritative하게 공급되지 않으면 Standard identity를 완성하지 않고 fail-closed한다.
## 구현 금지사항
    - standard_code → SHTN_PDNO 변환 금지
    - stnd_iscd → shrn_iscd 추정 금지
    - KOSPI200을 short code로 사용 금지
    - symbol + expiry + strike + option_type로 instrument_id 생성 금지
    - info_type 외의 action/track/tag/side로 option_type 추정 금지
    - parts[4]를 expiry로 재해석 금지
    - 기존 expiry 계산을 임의로 변경 금지
## 상태
이 문서는 실제 원격 코드에 적용하기 전의 최소 구현 계약이다. 현재 원격 Exp_Detail_1은 읽기 전용으로 유지하며, 적용 시에도 legacy parser/API의 기능 보존을 우선한다.
## No.147 반영 — Raw/Decimal 안전 규칙
    - KIS Master 공식 9-column 순서에 따라 shrn_iscd=parts[1], stnd_iscd=parts[2], info_type=parts[0], acpr=parts[5]로 해석한다.
    - 각 raw field는 strip() 후 의미를 보존한다.
    - acpr는 비어 있지 않고 Decimal(raw_acpr) 변환에 성공하며 결과가 0보다 클 때만 strike로 승격한다.
    - 실제 원문으로 확인되지 않은 소수점 scale 보정은 하지 않는다.
    - 5/D/L → CALL, 6/E/M → PUT은 KIS-specific adapter에서만 명시적으로 적용한다.
    - 기존 expiry 계산 및 legacy get_expiry()/register_contract() 의미는 유지한다.
    - 실제 최신 MST raw sample에서 확인되지 않은 acpr 암묵 scale은 확정하지 않는다.
## No.147 반영
Raw MST의 | 구분/field strip() 경계를 유지하고, acpr는 검증된 Decimal 값만 strike로 승격한다. 소수점 위치를 추정하지 않으며 기존 expiry 계산은 변경하지 않는다.
## No.148 준비 — Identity Parser/Registry additive 구현 경계
다음 구현은 기존 parse_kis_fo_idx_mst()와 legacy expiry map을 대체하지 않고, 별도의 Identity parser가 같은 raw MST를 읽어 KisOptionContractIdentity를 생성한 뒤 Registry에 등록하는 additive 경로로 설계한다.
## 구현 초안
```python
@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: str | None
    expiry: str
    option_type: str | None
    strike: Decimal | None
    info_type: str | None = None
```
Identity parser는 raw_content를 순회하면서 최소 6개 field가 있는 옵션 레코드만 대상으로 하고, info_type은 명시된 Call/Put 코드일 때만 CALL/PUT으로 변환한다. acpr는 검증된 Decimal만 사용한다. expiry는 기존 parser가 계산한 결과를 재사용하는 별도 compatibility helper를 통해 공급하며, expiry 계산식을 중복 구현하지 않는다.
Registry는 _contract_identities: Dict[str, KisOptionContractIdentity]를 두고 1차 key를 shrn_iscd로 한다. register_contract_identity()는 빈 단축코드 또는 동일 key의 의미가 다른 identity가 들어오면 fail-closed한다. get_contract_identity()는 trim된 shrn_iscd로 조회한다.
중요: stnd_iscd는 별도 보존 필드이며 SHTN_PDNO로 사용하지 않는다. shrn_iscd 역시 현재 Canonical symbol을 자동 변경하지 않는다. Standard instrument_id도 생성하지 않는다.
## 구현 전 보류
현재 단계에서는 원격 Exp_Detail_1에 parser/registry 코드를 직접 반영하지 않는다. 이유는 실제 최신 MST raw sample의 acpr 표현 및 기존 expiry 계산 결과와의 1:1 결합을 코드로 검증할 수 없는 상태이기 때문이다. 먼저 additive parser의 입력/출력 및 충돌 정책을 문서로 고정한 후 원격 적용 여부를 결정한다.
## No.148 반영 — 실제 option_master.py 구조 대조 결과
    - 원격 Exp_Detail_1/shared/contracts/option_master.py를 다시 대조한 결과, 현재 구현에는 KisOptionContractIdentity 또는 Identity Registry가 아직 존재하지 않는다.
    - 현재 parse_kis_fo_idx_mst()는 parts[0]~parts[3]만 직접 사용하며 반환형은 Dict[str, str]이다.
    - 현재 KisOptionMasterLoader.load_from_zip_bytes()와 load_from_url()도 기존 parser의 expiry map을 그대로 반환한다.
    - InMemoryOptionContractMaster와 KisProductionOptionContractMaster 모두 _contracts: Dict[str, str]만 보유하며 get_expiry() / register_contract()를 통해 legacy expiry map을 제공한다.
    - 따라서 No.148에서 확정한 Identity Registry를 기존 _contracts에 억지로 혼합하지 않고 별도 _contract_identities 저장소로 additive하게 두는 것이 실제 구조와 가장 안전하게 맞는다.
    - 두 Master 구현체에 동일한 Identity 조회/등록 API를 제공하려면 공통 IOptionContractMaster 계약 확장이 우선 검토 대상이다. 다만 기존 구현체의 외부 동작을 깨뜨리지 않도록 abstract method로 즉시 강제할지는 별도 판단이 필요하다.
    - 새 Identity loader는 기존 parse_kis_fo_idx_mst()를 교체하지 않고 별도 parser/helper로 두는 방향이 현재 코드 구조와 일치한다.
    - 기존 load_from_kis_source() 및 load_from_raw_mst_content()는 현재 expiry map만 갱신하므로, Identity 동시 등록을 적용할 경우 이 두 경로와 ZIP loader의 책임을 중복시키지 않는 공통 additive load helper가 필요하다.
    - 원격 브랜치에는 코드를 반영하지 않았다. 터미널 테스트도 수행하지 않았다.
### No.148 결론
현재 원격 구현은 No.148 구현계약을 수용할 수 있는 구조이지만, 실제 적용 시에는 기존 expiry map과 새 Identity registry를 병렬 유지하고, Master loading 과정에서 동일 raw MST를 중복 다운로드하지 않도록 parser/load 책임을 분리해야 한다. 또한 IOptionContractMaster의 기존 호출 계약을 보존하면서 Identity API를 추가하는 구체적인 인터페이스 확장 방식이 다음 작업의 핵심이다.
## 구현 상태 갱신 — No.152
No.151에서 확정한 공통 Raw Parse 경계를 실제 OptionProject 코드로 구현했다.
    - 실제 코드: OptionProject/core/oms/option_master.py
    - 테스트: OptionProject/core/oms/test_option_master.py
    - 한 번의 raw MST 순회에서 legacy expiry map과 identity registry를 함께 생성
    - 기존 parse_kis_fo_idx_mst() -> Dict[str, str]는 compatibility wrapper로 유지
    - _contracts와 _contract_identities 병렬 유지
    - IOptionContractMaster 기존 abstract API 유지, identity API는 concrete fallback
    - duplicate identity 충돌은 fail-closed
    - malformed acpr는 strike를 추정하지 않고 None
    - 실제 pytest 실행 환경 검증은 다음 단계로 남김
## No.153 검증 결과 보강
### 실제 import/package 정합성 점검
OptionProject/core/oms/option_master.py는 현재 from shared.calendar.krx_calendar import KrxTradingCalendar를 사용한다.
그러나 현재 OptionProject 최상위 구조에는 shared/ 작업공간이 존재하지 않고, core가 외부 Reference/Legacy 경로를 직접 import하지 않는 Architecture Lint 원칙도 존재한다. 따라서 현재 파일은 독립 OptionProject Python workspace로 materialize할 경우 import 단계에서 실패할 가능성이 높은 상태다.
### 회귀 보존 대조
원격 Exp_Detail_1/shared/contracts/option_master.py와 대조한 결과 기존 public expiry API와 loader API는 유지되어 있다. Identity 확장은 additive이며 기존 만기조회 호출 경로를 제거하지 않았다.
### 테스트 구조 점검
test_option_master.py의 core.oms... import 방식은 현재 프로젝트의 테스트 관례와 일치한다. 다만 OptionProject 자체가 물리 Python workspace로 실행될 때 shared.calendar...가 없으므로 pytest 이전에 module import가 막히는 구조적 선행 문제가 확인됐다.
### 결론
API 회귀 대조, 테스트 import 형태 대조, Git Reference 구조 대조는 완료했다. 실제 pytest 실행은 Calendar 구현 소유권/패키지 경로가 미정이므로 보류한다.
다음 구현 단계에서는 원격 Reference의 Calendar 기능을 무단 복제하지 않고 OptionProject Architecture에 맞는 Calendar Contract/Adapter 주입 경계를 먼저 확정한 뒤 option_master.py의 shared.calendar 직접 의존성을 제거해야 한다.
## No.154 구현 반영 — Calendar Contract 명시 주입 경계
    - OptionProject/contracts/trading_calendar.py에 최소 TradingCalendar Protocol을 생성했다.
    - OptionProject/core/oms/option_master.py에서 shared.calendar.krx_calendar 직접 import를 제거했다.
    - OptionContractMaster가 실제로 사용하는 is_trading_day()와 prev_trading_day()만 표준 Contract로 소비하도록 변경했다.
    - Core/OMS 내부에서 기본 KrxTradingCalendar()를 생성하지 않는다. Production Calendar 구현과 source 선택 책임은 Core 밖으로 유지한다.
    - raw MST parser와 loader의 만기 계산 경로는 Calendar를 명시적으로 주입받는다.
    - 기존 legacy expiry map과 Identity Registry의 additive 병렬 구조는 유지했다.
    - test_option_master.py에는 deterministic FakeTradingCalendar를 주입해 Calendar 구현과 parser 검증 책임을 분리했다.
    - 원격 Git Exp_Detail_1은 읽기/대조만 수행하는 기준을 유지하며 수정하지 않았다.
### 검증 경계
현재 Notion 작업공간은 실제 파일시스템 터미널 pytest 실행 환경이 아니므로 실제 pytest 실행 PASS는 확정하지 않는다. 이번 단계는 독립 import 차단 원인을 제거하고, 실행 가능한 테스트 주입 경계를 코드 구조로 확정한 단계다.
### 다음 작업 준비
다음 단계에서는 OptionProject 전체 코드 페이지를 실제 Python workspace 기준으로 materialize할 수 있는 범위를 확인하고, test_option_master.py를 포함한 targeted pytest 실행 가능 여부를 검증한다. 실제 실행이 가능할 경우에만 PASS/FAIL을 판정하고, Calendar production source 미검증 상태는 별도로 BLOCKED로 유지한다.
## No.156 정합성 점검 결과 — 기능 보존 회귀 위험
원격 Exp_Detail_1/shared/contracts/option_master.py와 현재 OptionProject 구현을 파일 단위로 재대조했다.
    - legacy get_expiry() / register_contract() 및 loader API는 유지됐다.
    - Identity Registry 추가는 additive 구조다.
    - 그러나 원격 구현은 calendar=None일 때 내부 KrxTradingCalendar()를 생성하여 기존 호출자가 Calendar를 전달하지 않아도 동작한다.
    - 현재 OptionProject는 Architecture 규칙에 따라 Core가 Production Calendar 구현을 소유하지 않도록 명시 주입으로 변경했고, 그 결과 parse_kis_fo_idx_mst, expiry 계산 함수, KisProductionOptionContractMaster, create_default_option_master의 무인자 기존 호출 경로가 즉시 동일하게 동작하지 않는다.
따라서 shared.calendar 직접 의존 제거 자체는 Architecture 적합성이지만, 기존 auto-load/production 생성 기능까지 제거하거나 사실상 필수 인자로 변경해서는 안 된다. 다음 단계에서는 Core 내부 기본 구현 생성 없이 Application/Environment 조립 계층이 Production TradingCalendar를 주입하는 경로를 마련하여 기존 무인자 public factory 기능과 새 의존성 경계를 동시에 보존해야 한다.
현재 이 회귀 위험은 코드 수준 확인 결과이며 실제 pytest PASS/FAIL은 실행환경 부재로 판정하지 않는다.
## No.157 구현 — Production TradingCalendar 조립 위치 및 기존 Auto-load 호환 경계 확정
### 결론
No.156의 다음 단계에 따라 OptionProject의 현재 계층을 확인했다.
    - core/oms/option_master.py는 contracts.trading_calendar.TradingCalendar만 소비한다.
    - application/environment_hub/factory.py는 이미 실제 Environment 구성요소를 외부 builder로 주입받는 composition 경계를 사용한다.
    - 따라서 Production Calendar의 concrete 구현 소유·선택·생성 책임은 Core가 아니라 Application composition root에 두는 것이 현재 구조와 일치한다.
### 기존 기능 보존 방식
Core의 create_default_option_master() 자체에 다시 KrxTradingCalendar()를 import하면 No.154의 의존성 경계를 되돌리게 된다.
따라서 호환 경계는 다음처럼 분리한다.
```plain text
Legacy-compatible application factory
    ↓ owns/creates Production TradingCalendar
create_default_option_master(calendar=calendar)
    ↓
KisProductionOptionContractMaster
    ↓ consumes contract only
TradingCalendar Protocol
```
즉 기존의 “Production 기본 조립” 목적은 Application factory가 담당하고, Core의 low-level parser/expiry 계산은 계속 명시 주입을 유지한다.
### Production Calendar source 상태
과거 Reference에는 shared/calendar/krx_calendar.py의 최소 Calendar engine이 존재했지만 실제 운영 휴장일 source는 별도 BLOCKED였고, KIS 실제 응답 교차검증도 FAIL/BLOCKED 이력이 있다.
따라서 이번 단계에서:
    - 원격 Calendar 구현을 Core로 복사하지 않음
    - 휴장일 목록을 임의 하드코딩하지 않음
    - weekend-only Calendar를 Production 대체품으로 만들지 않음
    - 검증되지 않은 Calendar source를 PASS로 선언하지 않음
### 실제 코드 수정 범위
이번 단계는 조립 위치와 책임 경계 확정 단계다.
Production Calendar concrete source 자체가 아직 OptionProject에서 authoritative하게 확정되지 않았으므로, 가짜 Production 구현을 생성하여 기존 무인자 호출을 억지로 복구하지 않았다.
대신 다음 구현 방향을 고정한다.
    1. contracts/trading_calendar.py는 Contract 유지
    1. core/oms/option_master.py는 concrete Calendar import 금지 유지
    1. application/에 Production composition factory를 두고 Calendar Provider/Builder를 소유
    1. 기존 무인자 auto-load 호환이 필요한 최종 public entrypoint는 Application factory에서 제공
    1. Core의 raw parser 직접 호출은 Calendar를 명시 주입
    1. authoritative Production Calendar source가 확정될 때에만 Application composition에 실제 구현 연결
### 판정
    - Core → Contract 의존 경계: PASS
    - Core의 concrete Calendar 직접 생성 금지: PASS
    - 기존 Production 조립 책임의 올바른 위치 확정: PASS
    - 기존 무인자 Core factory를 동일 시그니처로 즉시 복구: BLOCKED (authoritative Production Calendar source 미확정)
    - 원격 Git 수정: 없음
    - 실제 pytest: 실행환경 미확보로 미실행
### 다음 단계
No.158에서는 현재 Reference와 OptionProject의 기존 무인자 public 호출이 실제 어느 Runtime/Application entrypoint에서 사용되는지 추적한다.
그 결과에 따라:
    - Core-level legacy API 자체를 유지해야 하는지
    - Application-level compatibility entrypoint로 충분한지
를 실제 호출 증거로 판정한다.
호출 증거 없이 무인자 API를 추측 복구하지 않으며, authoritative Calendar source 미확정 상태도 그대로 BLOCKED로 유지한다.
## No.158 구현 — 기존 무인자 Public 호출 실제 경로 추적 및 호환 필요 범위 판정
### 조사 기준
No.157의 다음 단계에 따라 원격 Git Exp_Detail_1 최신 HEAD를 다시 확인했다.
    - 최신 HEAD: 51c57c1f88035523db9491fa56bbc52bcad9b20f
    - 최신 commit: fix(calendar): define real trading calendar source
### 실제 Reference Runtime 호출 증거
최신 원격 option_program/runtime/program_runtime.py의 기본 Runtime 생성 경로는 다음과 같다.
```plain text
OptionProgramRuntime()
  ├─ calendar 미주입
  │    → create_default_krx_calendar(auto_load_kis=True)
  └─ option_master 미주입
       → create_default_option_master(
             calendar=self.calendar,
             auto_load_kis=True
         )
```
즉 실제 Production Runtime은 이미 OptionContractMaster에 Calendar를 명시 전달한다.
따라서 현재 확인된 Reference Runtime 증거상:
    - create_default_option_master()를 Core에서 반드시 무인자로 지원해야 한다는 호출 증거는 없음
    - Production 기본 Calendar 생성 책임은 Runtime/Application composition에 존재
    - Core Master는 TradingCalendar를 명시 주입받는 현재 OptionProject 경계가 Reference 최신 Runtime과 양립 가능
### 중요한 최신 Reference 변경 확인
No.157 작성 당시의 “authoritative Production Calendar source 미확정” 상태는 최신 원격 HEAD와 일치하지 않게 되었다.
최신 Reference에는:
    - KisProductionHolidayProvider
    - KIS 공식 chk-holiday TR (CTCA0903R)
    - create_default_krx_calendar()
    - Runtime 기본 생성 시 Production Calendar auto-load
가 실제 구현되어 있다.
따라서 No.157의 BLOCKED 판단은 당시 확인 기준의 기록으로 유지하되, 현재 다음 작업에서는 최신 Reference를 기준으로 재검토해야 한다.
### OptionProject 호출 범위 판정
현재 OptionProject core/oms/option_master.py는:
    - create_default_option_master(calendar=...) 형태의 explicit DI를 수용
    - Core 내부 concrete Calendar 생성 없음
    - Parser/Expiry 계산의 Calendar Contract 소비 유지
따라서 Core-level legacy no-argument API 복구는 현재 증거 기준 필수 작업이 아니다.
대신 기능 보존을 위해 필요한 것은:
    1. 최신 Reference의 Production Calendar source 구현을 검증
    1. KIS 인증/HTTP 의존을 Core 밖에 유지
    1. Application/Runtime composition에서 Calendar 생성
    1. 생성된 Calendar를 create_default_option_master(calendar=...)에 주입
이다.
### 판정
    - 실제 Reference Runtime의 OptionMaster 호출 경로 추적: PASS
    - Runtime이 Calendar를 명시 주입한다는 증거 확인: PASS
    - Core-level 무인자 factory 복구 필요성: 현재 증거상 NOT REQUIRED
    - No.157의 Calendar source BLOCKED 상태 최신성: STALE → 재검토 필요
    - 원격 Git 수정: 없음
    - OptionProject 코드 임의 수정: 없음
### 다음 단계
No.159에서는 최신 Reference HEAD 51c57c1의 Production Calendar 구현을 상세 대조하여:
    - KIS Holiday Provider의 실제 책임
    - 인증 의존 위치
    - strict/failure semantics
    - Application/Infrastructure 이식 위치
를 확정한다.
그 후에만 OptionProject의 기존 “Production Calendar source BLOCKED” 문서를 갱신하고 실제 Application composition 코드를 구현한다.
## No.159 구현 — 최신 Reference Production TradingCalendar 책임·실패 의미·이식 위치 확정
### 기준
직전 No.158의 다음 단계에 따라 최신 Reference Exp_Detail_1 HEAD 51c57c1f와 Q&A-383의 구현 근거를 대조했다.
### 최신 Reference 구현 책임
shared/calendar/krx_calendar.py의 Production Calendar 구현은 다음 책임으로 분리되어 있다.
    - KisProductionHolidayProvider: KIS 공식 국내휴장일조회 API 호출 및 휴장일 데이터 공급
    - 공식 endpoint: /uapi/domestic-stock/v1/quotations/chk-holiday
    - TR ID: CTCA0903R
    - 인증: 기존 KISAuthManager를 통해 OAuth/인증 헤더 획득
    - create_default_krx_calendar(): Provider를 조립하여 KrxTradingCalendar 생성
    - Runtime: OptionProgramRuntime()에서 Calendar를 생성한 뒤 OptionMaster에 명시 주입
### 실패 의미 및 strict 경계
Reference의 핵심 안전 규칙도 확인했다.
    1. KIS API 오류를 빈 휴장일 집합의 정상 성공으로 은폐하지 않는다.
    1. Provider는 실패 원인을 last_error에 보존한다.
    1. strict_mode=True이고 source가 로드되지 않았으면 KisHolidayUnavailableError로 fail-closed한다.
    1. 명시적 테스트용 Calendar DI는 Runtime에서도 유지된다.
다만 실제 KisProductionHolidayProvider.is_loaded는 휴장일 1건 이상 로드된 경우를 성공으로 판단하므로, “해당 조회 구간에 휴장일이 없는 정상 응답”과 “source 미로드”를 장기적으로 구분해야 하는 개선 가능성은 존재한다. 이번 단계에서는 Reference 기능을 임의 변경하지 않는다.
### OptionProject 이식 위치 판정
No.006의 Core/Environment 분리 원칙과 No.154~158의 DI 경계를 함께 적용하면 다음 구조가 적합하다.
```plain text
Application / Infrastructure
    ├─ KIS Auth Adapter
    ├─ KIS Holiday Provider
    └─ Production Calendar Factory
              ↓
        TradingCalendar Contract
              ↓
        Core OptionContractMaster
```
따라서:
    - core/oms에 HTTP/KIS 인증 코드 이식 금지
    - contracts/trading_calendar.py는 유지
    - KIS API Provider는 Infrastructure 책임
    - Production Calendar 생성은 Application composition 책임
    - Core Master에는 생성된 Calendar를 명시 주입
### 현재 실제 구현 상태
이번 단계는 구조·책임 확정 및 Reference 대조 단계다.
    - 원격 Git 수정: 없음
    - OptionProject 코드 수정: 아직 없음
    - 이유: OptionProject에 KIS 인증 Adapter의 기존 표준 경로와 Application composition의 실제 public entrypoint를 먼저 확인하지 않은 상태에서 HTTP 구현을 임의 생성하지 않기 위함
### 결론
No.157의 “authoritative Production Calendar source 미확정” BLOCKED 상태는 최신 Reference 기준으로 해소되었다.
OptionProject에서 다음 실제 구현 대상은:
    1. Application/Infrastructure의 KIS 인증 기존 경계 조사
    1. KIS Holiday Provider 배치 위치 확정
    1. Production Calendar Factory 구현
    1. Factory → create_default_option_master(calendar=...) 실제 연결
    1. strict/failure semantics 테스트 가능한 경계 구축
이다.
### 다음 단계
No.160에서는 OptionProject 내부의 현재:
    - Application composition root
    - KIS 인증/HTTP Adapter
    - Runtime public entrypoint
를 전수 확인하여 Production Calendar Provider/Factory를 새로 구현할 정확한 위치와 재사용 가능한 인증 의존성을 확정한다.
호출 경로 확인 없이 새로운 KIS 인증 구현을 중복 생성하지 않는다.