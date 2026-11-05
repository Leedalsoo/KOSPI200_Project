from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "derived_scenario" / "q25_strategy7_8_v2"
TRADING_DAYS = tuple(
    date.fromisoformat(value)
    for value in (
        "2026-11-02", "2026-11-03", "2026-11-04",
        "2026-11-05", "2026-11-06", "2026-11-09",
        "2026-11-10", "2026-11-11", "2026-11-12",
    )
)
CALENDAR_DAYS = (date(2026, 10, 30), *TRADING_DAYS, date(2026, 11, 13))
SESSION_TIMES = tuple(
    time.fromisoformat(value)
    for value in ("08:45:00", "09:00:00", "09:10:00", "10:00:00", "13:00:00", "15:10:00")
)
KST = timezone(timedelta(hours=9))
MULTIPLIER = Decimal("250000")
PUT_MARKS = tuple(map(Decimal, ("1.20", "1.45", "2.60", "2.30", "0.55", "0.80", "0.75", "0.70", "0.60")))
CALL_MARKS = tuple(map(Decimal, ("1.10", "1.35", "2.40", "2.10", "0.50", "0.70", "0.65", "0.60", "0.55")))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row(strategy: str, group_id: str, expiry: str, series: str, leg: str,
         strike: Decimal, observed_at: datetime, mark: Decimal, seq: int,
         dte: int, regime: str = "NORMAL", entry_date: str | None = None) -> dict:
    bid = (mark * Decimal("0.95")).quantize(Decimal("0.01"))
    ask = (mark * Decimal("1.05")).quantize(Decimal("0.01"))
    symbol = f"SYNTHETIC_CONTRACT:{strategy}:{expiry}:{leg}:{strike}"
    return {
        "schema": "reference-canonical-market-tick-v1",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "tick": {
            "timestamp": observed_at.isoformat(),
            "underlying_price": 500.0,
            "underlying_symbol": "KOSPI200_SYNTHETIC",
            "underlying_observed_hour": observed_at.strftime("%Y%m%d%H"),
            "underlying_source": "SYNTHETIC:q25-s7-s8-generator-v2",
            "strike_price": float(strike),
            "option_type": leg,
            "contract_multiplier": float(MULTIPLIER),
            "bid_price": float(bid),
            "ask_price": float(ask),
            "last_price": float(((bid + ask) / 2).quantize(Decimal("0.01"))),
            "volume": 100 + seq,
            "seq_id": seq + 1,
            "expiry": expiry,
            "symbol": symbol,
            "instrument_id": symbol,
            "synthetic_contract_id": symbol,
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "source_instrument_code": symbol,
            "option_source": "SYNTHETIC",
            "implied_volatility": 0.25 if regime == "NORMAL" else 0.42,
            "delta": -0.35 if leg == "PUT" else 0.35,
            "gamma": 0.01,
            "theta": -0.01,
            "vega": 0.2,
            "contract_class": "weekly" if strategy == "strategy7_weekly" else "monthly",
        },
        "scenario_metadata": {
            "instrument_family": "STANDARD",
            "product_series": series,
            "source_type": "DERIVED_SCENARIO",
            "runtime_eligible": False,
            "validation_only": True,
            "scenario_id": f"Q25_{strategy.upper()}_LIFECYCLE_V2",
            "group_id": group_id,
            "leg_id": leg.lower(),
            "regime": regime,
            "dte_trading_days": dte,
            "expiry_is_authoritative": False,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "group_entry_date": entry_date,
            "purpose": "Validation-only quote and contract scenario; not an exchange or KIS master record.",
        },
    }


def _build(strategy: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    seq = 0
    if strategy == "strategy7_weekly":
        groups = (
            ("S7_MON_20261109", "20261109", "MONDAY_WEEKLY", "2026-11-02"),
            ("S7_THU_20261112", "20261112", "THURSDAY_WEEKLY", "2026-11-05"),
        )
        for group_id, expiry, series, entry_date in groups:
            for day_index, day in enumerate(TRADING_DAYS):
                for time_index, session_time in enumerate(SESSION_TIMES):
                    observed_at = datetime.combine(day, session_time, KST)
                    mark_index = min(day_index, len(PUT_MARKS) - 1)
                    for leg, strike, marks in (
                        ("PUT", Decimal("487.5"), PUT_MARKS),
                        ("CALL", Decimal("512.5"), CALL_MARKS),
                    ):
                        seq += 1
                        rows.append(_row(
                            strategy, group_id, expiry, series, leg, strike,
                            observed_at, marks[mark_index], seq, 10,
                            entry_date=entry_date,
                        ))
    else:
        expiry = "20261119"
        dte_by_day = (13, 12, 11, 10, 9, 8, 7, 6, 5)
        for regime in ("NORMAL", "HIGH_VOL"):
            scale = Decimal("1.0") if regime == "NORMAL" else Decimal("1.35")
            group_id = f"S8_MONTHLY_20261119_{regime}"
            for day_index, day in enumerate(TRADING_DAYS):
                for time_index, session_time in enumerate(SESSION_TIMES):
                    observed_at = datetime.combine(day, session_time, KST)
                    for leg, strike, marks in (
                        ("PUT", Decimal("485"), PUT_MARKS),
                        ("CALL", Decimal("515"), CALL_MARKS),
                        ("PUT", Decimal("500"), PUT_MARKS),
                        ("CALL", Decimal("500"), CALL_MARKS),
                    ):
                        seq += 1
                        rows.append(_row(
                            strategy, group_id, expiry, "MONTHLY", leg, strike,
                            observed_at, marks[min(day_index, len(marks) - 1)] * scale,
                            seq, dte_by_day[day_index], regime,
                            entry_date="2026-11-02",
                        ))
    raw = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in sorted(rows, key=lambda item: (
            item["tick"]["timestamp"],
            item["scenario_metadata"]["group_id"],
            item["scenario_metadata"]["leg_id"],
        ))
    )
    group_ids = sorted({row["scenario_metadata"]["group_id"] for row in rows})
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "scenario_id": f"Q25_{strategy.upper()}_LIFECYCLE_V2",
        "strategy_id": strategy,
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "expiry_is_authoritative": False,
        "contract_identity_authority": "SYNTHETIC_ONLY",
        "dataset_path": f"data/derived_scenario/q25_strategy7_8_v2/{strategy}/20261103.jsonl",
        "dataset_sha256": _sha(raw),
        "output_sha256": _sha(raw),
        "output_bytes": len(raw),
        "output_path": f"data/derived_scenario/q25_strategy7_8_v2/{strategy}/20261103.jsonl",
        "rows": len(rows),
        "groups": group_ids,
        "trading_calendar": {
            "calendar_id": f"{strategy.upper()}_SYNTHETIC_CALENDAR_V2",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": [day.isoformat() for day in CALENDAR_DAYS],
            "provenance": "Explicit scenario schedule for validation-only tests; not a KRX/KIS holiday or session calendar.",
        },
        "session_times_kst": [value.isoformat() for value in SESSION_TIMES],
        "strategy_policy_inputs": {
            "strategy7_group_entry_dates": {
                "S7_MON_20261109": "2026-11-02",
                "S7_THU_20261112": "2026-11-05",
            } if strategy == "strategy7_weekly" else None,
            "strategy8_dte_by_trading_day": list(dte_by_day) if strategy == "strategy8_monthly" else None,
            "strategy8_retry_window_trading_days": 3 if strategy == "strategy8_monthly" else None,
            "strategy8_third_day_cutoff_kst": "15:00" if strategy == "strategy8_monthly" else None,
        },
        "provenance_note": "All quotes, contract identities, expiry and trading calendar are generated synthetic test inputs.",
    }
    return rows, manifest, raw


def main() -> None:
    for strategy in ("strategy7_weekly", "strategy8_monthly"):
        rows, manifest, raw = _build(strategy)
        folder = BASE / strategy
        folder.mkdir(parents=True, exist_ok=True)
        dataset_path = folder / "20261103.jsonl"
        manifest_path = folder / "manifest.json"
        dataset_path.write_bytes(raw)
        manifest["dataset_path"] = str(dataset_path.relative_to(ROOT)).replace("\\", "/")
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{strategy}: rows={len(rows)} sha256={manifest['dataset_sha256']}")
        print(f"dataset={dataset_path.relative_to(ROOT)}")
        print(f"manifest={manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
