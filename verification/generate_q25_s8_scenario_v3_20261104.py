from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "derived_scenario" / "q25_s8_v3"
RISK_BASE = ROOT / "config" / "validation_only" / "q25_s8_v3"
TRADING_DAYS = tuple(date.fromisoformat(value) for value in (
    "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
    "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11",
    "2026-11-12",
))
CALENDAR_DAYS = tuple(date.fromisoformat(value) for value in (
    "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
    "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11",
    "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17",
    "2026-11-18", "2026-11-19",
))
SESSION_TIMES = tuple(time.fromisoformat(x) for x in (
    "08:45:00", "09:00:00", "09:10:00", "10:00:00", "13:00:00", "15:10:00"
))
KST = timezone(timedelta(hours=9))
MULTIPLIER = Decimal("250000")
MARKS = {
    "PUT": tuple(map(Decimal, ("1.20", "1.45", "2.60", "2.30", "0.55", "0.80", "0.75", "0.70", "0.60"))),
    "CALL": tuple(map(Decimal, ("1.10", "1.35", "2.40", "2.10", "0.50", "0.70", "0.65", "0.60", "0.55"))),
}
DTE = (13, 12, 11, 10, 9, 8, 7, 6, 5)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_scenario(regime: str) -> None:
    folder = BASE / "strategy8_monthly" / regime.lower()
    folder.mkdir(parents=True, exist_ok=False)
    rows = []
    seq = 0
    scale = Decimal("1.35") if regime == "HIGH_VOL" else Decimal("1.0")
    scenario_id = f"Q25_S8_MONTHLY_V3_{regime}"
    group_id = f"S8_MONTHLY_20261119_{regime}_V3"
    expiry = "20261119"
    for day_index, day in enumerate(TRADING_DAYS):
        for session_time in SESSION_TIMES:
            observed = datetime.combine(day, session_time, KST)
            for leg, strike in (("PUT", Decimal("485")), ("CALL", Decimal("515")),
                                ("PUT", Decimal("500")), ("CALL", Decimal("500"))):
                seq += 1
                mark = MARKS[leg][day_index] * scale
                bid = (mark * Decimal("0.95")).quantize(Decimal("0.01"))
                ask = (mark * Decimal("1.05")).quantize(Decimal("0.01"))
                identity = f"SYNTHETIC_CONTRACT:S8V3:{regime}:{expiry}:{leg}:{strike}"
                rows.append({
                    "schema": "reference-canonical-market-tick-v1",
                    "provenance": "DERIVED_SCENARIO",
                    "synthetic": True,
                    "tick": {
                        "timestamp": observed.isoformat(),
                        "underlying_price": 500.0,
                        "underlying_symbol": "KOSPI200_SYNTHETIC",
                        "underlying_observed_hour": observed.strftime("%Y%m%d%H"),
                        "underlying_source": "SYNTHETIC:q25-s8-v3-scenario-generator",
                        "strike_price": float(strike),
                        "option_type": leg,
                        "contract_multiplier": float(MULTIPLIER),
                        "bid_price": float(bid),
                        "ask_price": float(ask),
                        "last_price": float(((bid + ask) / 2).quantize(Decimal("0.01"))),
                        "volume": 100 + seq,
                        "seq_id": seq,
                        "expiry": expiry,
                        "symbol": identity,
                        "instrument_id": identity,
                        "synthetic_contract_id": identity,
                        "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
                        "source_instrument_code": identity,
                        "option_source": "SYNTHETIC",
                        "implied_volatility": 0.25 if regime == "NORMAL" else 0.42,
                        "delta": -0.35 if leg == "PUT" else 0.35,
                        "gamma": 0.01,
                        "theta": -0.01,
                        "vega": 0.2,
                        "contract_class": "monthly",
                    },
                    "scenario_metadata": {
                        "instrument_family": "STANDARD",
                        "product_series": "MONTHLY",
                        "source_type": "DERIVED_SCENARIO",
                        "runtime_eligible": False,
                        "validation_only": True,
                        "scenario_id": scenario_id,
                        "group_id": group_id,
                        "leg_id": leg.lower(),
                        "regime": regime,
                        "dte_trading_days": DTE[day_index],
                        "expiry_is_authoritative": False,
                        "contract_identity_authority": "SYNTHETIC_ONLY",
                        "group_entry_date": "2026-11-02",
                        "purpose": "Isolated S8 validation-only scenario; not exchange or KIS master data.",
                    },
                })
    raw = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    dataset_name = "20261104.jsonl"
    dataset_path = folder / dataset_name
    dataset_path.write_bytes(raw)
    rel_manifest = f"data/derived_scenario/q25_s8_v3/strategy8_monthly/{regime.lower()}/manifest.json"
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "scenario_id": scenario_id,
        "strategy_id": "strategy8_monthly",
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "validation_identity_namespace": f"SYNTHETIC_CONTRACT:S8V3:{regime}:",
        "expiry_is_authoritative": False,
        "contract_identity_authority": "SYNTHETIC_ONLY",
        "dataset_path": f"{folder.relative_to(ROOT).as_posix()}/{dataset_name}",
        "dataset_sha256": digest(raw),
        "output_sha256": digest(raw),
        "output_bytes": len(raw),
        "output_path": f"{folder.relative_to(ROOT).as_posix()}/{dataset_name}",
        "rows": len(rows),
        "groups": [group_id],
        "scenario_regime": regime,
        "trading_calendar": {
            "calendar_id": f"S8_V3_{regime}_SYNTHETIC_CALENDAR",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": [d.isoformat() for d in CALENDAR_DAYS],
            "provenance": "Explicit validation-only synthetic schedule; not KRX/KIS calendar.",
        },
        "session_times_kst": [x.isoformat() for x in SESSION_TIMES],
        "strategy_policy_inputs": {
            "strategy8_min_entry_dte_trading_days": 10,
            "strategy8_dte_by_trading_day": list(DTE),
            "strategy8_dte_source": "scenario_metadata.dte_trading_days",
            "strategy8_retry_interval_minutes": 10,
            "strategy8_max_attempts_per_leg": 3,
            "strategy8_retry_window_trading_days": 3,
            "strategy8_third_day_cutoff_kst": "15:00",
        },
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    risk_folder = RISK_BASE / regime.lower()
    risk_folder.mkdir(parents=True, exist_ok=False)
    risk = {
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "audit_fields_required": [
            "computed_gross_premium_krw", "computed_max_loss_krw",
            "computed_concurrent_exposure_krw", "operational_reference_overage_krw",
            "validation_budget_overage_krw", "run_id", "scenario_id",
            "manifest_sha256", "dataset_sha256",
        ],
        "currency": "KRW",
        "enforcement_mode": "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT",
        "operational_config_mutated": False,
        "operational_config_path": "config/risk/option-hedge-risk.v1.json",
        "profiles": {
            "track8_monthly_strangle": {
                "budget_basis": "one CALL + one PUT BUY pair; max loss capped at premium paid; no macro scale-up",
                "dataset_manifest": rel_manifest,
                "entry_policy": "No.1169 DTE >= 10 trading days; 200,000 KRW minimum-budget gate retired.",
                "max_concurrent_groups": 1,
                "max_gross_premium_outlay_krw": 2300000,
                "max_loss_krw": 2300000,
                "operational_reference_limit_krw": 250000,
            }
        },
        "risk_checks_enabled": True,
        "runtime_eligible": False,
        "schema_version": "q25-validation-only-risk-profile-v1",
        "validation_only": True,
    }
    (risk_folder / "risk_profile.json").write_text(json.dumps(risk, indent=2) + "\n", encoding="utf-8")
    print(f"{regime}: rows={len(rows)} sha256={digest(raw)}")
    print(f"DATASET={folder.relative_to(ROOT).as_posix()}/{dataset_name}")
    print(f"MANIFEST={rel_manifest}")
    print(f"RISK_PROFILE={(risk_folder / 'risk_profile.json').relative_to(ROOT).as_posix()}")


def main() -> None:
    for regime in ("HIGH_VOL", "NORMAL"):
        build_scenario(regime)


if __name__ == "__main__":
    main()
