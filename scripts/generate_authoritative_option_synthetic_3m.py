from __future__ import annotations

import argparse
import calendar as month_calendar
import hashlib
import json
import math
import random
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from contracts.option_expiry import normalize_option_expiry
from core.option.option_master import calculate_krx_monthly_option_expiry, calculate_krx_weekly_option_expiry

SCHEMA = "reference-canonical-market-tick-v1"
RULES_VERSION = "project200-synthetic-3m-v1"
PATTERNS = ("trend_up", "trend_down", "mean_revert", "high_volatility", "low_volatility", "shock")
BAR_INTERVAL_MINUTES = 5
SESSION_OPEN = time(8, 45)
SESSION_CLOSE = time(15, 45)
LAST_TRADING_CLOSE = time(15, 20)
HORIZON_MONTHS = 3
CONTRACTS_PER_BAR = 10
MULTIPLIER = 250000.0


class Calendar:
    def __init__(self, holidays: set[date]):
        self.holidays = holidays

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def prev_trading_day(self, value: date) -> date:
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current


def add_calendar_months(value: date, months: int) -> date:
    """Add calendar months, clamping the day when the target month is shorter."""
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return date(year, month, min(value.day, month_calendar.monthrange(year, month)[1]))


def trading_days_between(calendar: Calendar, start: date, end_exclusive: date) -> list[date]:
    days = []
    current = start
    while current < end_exclusive:
        if calendar.is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def session_bar_count(day: date, monthly_last_trading_day: bool) -> int:
    close = LAST_TRADING_CLOSE if monthly_last_trading_day else SESSION_CLOSE
    minutes = int((datetime.combine(day, close) - datetime.combine(day, SESSION_OPEN)).total_seconds() // 60)
    if minutes <= 0 or minutes % BAR_INTERVAL_MINUTES:
        raise RuntimeError(f"INVALID_KRX_SESSION_WINDOW:{day}:{SESSION_OPEN}:{close}")
    return minutes // BAR_INTERVAL_MINUTES


def option_tick_size(price: float) -> Decimal:
    return Decimal("0.05") if Decimal(str(price)) >= Decimal("10") else Decimal("0.01")


def round_option_price(price: float) -> float:
    raw = max(Decimal("0.01"), Decimal(str(price)))
    step = option_tick_size(float(raw))
    rounded = (raw / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    if rounded >= Decimal("10"):
        rounded = (raw / Decimal("0.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("0.05")
    return float(max(Decimal("0.01"), rounded))


def load_calendar(root: Path, years: set[int]) -> Calendar:
    holidays: set[date] = set()
    for year in years:
        path = root / "data" / "calendar" / "krx" / f"{year}.json"
        if not path.is_file():
            raise RuntimeError(f"KRX_AUTHORITATIVE_CALENDAR_REQUIRED:{year}:{path}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("source") != "KRX" or int(payload.get("year", 0)) != year:
            raise RuntimeError(f"KRX_AUTHORITATIVE_CALENDAR_INVALID:{year}:{path}")
        holidays.update(date.fromisoformat(x) for x in payload.get("holidays", []))
    return Calendar(holidays)


def latest_master_snapshot(root: Path) -> tuple[Path, date]:
    pattern = re.compile(r"^(\d{8})_options_daily\.json$")
    today = date.today()
    candidates = []
    folder = root / "data" / "historical" / "krx_raw"
    for path in folder.glob("*_options_daily.json"):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        raw = match.group(1)
        snapshot = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        if snapshot <= today:
            candidates.append((snapshot, path))
    if not candidates:
        raise RuntimeError(f"KRX_AUTHORITATIVE_OPTION_MASTER_REQUIRED:{folder}")
    snapshot, path = max(candidates, key=lambda item: item[0])
    return path, snapshot


def parse_master(root: Path, calendar: Calendar, path: Path) -> tuple[dict[str, dict], str, str, dict[str, dict], dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(f"KRX_AUTHORITATIVE_OPTION_MASTER_REQUIRED:{path}")
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8-sig"))
    rows = payload.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("KRX_AUTHORITATIVE_OPTION_MASTER_EMPTY")
    monthly_pattern = re.compile(r"(?:^|\s)(?:C|P)\s+(20\d{4})\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    weekly_pattern = re.compile(r"(?:^|\s)(?:C|P)\s+(\d{4}W\d)\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    monthly_rows = []
    weekly_rows = []
    weekly_series_expiries: dict[str, str] = {}
    for row in rows:
        name = str(row.get("ISU_NM", "")).strip()
        name_escaped = name.encode("unicode_escape").decode("ascii")
        kind = str(row.get("RGHT_TP_NM", "")).upper()
        code = str(row.get("ISU_CD", "")).strip()
        product = str(row.get("PROD_NM", "")).strip()
        product_escaped = product.encode("unicode_escape").decode("ascii")
        if kind not in {"CALL", "PUT"} or not code or not product:
            continue
        weekly_match = weekly_pattern.search(name)
        if weekly_match and r"\ucf54\uc2a4\ud53c200" in product_escaped and r"\uc704\ud074\ub9ac" in product_escaped:
            series = weekly_match.group(1)
            year, month, week_num = 2000 + int(series[:2]), int(series[2:4]), int(series[-1])
            if r"\uc6d4" in product_escaped or re.search(r"\uc704\ud074\ub9ac\s*M", name_escaped):
                weekday = 0
            elif r"\ubaa9" in product_escaped:
                weekday = 3
            else:
                # Without the listed weekday family, the expiry is not authoritative.
                continue
            expiry = calculate_krx_weekly_option_expiry(year, month, week_num, calendar, weekday=weekday)
            strike = Decimal(weekly_match.group(2).replace(",", ""))
            weekly_rows.append({"series": series, "month": f"{year:04d}{month:02d}", "expiry": expiry,
                                "strike": strike, "option_type": kind, "code": code, "product": product,
                                "contract_class": "weekly", "weekday": weekday})
            weekly_series_expiries[f"{product}:{series}"] = expiry
            continue
        monthly_match = monthly_pattern.search(name)
        if monthly_match and r"\ucf54\uc2a4\ud53c200" in product_escaped and r"\uc704\ud074\ub9ac" not in product_escaped and r"\ubbf8\ub2c8" not in product_escaped:
            month = monthly_match.group(1)
            if not 1 <= int(month[4:]) <= 12:
                continue
            monthly_rows.append({"month": month, "strike": Decimal(monthly_match.group(2).replace(",", "")),
                                 "option_type": kind, "code": code, "product": product,
                                 "contract_class": "monthly"})
    if not monthly_rows:
        raise RuntimeError("KRX_AUTHORITATIVE_OPTION_MASTER_NO_MONTHLY_OPTIONS")
    product_coverage: dict[str, set[tuple[str, str, Decimal]]] = {}
    for row in monthly_rows:
        product_coverage.setdefault(row["product"], set()).add((row["month"], row["option_type"], row["strike"]))
    ranked = sorted(product_coverage.items(), key=lambda item: (len(item[1]), item[0]), reverse=True)
    if len(ranked) < 1:
        raise RuntimeError("KRX_KOSPI200_REGULAR_OPTION_FAMILY_AMBIGUOUS")
    selected_product = ranked[0][0]
    selected_monthly = [row for row in monthly_rows if row["product"] == selected_product]
    identities: dict[str, dict] = {}
    monthly_expiries: dict[str, str] = {}
    for row in selected_monthly:
        month = row["month"]
        expiry = calculate_krx_monthly_option_expiry(int(month[:4]), int(month[4:]), calendar)
        monthly_expiries[month] = expiry
        identity = {"instrument_id": row["code"], "month": month, "expiry": expiry,
                    "option_type": row["option_type"], "strike": row["strike"],
                    "contract_multiplier": MULTIPLIER, "identity_source": path.name,
                    "contract_class": "monthly", "product_family": row["product"]}
        previous = identities.get(row["code"])
        if previous is not None and previous != identity:
            raise RuntimeError(f"KRX_OPTION_MASTER_CONFLICTING_IDENTITY:{row['code']}")
        identities[row["code"]] = identity
    for row in weekly_rows:
        identity = {"instrument_id": row["code"], "month": row["month"], "expiry": row["expiry"],
                    "option_type": row["option_type"], "strike": row["strike"],
                    "contract_multiplier": MULTIPLIER, "identity_source": path.name,
                    "contract_class": "weekly", "product_family": row["product"], "series": row["series"]}
        previous = identities.get(row["code"])
        if previous is not None and previous != identity:
            raise RuntimeError(f"KRX_OPTION_MASTER_CONFLICTING_IDENTITY:{row['code']}")
        identities[row["code"]] = identity
    by_month: dict[str, dict[tuple[str, Decimal], dict]] = {}
    for identity in identities.values():
        if identity["contract_class"] == "monthly":
            by_month.setdefault(identity["month"], {})[(identity["option_type"], identity["strike"])] = identity
    snapshot_match = re.fullmatch(r"(\d{8})_options_daily\.json", path.name)
    if not snapshot_match:
        raise RuntimeError(f"KRX_OPTION_MASTER_SNAPSHOT_DATE_INVALID:{path.name}")
    snapshot_raw = snapshot_match.group(1)
    snapshot_day = date(int(snapshot_raw[:4]), int(snapshot_raw[4:6]), int(snapshot_raw[6:8]))
    required_months = [m for m in sorted(by_month) if m in monthly_expiries and date.fromisoformat(monthly_expiries[m]) >= snapshot_day]
    if len(required_months) < 4:
        raise RuntimeError(f"KRX_OPTION_MASTER_MONTH_ROLL_COVERAGE_REQUIRED:{required_months}")
    for month in required_months[:4]:
        if not any(k == "CALL" for k, _ in by_month[month]) or not any(k == "PUT" for k, _ in by_month[month]):
            raise RuntimeError(f"KRX_OPTION_MASTER_CALL_PUT_REQUIRED:{month}")
    return identities, hashlib.sha256(raw_bytes).hexdigest(), selected_product, monthly_expiries, weekly_series_expiries


def load_initial_underlying_spot(root: Path, snapshot_day: date) -> tuple[float, str, str]:
    """Load the same-date KOSPI200 index spot from regular KRX futures data."""
    path = root / "data" / "historical" / "krx_raw" / f"{snapshot_day:%Y%m%d}_futures_daily.json"
    if not path.is_file():
        raise RuntimeError(f"KRX_AUTHORITATIVE_UNDERLYING_REQUIRED:{path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"KRX_AUTHORITATIVE_UNDERLYING_EMPTY:{path}")
    regular_product = chr(0xCF54) + chr(0xC2A4) + chr(0xD53C) + "200 " + chr(0xC120) + chr(0xBB3C)
    weekly_label = chr(0xC8FC) + chr(0xAC04)
    candidates = []
    for row in rows:
        product = str(row.get("PROD_NM", "")).strip()
        name = str(row.get("ISU_NM", "")).strip()
        if str(row.get("BAS_DD", "")) != snapshot_day.strftime("%Y%m%d") or product != regular_product:
            continue
        if not re.search(r"\bF 20\d{4} \(", name) or f"({weekly_label})" not in name:
            continue
        try:
            value = float(str(row.get("SPOT_PRC", "")).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            candidates.append((value, str(row.get("ISU_CD", "")), name))
    if not candidates:
        raise RuntimeError(f"KRX_AUTHORITATIVE_KOSPI200_SPOT_NOT_FOUND:{snapshot_day}")
    values = {round(value, 6) for value, _, _ in candidates}
    if len(values) != 1:
        raise RuntimeError(f"KRX_AUTHORITATIVE_KOSPI200_SPOT_CONFLICT:{snapshot_day}:{sorted(values)}")
    value, code, _ = candidates[0]
    return value, path.relative_to(root).as_posix(), code
def option_valuation(spot: float, strike: float, expiry: date, as_of: datetime, iv: float, kind: str) -> tuple[float, float, float, int]:
    """Return theoretical premium, intrinsic value, time value, and seconds to expiry."""
    expiry_cutoff = datetime.combine(expiry, LAST_TRADING_CLOSE)
    seconds = int((expiry_cutoff - as_of).total_seconds())
    if seconds < 0:
        raise RuntimeError(f"OPTION_QUOTE_AFTER_LAST_TRADING_CUTOFF:{expiry}:{as_of.isoformat()}")
    intrinsic = max(0.0, spot - strike if kind == "CALL" else strike - spot)
    years = seconds / (365.0 * 24.0 * 60.0 * 60.0)
    if years <= 0 or spot <= 0 or strike <= 0 or iv <= 0:
        theoretical = intrinsic
    else:
        sigma_root_t = iv * math.sqrt(years)
        d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / sigma_root_t
        d2 = d1 - sigma_root_t
        cdf = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        theoretical = spot * cdf(d1) - strike * cdf(d2) if kind == "CALL" else strike * cdf(-d2) - spot * cdf(-d1)
    theoretical = max(intrinsic, theoretical, 0.0)
    time_value = max(0.0, theoretical - intrinsic)
    return theoretical, intrinsic, time_value, seconds


def option_mid(spot: float, strike: float, expiry: date, as_of: datetime, iv: float, kind: str) -> float:
    return option_valuation(spot, strike, expiry, as_of, iv, kind)[0]


def pattern_step(pattern: str, progress: float, rng: random.Random) -> tuple[float, float]:
    if pattern == "trend_up": return 0.00004 + rng.gauss(0, 0.00015), 0.19
    if pattern == "trend_down": return -0.00004 + rng.gauss(0, 0.00015), 0.20
    if pattern == "mean_revert": return -0.00025*(progress-0.5) + rng.gauss(0, 0.00018), 0.18
    if pattern == "high_volatility": return rng.gauss(0, 0.0010), 0.34
    if pattern == "low_volatility": return rng.gauss(0, 0.00010), 0.12
    if pattern == "shock": return (-0.0012 if 0.52 <= progress <= 0.54 else (0.0005 if 0.54 < progress <= 0.60 else rng.gauss(0,0.0002))), 0.28
    raise ValueError(f"UNKNOWN_PATTERN:{pattern}")


def generate(root: Path, output: Path, pattern: str, seed: int) -> dict:
    if pattern not in PATTERNS: raise ValueError(f"UNKNOWN_PATTERN:{pattern}")
    master_path, snapshot_day = latest_master_snapshot(root)
    horizon_end_exclusive = add_calendar_months(snapshot_day, HORIZON_MONTHS)
    calendar_years = set(range(snapshot_day.year, horizon_end_exclusive.year + 2))
    calendar=load_calendar(root,calendar_years)
    identities, master_sha, selected_product, monthly_expiries, weekly_series_expiries=parse_master(root,calendar,master_path)
    days=trading_days_between(calendar,snapshot_day,horizon_end_exclusive)
    if not days: raise RuntimeError("KRX_THREE_MONTH_HORIZON_HAS_NO_TRADING_DAYS")
    months=sorted({x["month"] for x in identities.values() if x["contract_class"] == "monthly"})
    usable=[m for m in months if m in monthly_expiries and date.fromisoformat(monthly_expiries[m]) >= snapshot_day]
    if len(usable)<4: raise RuntimeError("KRX_OPTION_MASTER_THREE_MONTH_ROLL_REQUIRED")
    spot, underlying_source_path, underlying_source_code = load_initial_underlying_spot(root, snapshot_day)
    initial_underlying_spot = spot
    active_month_by_day = {}
    bar_count_by_day = {}
    for scenario_day in days:
        active_months = [m for m in usable if date.fromisoformat(monthly_expiries[m]) >= scenario_day]
        if not active_months:
            raise RuntimeError(f"KRX_OPTION_MASTER_NO_ACTIVE_MONTH:{scenario_day}")
        active_month_by_day[scenario_day] = active_months[0]
        bar_count_by_day[scenario_day] = session_bar_count(
            scenario_day, date.fromisoformat(monthly_expiries[active_months[0]]) == scenario_day
        )
    total_bars = sum(bar_count_by_day.values())
    rng=random.Random(seed); seq=0; total=0; day_manifest=[]; bar_offset=0
    output.mkdir(parents=True,exist_ok=True)
    identities_by_month={}
    identities_by_weekly_expiry={}
    for ident in identities.values():
        if ident["contract_class"] == "monthly":
            identities_by_month.setdefault(ident["month"],{}).setdefault((ident["option_type"],ident["strike"]),ident)
        else:
            identities_by_weekly_expiry.setdefault(ident["expiry"],{}).setdefault((ident["option_type"],ident["strike"]),ident)
    weekly_expiry_dates=sorted(date.fromisoformat(value) for value in set(weekly_series_expiries.values()))
    weekly_rollovers=[]
    for weekly_expiry in weekly_expiry_dates:
        weekly_rollovers.append({"expiry":normalize_option_expiry(weekly_expiry).require_exact(),"series":[key for key,value in weekly_series_expiries.items() if value==weekly_expiry.isoformat()]})
    for day_index, day in enumerate(days):
        month = active_month_by_day[day]
        expiry=date.fromisoformat(monthly_expiries[month])
        monthly_last_trading_day = expiry == day
        bar_count = bar_count_by_day[day]
        session_close = LAST_TRADING_CLOSE if monthly_last_trading_day else SESSION_CLOSE
        month_identities=identities_by_month[month]
        strikes=sorted({strike for (kind,strike) in month_identities})
        if len(strikes)<5: raise RuntimeError(f"KRX_OPTION_MASTER_STRIKES_INSUFFICIENT:{month}")
        daily_path=output/f"{day.isoformat()}.jsonl"; day_count=0; day_weekly_bars=0
        with daily_path.open('w',encoding='utf-8',newline='\n') as handle:
            day_daily_pair_covered=True
            day_monthly_pair_covered=True
            day_weekly_contract_used=False
            day_weekly_block_reasons=set()
            for bar in range(bar_count):
                progress=(bar_offset+bar)/max(1,total_bars-1)
                drift,iv=pattern_step(pattern,progress,rng); spot=round(max(400.0,spot*(1.0+drift)),4)
                atm=min(strikes,key=lambda x:abs(float(x)-spot)); atm_index=strikes.index(atm)
                offset=Decimal("12.5")
                monthly_offset=Decimal("15")
                valid_shared_centers=[x for x in strikes if x-offset in strikes and x+offset in strikes and x-monthly_offset in strikes and x+monthly_offset in strikes]
                shared_center=min(valid_shared_centers,key=lambda x:(abs(float(x)-spot),x)) if valid_shared_centers else None
                ts=datetime.combine(day,SESSION_OPEN)+timedelta(minutes=BAR_INTERVAL_MINUTES*bar)
                next_weekly_expiries=[value for value in weekly_expiry_dates if value >= day]
                weekly_expiry_date=min(next_weekly_expiries).isoformat() if next_weekly_expiries else None
                event_contracts=[]
                weekly_contract_available=False
                weekly_block_reason=None
                weekly_identities=identities_by_weekly_expiry.get(weekly_expiry_date, {}) if weekly_expiry_date else {}
                weekly_strikes=sorted({strike for (kind,strike) in weekly_identities})
                nearest_weekly_distance=min((abs(float(strike)-spot) for strike in weekly_strikes),default=None)
                # The scenario underlying is anchored to the selected monthly family.
                # A listed weekly code is not usable when its authoritative strike ladder
                # does not cover that same underlying price neighborhood.
                weekly_cutoff_passed = bool(weekly_expiry_date and day == date.fromisoformat(weekly_expiry_date) and ts.time() >= LAST_TRADING_CLOSE)
                if weekly_cutoff_passed:
                    weekly_block_reason="WEEKLY_CONTRACT_AFTER_LAST_TRADING_CUTOFF"
                    day_weekly_block_reasons.add(weekly_block_reason)
                elif weekly_expiry_date and len(weekly_strikes)>=2 and nearest_weekly_distance is not None and nearest_weekly_distance <= 25.0:
                    weekly_contract_available=True
                elif weekly_expiry_date:
                    weekly_block_reason="AUTHORITATIVE_WEEKLY_STRIKE_RANGE_DOES_NOT_MATCH_UNDERLYING" if nearest_weekly_distance is not None else "AUTHORITATIVE_WEEKLY_CONTRACTS_NOT_FOUND"
                    day_weekly_block_reasons.add(weekly_block_reason)
                if weekly_contract_available:
                    day_weekly_contract_used=True
                    day_weekly_bars += 1
                    put_target=spot-12.5; call_target=spot+12.5
                    selected_weekly_strikes=list(dict.fromkeys(min(weekly_strikes,key=lambda x:abs(float(x)-target)) for target in (put_target,call_target)))
                    for candidate in sorted(weekly_strikes, key=lambda x: (abs(float(x)-spot), x)):
                        if len(selected_weekly_strikes) >= 2: break
                        if candidate not in selected_weekly_strikes: selected_weekly_strikes.append(candidate)
                    selected_weekly_strikes=sorted(selected_weekly_strikes)
                    if shared_center is not None:
                        monthly_five=[shared_center-monthly_offset,shared_center-offset,shared_center,shared_center+offset,shared_center+monthly_offset]
                    else:
                        monthly_five=sorted(strikes,key=lambda x:(abs(float(x)-spot),x))[:5]
                        monthly_five=sorted(monthly_five)
                    for kind in ("CALL","PUT"):
                        for strike in monthly_five:
                            event_contracts.append((month_identities.get((kind,strike)),kind,strike,"monthly"))
                    for kind in ("CALL","PUT"):
                        for strike in selected_weekly_strikes:
                            event_contracts.append((weekly_identities.get((kind,strike)),kind,strike,"weekly"))
                else:
                    if shared_center is not None:
                        monthly_five=[shared_center-monthly_offset,shared_center-offset,shared_center,shared_center+offset,shared_center+monthly_offset]
                    else:
                        monthly_five=sorted(strikes,key=lambda x:(abs(float(x)-spot),x))[:5]
                        monthly_five=sorted(monthly_five)
                    for kind in ("CALL","PUT"):
                        for strike in monthly_five:
                            event_contracts.append((month_identities.get((kind,strike)),kind,strike,"monthly"))
                daily_pair_available = any(
                    center-offset in monthly_five and center+offset in monthly_five and abs(float(center)-spot) <= 25.0
                    for center in strikes
                )
                monthly_pair_available = any(
                    center-monthly_offset in monthly_five and center+monthly_offset in monthly_five and abs(float(center)-spot) <= 25.0
                    for center in strikes
                )
                day_daily_pair_covered = day_daily_pair_covered and daily_pair_available
                day_monthly_pair_covered = day_monthly_pair_covered and monthly_pair_available
                expected_bar_events = CONTRACTS_PER_BAR + (4 if weekly_contract_available else 0)
                if len(event_contracts) != expected_bar_events:
                    raise RuntimeError(f"STRATEGY_HORIZON_EVENT_SHAPE_INVALID:{day}:{len(event_contracts)}:{expected_bar_events}")
                for ident,kind,strike,contract_class in event_contracts:
                    if ident is None: raise RuntimeError(f"KRX_OPTION_MASTER_IDENTITY_REQUIRED:{contract_class}:{day}:{kind}:{strike}")
                    contract_expiry=date.fromisoformat(ident["expiry"])
                    mid,intrinsic,time_value,time_to_expiry_seconds=option_valuation(spot,float(strike),contract_expiry,ts,iv,kind)
                    spread=max(0.02,mid*(0.008+iv*0.015)); noise=rng.uniform(-spread*0.25,spread*0.25)
                    bid=round_option_price(max(0.01,mid-spread/2))
                    ask=round_option_price(max(mid+spread/2,bid+float(option_tick_size(bid))))
                    last=round_option_price(max(0.01,mid+noise))
                    exact_expiry=normalize_option_expiry(ident["expiry"]).require_exact()
                    seq+=1
                    tick={"timestamp":ts.isoformat(),"underlying_price":round(spot,4),"underlying_symbol":"KOSPI200","strike_price":float(strike),"option_type":kind,"contract_multiplier":MULTIPLIER,"bid_price":bid,"ask_price":ask,"last_price":last,"theoretical_mid_price":round(mid,8),"intrinsic_value":round(intrinsic,8),"time_value":round(time_value,8),"time_to_expiry_seconds":time_to_expiry_seconds,"implied_volatility":iv,"volume":rng.randint(1,500),"seq_id":seq,"expiry":exact_expiry,"contract_month":ident["month"],"contract_class":contract_class,"symbol":"KOSPI200","option_observed_hour":ts.strftime("%H:%M"),"option_source":f"KRX_OPTION_MASTER:{master_sha[:12]}:{pattern}","instrument_id":ident["instrument_id"]}
                    record={"schema":SCHEMA,"source":f"DERIVED_FROM_KRX_OPTION_MASTER:{master_sha[:12]}","dataset":output.name,"provenance":"DERIVED_SCENARIO","provider":"KOSPI200_KRX_MASTER_SCENARIO","tick":tick}
                    handle.write(json.dumps(record,separators=(",",":"))+"\n"); total+=1; day_count+=1
        day_manifest.append({"date":day.isoformat(),"file":daily_path.name,"events":day_count,"bars":bar_count,"weekly_contract_bars":day_weekly_bars,"session_open":SESSION_OPEN.strftime("%H:%M"),"session_close_exclusive":session_close.strftime("%H:%M"),"session_type":"MONTHLY_LAST_TRADING_DAY" if monthly_last_trading_day else "REGULAR","expiry_month":month,"expiry":normalize_option_expiry(monthly_expiries[month]).require_exact(),"weekly_expiry":normalize_option_expiry(weekly_expiry_date).require_exact() if weekly_expiry_date else None,"weekly_contract_available":day_weekly_contract_used,"weekly_contract_block_reason":";".join(sorted(day_weekly_block_reasons)) or None,"daily_pair_available":day_daily_pair_covered,"monthly_pair_available":day_monthly_pair_covered,"daily_close_limit":"15:00","daily_close_fallback":"15:15","pattern":pattern})
        bar_offset += bar_count
    expected_events = sum(item["bars"] * CONTRACTS_PER_BAR + item["weekly_contract_bars"] * 4 for item in day_manifest)
    if total != expected_events or not day_manifest or len(day_manifest) != len(days):
        raise RuntimeError(f"DATASET_SHAPE_INVALID:{total}:{expected_events}:{len(day_manifest)}:{len(days)}")
    rollovers=[]
    for item in day_manifest:
        if not rollovers or rollovers[-1]["month"]!=item["expiry_month"]:
            rollovers.append({"month":item["expiry_month"],"expiry":item["expiry"],"first_date":item["date"]})
    if len(rollovers)<3: raise RuntimeError(f"MONTHLY_EXPIRY_ROLLOVER_MISSING:{rollovers}")
    weekly_coverage_days=[item["date"] for item in day_manifest if item["weekly_contract_available"]]
    weekly_coverage_end=max(weekly_coverage_days) if weekly_coverage_days else None
    weekly_block_reasons=sorted({item["weekly_contract_block_reason"] for item in day_manifest if item["weekly_contract_block_reason"]})
    daily_coverage_days=[item["date"] for item in day_manifest if item["daily_pair_available"]]
    strategy_lifecycle={
        "strategy6_daily_tail_insurance":{"contract_class":"any_listed_option","start_time":"09:00","close_limit":"15:00","close_fallback":"15:15","carry_over_allowed":False,"daily_pair_coverage_status":"FULL" if len(daily_coverage_days)==len(days) else "PARTIAL_OR_UNAVAILABLE","daily_pair_coverage_days":len(daily_coverage_days),"daily_pair_uncovered_days":[item["date"] for item in day_manifest if not item["daily_pair_available"]],"expiry_semantics":"same-session strategy cutoff; does not falsify instrument expiry"},
        "strategy7_weekly_volatility_skew_insurance":{"required_contract_class":"weekly","entry_trigger":"first trading day of ISO week","exit_time_on_exact_contract_expiry":"15:00","weekly_expiries":weekly_rollovers,"authoritative_coverage_end":weekly_coverage_end,"coverage_status":"FULL" if len(weekly_coverage_days)==len(days) else ("UNAVAILABLE_STRIKE_RANGE_MISMATCH" if not weekly_coverage_days and "AUTHORITATIVE_WEEKLY_STRIKE_RANGE_DOES_NOT_MATCH_UNDERLYING" in weekly_block_reasons else "PARTIAL_AUTHORITATIVE_MASTER_COVERAGE"),"weekly_contract_coverage_days":len(weekly_coverage_days),"uncovered_trading_days":[item["date"] for item in day_manifest if not item["weekly_contract_available"]],"block_reasons":weekly_block_reasons},
        "strategy8_monthly_macro_strangle":{"required_contract_class":"monthly","monthly_expiries":{month:normalize_option_expiry(value).require_exact() for month,value in monthly_expiries.items()},"entry_min_dte":15,"dte_lte_4_action":"NON_EXECUTION_HOLD_LONG_ATTACK","monthly_pair_coverage_status":"FULL" if all(item["monthly_pair_available"] for item in day_manifest) else "PARTIAL_OR_UNAVAILABLE","monthly_pair_coverage_days":sum(1 for item in day_manifest if item["monthly_pair_available"]),"monthly_pair_uncovered_days":[item["date"] for item in day_manifest if not item["monthly_pair_available"]]}
    }
    manifest={"schema":"reference-canonical-market-tick-v1","rules_version":RULES_VERSION,"dataset":output.name,"provenance":"DERIVED_SCENARIO","source":"KRX_OPTION_MASTER_SNAPSHOT","option_master_path":str(master_path.relative_to(root)).replace("\\","/"),"option_master_snapshot_date":snapshot_day.isoformat(),"option_master_sha256":master_sha,"selected_product_family":selected_product,"underlying_symbol":"KOSPI200","initial_underlying_spot":initial_underlying_spot,"underlying_spot_source_path":underlying_source_path,"underlying_spot_source_code":underlying_source_code,"underlying_spot_source_field":"KRX futures_daily.SPOT_PRC (regular KOSPI200 futures; Mini excluded)","calendar_source":";".join(f"data/calendar/krx/{year}.json" for year in sorted(calendar_years)),"horizon_months":HORIZON_MONTHS,"timezone":"Asia/Seoul","date_start":days[0].isoformat(),"date_end":days[-1].isoformat(),"date_end_exclusive":horizon_end_exclusive.isoformat(),"trading_days":len(days),"bar_interval_minutes":BAR_INTERVAL_MINUTES,"session_open":SESSION_OPEN.strftime("%H:%M"),"session_close":"15:45","last_trading_cutoff":LAST_TRADING_CLOSE.strftime("%H:%M"),"contracts_per_bar_without_weekly":CONTRACTS_PER_BAR,"weekly_extra_contracts_per_bar":4,"events":total,"seed":seed,"pattern":pattern,"contract_multiplier":MULTIPLIER,"pricing_assumptions":{"model":"BLACK_SCHOLES_SCENARIO_APPROXIMATION","risk_free_rate":0.0,"dividend_yield":0.0,"time_basis":"actual seconds to 15:20 KST on exact expiry date","implied_volatility_source":"declared scenario pattern assumptions"},"option_tick_sizes":{"premium_below_10":0.01,"premium_at_or_above_10":0.05},"market_rule_limitations":["KRX_DAILY_PRICE_LIMIT_NOT_ENFORCED_NO_AUTHORITATIVE_PER_CONTRACT_BASE_PRICE"],"monthly_rollovers":rollovers,"monthly_expiries":{month:normalize_option_expiry(value).require_exact() for month,value in monthly_expiries.items()},"weekly_series_expiries":{series:normalize_option_expiry(value).require_exact() for series,value in weekly_series_expiries.items()},"weekly_rollovers":weekly_rollovers,"strategy_lifecycle":strategy_lifecycle,"days":day_manifest}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    store=output/"control_tower_replay.jsonl"
    with store.open('w',encoding='utf-8',newline='\n') as target:
        for item in day_manifest:
            with (output/item['file']).open(encoding='utf-8') as source:
                for line in source: target.write(line)
    return manifest


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True); parser.add_argument('--pattern',choices=PATTERNS,required=True); parser.add_argument('--seed',type=int,required=True)
    args=parser.parse_args(); root=Path.cwd(); output=Path(args.output)
    manifest=generate(root,output,args.pattern,args.seed)
    print(json.dumps({k:manifest[k] for k in ('dataset','rules_version','date_start','date_end','date_end_exclusive','trading_days','events','initial_underlying_spot','underlying_spot_source_path','underlying_spot_source_code','monthly_rollovers','weekly_rollovers','strategy_lifecycle','option_master_sha256')},ensure_ascii=False))

if __name__=='__main__': main()
