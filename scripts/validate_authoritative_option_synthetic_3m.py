from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from contracts.option_expiry import normalize_option_expiry
from scripts.generate_authoritative_option_synthetic_3m import (
    BAR_INTERVAL_MINUTES,
    CONTRACTS_PER_BAR,
    HORIZON_MONTHS,
    LAST_TRADING_CLOSE,
    MULTIPLIER,
    RULES_VERSION,
    SCHEMA,
    SESSION_CLOSE,
    SESSION_OPEN,
    add_calendar_months,
    load_calendar,
    load_initial_underlying_spot,
    option_valuation,
    option_tick_size,
    parse_master,
    round_option_price,
    trading_days_between,
)


def validate_dataset(root: Path, dataset: Path) -> dict:
    manifest_path = dataset / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"MANIFEST_REQUIRED:{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("rules_version") != RULES_VERSION:
        raise RuntimeError(f"RULES_VERSION_MISMATCH:{manifest.get('rules_version')}")
    if manifest.get("provenance") != "DERIVED_SCENARIO":
        raise RuntimeError(f"PROVENANCE_INVALID:{manifest.get('provenance')}")
    if manifest.get("pattern") not in {"trend_up", "trend_down", "mean_revert", "high_volatility", "low_volatility", "shock"}:
        raise RuntimeError(f"PATTERN_INVALID:{manifest.get('pattern')}")
    if int(manifest.get("horizon_months", 0)) != HORIZON_MONTHS:
        raise RuntimeError(f"HORIZON_MONTHS_INVALID:{manifest.get('horizon_months')}")
    if manifest.get("timezone") != "Asia/Seoul":
        raise RuntimeError(f"TIMEZONE_INVALID:{manifest.get('timezone')}")

    snapshot_day = date.fromisoformat(manifest["option_master_snapshot_date"])
    end_exclusive = add_calendar_months(snapshot_day, HORIZON_MONTHS)
    if manifest.get("date_end_exclusive") != end_exclusive.isoformat():
        raise RuntimeError(f"THREE_MONTH_END_BOUNDARY_INVALID:{manifest.get('date_end_exclusive')}:{end_exclusive}")
    calendar_years = set(range(snapshot_day.year, end_exclusive.year + 2))
    calendar = load_calendar(root, calendar_years)
    expected_calendar_source = ";".join(f"data/calendar/krx/{year}.json" for year in sorted(calendar_years))
    if manifest.get("calendar_source") != expected_calendar_source:
        raise RuntimeError(f"CALENDAR_PROVENANCE_INVALID:{manifest.get('calendar_source')}:{expected_calendar_source}")
    expected_days = trading_days_between(calendar, snapshot_day, end_exclusive)
    if not expected_days:
        raise RuntimeError("THREE_MONTH_HORIZON_HAS_NO_TRADING_DAYS")
    if manifest.get("date_start") != expected_days[0].isoformat() or manifest.get("date_end") != expected_days[-1].isoformat():
        raise RuntimeError(f"DATE_WINDOW_INVALID:{manifest.get('date_start')}:{manifest.get('date_end')}")
    if int(manifest.get("trading_days", 0)) != len(expected_days):
        raise RuntimeError(f"TRADING_DAY_COUNT_INVALID:{manifest.get('trading_days')}:{len(expected_days)}")

    master_path = root / Path(manifest["option_master_path"])
    if not master_path.is_file():
        raise RuntimeError(f"OPTION_MASTER_SOURCE_MISSING:{master_path}")
    master_hash = hashlib.sha256(master_path.read_bytes()).hexdigest()
    if master_hash != manifest.get("option_master_sha256"):
        raise RuntimeError(f"OPTION_MASTER_HASH_MISMATCH:{master_hash}:{manifest.get('option_master_sha256')}")
    master_date_match = re.fullmatch(r"(\d{8})_options_daily\.json", master_path.name)
    if not master_date_match or date.fromisoformat(f"{master_date_match.group(1)[:4]}-{master_date_match.group(1)[4:6]}-{master_date_match.group(1)[6:8]}") != snapshot_day:
        raise RuntimeError(f"OPTION_MASTER_SNAPSHOT_DATE_MISMATCH:{master_path.name}:{snapshot_day}")
    identities, parsed_hash, selected_product, monthly_expiries, weekly_expiries = parse_master(root, calendar, master_path)
    if parsed_hash != master_hash or selected_product != manifest.get("selected_product_family"):
        raise RuntimeError("OPTION_MASTER_IDENTITY_SOURCE_MISMATCH")
    expected_monthly_expiries = {month: normalize_option_expiry(value).require_exact() for month, value in monthly_expiries.items()}
    expected_weekly_expiries = {series: normalize_option_expiry(value).require_exact() for series, value in weekly_expiries.items()}
    if manifest.get("monthly_expiries") != expected_monthly_expiries or manifest.get("weekly_series_expiries") != expected_weekly_expiries:
        raise RuntimeError("MANIFEST_EXPIRY_TABLE_MISMATCH")

    underlying_source = root / Path(manifest.get("underlying_spot_source_path", ""))
    if not underlying_source.is_file() or not manifest.get("underlying_spot_source_code") or float(manifest.get("initial_underlying_spot", 0)) <= 0:
        raise RuntimeError("INITIAL_UNDERLYING_PROVENANCE_INVALID")
    authoritative_spot, authoritative_spot_path, authoritative_spot_code = load_initial_underlying_spot(root, snapshot_day)
    if abs(authoritative_spot - float(manifest["initial_underlying_spot"])) > 1e-6 or authoritative_spot_path != manifest.get("underlying_spot_source_path") or authoritative_spot_code != manifest.get("underlying_spot_source_code"):
        raise RuntimeError("INITIAL_UNDERLYING_SOURCE_VALUE_MISMATCH")
    if manifest.get("underlying_spot_source_field") != "KRX futures_daily.SPOT_PRC (regular KOSPI200 futures; Mini excluded)":
        raise RuntimeError("INITIAL_UNDERLYING_SOURCE_FIELD_INVALID")
    if manifest.get("session_open") != SESSION_OPEN.strftime("%H:%M") or manifest.get("session_close") != SESSION_CLOSE.strftime("%H:%M") or manifest.get("last_trading_cutoff") != LAST_TRADING_CLOSE.strftime("%H:%M"):
        raise RuntimeError("KRX_SESSION_RULES_INVALID")
    if float(manifest.get("contract_multiplier", 0)) != MULTIPLIER:
        raise RuntimeError("CONTRACT_MULTIPLIER_INVALID")
    limitations = manifest.get("market_rule_limitations")
    expected_limitations = ["KRX_DAILY_PRICE_LIMIT_NOT_ENFORCED_NO_AUTHORITATIVE_PER_CONTRACT_BASE_PRICE"]
    if limitations != expected_limitations:
        raise RuntimeError(f"MARKET_RULE_LIMITATIONS_NOT_DECLARED:{limitations}")
    pricing = manifest.get("pricing_assumptions", {})
    if pricing.get("model") != "BLACK_SCHOLES_SCENARIO_APPROXIMATION" or pricing.get("risk_free_rate") != 0.0 or pricing.get("dividend_yield") != 0.0:
        raise RuntimeError("PRICING_ASSUMPTIONS_INVALID")

    daily_manifest = manifest.get("days")
    if not isinstance(daily_manifest, list) or [item.get("date") for item in daily_manifest] != [day.isoformat() for day in expected_days]:
        raise RuntimeError("DAILY_MANIFEST_CALENDAR_MISMATCH")

    expected_seq = 1
    total_events = 0
    weekly_covered_days = 0
    daily_pair_days = 0
    monthly_pair_days = 0
    for item, scenario_day in zip(daily_manifest, expected_days, strict=True):
        if not calendar.is_trading_day(scenario_day) or scenario_day.weekday() >= 5:
            raise RuntimeError(f"NON_TRADING_DAY_IN_DATASET:{scenario_day}")
        active_month = item.get("expiry_month")
        expected_month_expiry = monthly_expiries.get(active_month)
        if expected_month_expiry is None:
            raise RuntimeError(f"MONTHLY_EXPIRY_NOT_IN_MASTER:{scenario_day}:{active_month}")
        expected_month_expiry_exact = normalize_option_expiry(expected_month_expiry).require_exact()
        if item.get("expiry") != expected_month_expiry_exact:
            raise RuntimeError(f"MONTHLY_EXPIRY_IDENTITY_MISMATCH:{scenario_day}:{item.get('expiry')}:{expected_month_expiry_exact}")
        monthly_last_trading_day = date.fromisoformat(expected_month_expiry) == scenario_day
        expected_close = LAST_TRADING_CLOSE if monthly_last_trading_day else SESSION_CLOSE
        expected_bars = int((datetime.combine(scenario_day, expected_close) - datetime.combine(scenario_day, SESSION_OPEN)).total_seconds() // (BAR_INTERVAL_MINUTES * 60))
        if int(item.get("bars", -1)) != expected_bars:
            raise RuntimeError(f"SESSION_BAR_COUNT_INVALID:{scenario_day}:{item.get('bars')}:{expected_bars}")
        if item.get("session_open") != SESSION_OPEN.strftime("%H:%M") or item.get("session_close_exclusive") != expected_close.strftime("%H:%M"):
            raise RuntimeError(f"SESSION_WINDOW_INVALID:{scenario_day}")
        expected_session_type = "MONTHLY_LAST_TRADING_DAY" if monthly_last_trading_day else "REGULAR"
        if item.get("session_type") != expected_session_type:
            raise RuntimeError(f"SESSION_TYPE_INVALID:{scenario_day}:{item.get('session_type')}")

        daily_path = dataset / item.get("file", "")
        if daily_path.name != f"{scenario_day.isoformat()}.jsonl" or not daily_path.is_file():
            raise RuntimeError(f"DAILY_DATA_FILE_INVALID:{scenario_day}:{daily_path}")
        grouped: dict[datetime, list[dict]] = defaultdict(list)
        file_count = 0
        with daily_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("schema") != SCHEMA or record.get("provenance") != "DERIVED_SCENARIO":
                    raise RuntimeError(f"ROW_PROVENANCE_INVALID:{daily_path.name}:{line_number}")
                if record.get("dataset") != manifest.get("dataset"):
                    raise RuntimeError(f"ROW_DATASET_ID_INVALID:{daily_path.name}:{line_number}")
                if record.get("source") != f"DERIVED_FROM_KRX_OPTION_MASTER:{master_hash[:12]}":
                    raise RuntimeError(f"ROW_MASTER_PROVENANCE_INVALID:{daily_path.name}:{line_number}")
                tick = record.get("tick", {})
                timestamp = datetime.fromisoformat(tick["timestamp"])
                if timestamp.date() != scenario_day:
                    raise RuntimeError(f"ROW_DATE_MISMATCH:{daily_path.name}:{line_number}:{timestamp}")
                if timestamp.time() < SESSION_OPEN or timestamp.time() >= expected_close:
                    raise RuntimeError(f"ROW_OUTSIDE_SESSION:{daily_path.name}:{line_number}:{timestamp}")
                if timestamp.minute % BAR_INTERVAL_MINUTES != 0 or timestamp.second != 0 or timestamp.microsecond != 0:
                    raise RuntimeError(f"ROW_TIMESTAMP_ALIGNMENT_INVALID:{daily_path.name}:{line_number}:{timestamp}")
                if timestamp.time() < SESSION_OPEN:
                    raise RuntimeError(f"ROW_BEFORE_SESSION_OPEN:{daily_path.name}:{line_number}")
                if not isinstance(tick.get("expiry"), str) or not re.fullmatch(r"\d{8}", tick["expiry"]):
                    raise RuntimeError(f"ROW_EXPIRY_NOT_CANONICAL_YYYYMMDD:{daily_path.name}:{line_number}:{tick.get('expiry')}")
                exact_expiry = normalize_option_expiry(tick["expiry"]).require_exact()
                instrument_id = str(tick.get("instrument_id", ""))
                identity = identities.get(instrument_id)
                if identity is None:
                    raise RuntimeError(f"ROW_INSTRUMENT_NOT_IN_MASTER:{daily_path.name}:{line_number}:{instrument_id}")
                if exact_expiry != normalize_option_expiry(identity["expiry"]).require_exact():
                    raise RuntimeError(f"ROW_EXPIRY_IDENTITY_MISMATCH:{daily_path.name}:{line_number}:{instrument_id}")
                if tick.get("contract_month") != identity["month"] or tick.get("contract_class") != identity["contract_class"]:
                    raise RuntimeError(f"ROW_CONTRACT_CLASS_OR_MONTH_MISMATCH:{daily_path.name}:{line_number}:{instrument_id}")
                if tick.get("option_type") != identity["option_type"] or Decimal(str(tick.get("strike_price"))) != identity["strike"]:
                    raise RuntimeError(f"ROW_OPTION_IDENTITY_MISMATCH:{daily_path.name}:{line_number}:{instrument_id}")
                if float(tick.get("contract_multiplier", 0)) != MULTIPLIER or tick.get("underlying_symbol") != "KOSPI200":
                    raise RuntimeError(f"ROW_MULTIPLIER_OR_UNDERLYING_INVALID:{daily_path.name}:{line_number}")
                expiry_day = date(int(exact_expiry[:4]), int(exact_expiry[4:6]), int(exact_expiry[6:8]))
                expiry_cutoff = datetime.combine(expiry_day, LAST_TRADING_CLOSE)
                if timestamp >= expiry_cutoff:
                    raise RuntimeError(f"ROW_AFTER_CONTRACT_LAST_TRADING_CUTOFF:{daily_path.name}:{line_number}:{timestamp}:{exact_expiry}")

                bid = float(tick.get("bid_price", 0))
                ask = float(tick.get("ask_price", 0))
                last = float(tick.get("last_price", 0))
                if not all(math.isfinite(value) and value > 0 for value in (bid, ask, last)) or ask <= bid:
                    raise RuntimeError(f"ROW_QUOTE_INVALID:{daily_path.name}:{line_number}")
                for field, value in (("bid_price", bid), ("ask_price", ask), ("last_price", last)):
                    if abs(round_option_price(value) - value) > 1e-6:
                        raise RuntimeError(f"ROW_OPTION_TICK_SIZE_INVALID:{daily_path.name}:{line_number}:{field}:{value}")
                if option_tick_size(bid) not in {Decimal("0.01"), Decimal("0.05")} or option_tick_size(ask) not in {Decimal("0.01"), Decimal("0.05")}:
                    raise RuntimeError(f"ROW_OPTION_TICK_SIZE_RULE_INVALID:{daily_path.name}:{line_number}")

                spot = float(tick["underlying_price"])
                strike = float(tick["strike_price"])
                iv = float(tick["implied_volatility"])
                theoretical, intrinsic, time_value, seconds = option_valuation(spot, strike, expiry_day, timestamp, iv, tick["option_type"])
                if int(tick.get("time_to_expiry_seconds", -1)) != seconds:
                    raise RuntimeError(f"ROW_TIME_TO_EXPIRY_INVALID:{daily_path.name}:{line_number}")
                if abs(float(tick.get("theoretical_mid_price", -1)) - theoretical) > 1e-5:
                    raise RuntimeError(f"ROW_THEORETICAL_PRICE_INVALID:{daily_path.name}:{line_number}")
                if abs(float(tick.get("intrinsic_value", -1)) - intrinsic) > 1e-5:
                    raise RuntimeError(f"ROW_INTRINSIC_VALUE_INVALID:{daily_path.name}:{line_number}")
                if abs(float(tick.get("time_value", -1)) - time_value) > 1e-5 or time_value < -1e-8:
                    raise RuntimeError(f"ROW_TIME_VALUE_INVALID:{daily_path.name}:{line_number}")
                if not math.isfinite(iv) or iv <= 0:
                    raise RuntimeError(f"ROW_IV_INVALID:{daily_path.name}:{line_number}")
                if int(tick.get("seq_id", -1)) != expected_seq:
                    raise RuntimeError(f"ROW_SEQ_NOT_CONTIGUOUS:{daily_path.name}:{line_number}:{tick.get('seq_id')}:{expected_seq}")
                expected_seq += 1
                grouped[timestamp].append(record)
                file_count += 1

        if file_count != int(item.get("events", -1)):
            raise RuntimeError(f"DAILY_EVENT_COUNT_INVALID:{scenario_day}:{file_count}:{item.get('events')}")
        timestamps = sorted(grouped)
        if len(timestamps) != expected_bars:
            raise RuntimeError(f"BAR_TIMESTAMP_COUNT_INVALID:{scenario_day}:{len(timestamps)}:{expected_bars}")
        expected_times = [datetime.combine(scenario_day, SESSION_OPEN) + timedelta(minutes=BAR_INTERVAL_MINUTES * index) for index in range(expected_bars)]
        if timestamps != expected_times:
            raise RuntimeError(f"BAR_TIMESTAMP_SEQUENCE_INVALID:{scenario_day}")
        weekly_bars = 0
        for timestamp, records in grouped.items():
            weekly_rows = sum(1 for record in records if record["tick"]["contract_class"] == "weekly")
            expected_count = CONTRACTS_PER_BAR + (4 if weekly_rows else 0)
            if weekly_rows not in {0, 4} or len(records) != expected_count:
                raise RuntimeError(f"BAR_CONTRACT_ROW_COUNT_INVALID:{timestamp}:{len(records)}:{weekly_rows}")
            if weekly_rows:
                weekly_bars += 1
            for record in records:
                tick = record["tick"]
                if tick["contract_class"] == "weekly" and timestamp >= datetime.combine(date.fromisoformat(normalize_option_expiry(tick["expiry"]).require_exact()[:4] + "-" + normalize_option_expiry(tick["expiry"]).require_exact()[4:6] + "-" + normalize_option_expiry(tick["expiry"]).require_exact()[6:8]), LAST_TRADING_CLOSE):
                    raise RuntimeError(f"WEEKLY_CONTRACT_AFTER_CUTOFF:{timestamp}:{tick['instrument_id']}")
        if weekly_bars != int(item.get("weekly_contract_bars", -1)):
            raise RuntimeError(f"WEEKLY_BAR_COVERAGE_INVALID:{scenario_day}:{weekly_bars}:{item.get('weekly_contract_bars')}")
        if bool(weekly_bars) != bool(item.get("weekly_contract_available")):
            raise RuntimeError(f"WEEKLY_DAY_COVERAGE_INVALID:{scenario_day}")
        if item.get("daily_pair_available"):
            daily_pair_days += 1
        if item.get("monthly_pair_available"):
            monthly_pair_days += 1
        if weekly_bars:
            weekly_covered_days += 1
        expected_day_events = expected_bars * CONTRACTS_PER_BAR + weekly_bars * 4
        if file_count != expected_day_events:
            raise RuntimeError(f"DAILY_DYNAMIC_EVENT_COUNT_INVALID:{scenario_day}:{file_count}:{expected_day_events}")
        total_events += file_count

    if total_events != int(manifest.get("events", -1)):
        raise RuntimeError(f"TOTAL_EVENT_COUNT_INVALID:{total_events}:{manifest.get('events')}")
    if expected_seq - 1 != total_events:
        raise RuntimeError(f"TOTAL_SEQ_COUNT_INVALID:{expected_seq - 1}:{total_events}")
    strategy7 = manifest.get("strategy_lifecycle", {}).get("strategy7_weekly_volatility_skew_insurance", {})
    if strategy7.get("coverage_status") == "FULL" and weekly_covered_days != len(expected_days):
        raise RuntimeError(f"WEEKLY_COVERAGE_FALSE_FULL:{weekly_covered_days}:{len(expected_days)}")
    strategy6 = manifest.get("strategy_lifecycle", {}).get("strategy6_daily_tail_insurance", {})
    if int(strategy6.get("daily_pair_coverage_days", -1)) != daily_pair_days:
        raise RuntimeError(f"DAILY_PAIR_COVERAGE_MISMATCH:{daily_pair_days}:{strategy6.get('daily_pair_coverage_days')}")
    strategy8 = manifest.get("strategy_lifecycle", {}).get("strategy8_monthly_macro_strangle", {})
    if int(strategy8.get("monthly_pair_coverage_days", -1)) != monthly_pair_days:
        raise RuntimeError(f"MONTHLY_PAIR_COVERAGE_MISMATCH:{monthly_pair_days}:{strategy8.get('monthly_pair_coverage_days')}")
    return {
        "status": "PASS_WITH_LIMITATION",
        "rules_version": RULES_VERSION,
        "market_rule_limitations": limitations,
        "dataset": manifest["dataset"],
        "date_start": manifest["date_start"],
        "date_end": manifest["date_end"],
        "date_end_exclusive": manifest["date_end_exclusive"],
        "trading_days": len(expected_days),
        "events": total_events,
        "weekly_covered_days": weekly_covered_days,
        "daily_pair_coverage_days": daily_pair_days,
        "monthly_pair_coverage_days": monthly_pair_days,
        "option_master_sha256": master_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    result = validate_dataset(Path.cwd(), Path(args.dataset))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
