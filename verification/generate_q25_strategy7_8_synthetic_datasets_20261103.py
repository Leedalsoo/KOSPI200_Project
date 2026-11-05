from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/derived_scenario/q25_strategy7_8"
PROFILE = ROOT / "config/validation_only/q25_strategy7_8_risk_profiles.v1.json"
MULTIPLIER = Decimal("250000")
TIMES = ("09:00:00", "10:00:00", "11:00:00", "13:00:00", "14:30:00")
# Synthetic quote marks are deliberately narrow, two-sided, and varied to exercise
# entry, per-leg stop, and post-2x trailing observations. They are not market estimates.
MARKS = {
    "PUT": (Decimal("1.20"), Decimal("1.45"), Decimal("2.60"), Decimal("2.30"), Decimal("0.55")),
    "CALL": (Decimal("1.10"), Decimal("1.35"), Decimal("2.40"), Decimal("2.10"), Decimal("0.50")),
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def build_rows(strategy: str):
    rows = []
    if strategy == "strategy7_weekly":
        groups = [("S7_MON_20261109", "20261109", "MONDAY_WEEKLY"),
                  ("S7_THU_20261112", "20261112", "THURSDAY_WEEKLY")]
        base = datetime(2026, 11, 3, tzinfo=timezone.utc)
        for group_id, expiry, series in groups:
            for leg in ("PUT", "CALL"):
                strike = Decimal("487.5") if leg == "PUT" else Decimal("512.5")
                for i, clock in enumerate(TIMES):
                    ts = base + timedelta(days=i, hours=9)
                    bid = MARKS[leg][i] * Decimal("0.95")
                    ask = MARKS[leg][i] * Decimal("1.05")
                    rows.append(make_row(strategy, group_id, expiry, series, leg, strike, ts, bid, ask, i, 10))
    else:
        group_id, expiry, series = "S8_MONTHLY_20261119", "20261119", "MONTHLY"
        base = datetime(2026, 11, 3, tzinfo=timezone.utc)
        for regime in ("NORMAL", "HIGH_VOL"):
            for leg in ("PUT", "CALL"):
                strike = Decimal("485") if leg == "PUT" else Decimal("515")
                for i, clock in enumerate(TIMES):
                    ts = base + timedelta(days=i, hours=9)
                    scale = Decimal("1.0") if regime == "NORMAL" else Decimal("1.35")
                    mark = MARKS[leg][i] * scale
                    bid, ask = mark * Decimal("0.95"), mark * Decimal("1.05")
                    rows.append(make_row(strategy, group_id + "_" + regime, expiry, series, leg, strike, ts, bid, ask, i, 12 if regime == "NORMAL" else 10, regime))
    return rows

def make_row(strategy, group_id, expiry, series, leg, strike, ts, bid, ask, seq, dte, regime="NORMAL"):
    symbol = f"SYNTHETIC_CONTRACT:{strategy}:{expiry}:{leg}:{strike}"
    return {
        "schema": "reference-canonical-market-tick-v1",
        "provenance": "SYNTHETIC",
        "tick": {
            "timestamp": ts.isoformat(), "underlying_price": 500.0,
            "underlying_symbol": "KOSPI200_SYNTHETIC",
            "underlying_observed_hour": ts.strftime("%Y%m%d%H"),
            "underlying_source": "SYNTHETIC:q25-s7-s8-generator-v1",
            "strike_price": float(strike), "option_type": leg,
            "contract_multiplier": float(MULTIPLIER),
            "bid_price": float(bid.quantize(Decimal("0.01"))),
            "ask_price": float(ask.quantize(Decimal("0.01"))),
            "last_price": float(((bid+ask)/2).quantize(Decimal("0.01"))),
            "volume": 100 + seq, "seq_id": seq + 1,
            "expiry": expiry, "symbol": symbol, "instrument_id": symbol,
            "option_source": "SYNTHETIC", "implied_volatility": 0.25 if regime=="NORMAL" else 0.42,
            "delta": -0.35 if leg=="PUT" else 0.35, "gamma": 0.01,
            "theta": -0.01, "vega": 0.2, "contract_class": "weekly" if strategy=="strategy7_weekly" else "monthly",
            "product_series": series
        },
        "scenario_metadata": {
            "source_type": "SYNTHETIC", "runtime_eligible": False, "validation_only": True,
            "scenario_id": f"Q25_{strategy.upper()}_LIFECYCLE_V1",
            "group_id": group_id, "leg_id": leg.lower(), "regime": regime,
            "dte_trading_days": dte, "expiry_is_authoritative": False,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "purpose": "Validation-only quote and contract scenario; not an exchange or KIS master record."
        }
    }

def write_dataset(strategy: str):
    rows = build_rows(strategy)
    folder = BASE / strategy
    folder.mkdir(parents=True, exist_ok=True)
    dataset = folder / "20261103.jsonl"
    raw = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode()
    dataset.write_bytes(raw)
    group_timeline = {}
    max_spread = Decimal("0")
    for row in rows:
        t = row["tick"]; m = row["scenario_metadata"]
        key = m["group_id"]
        index = int(t["seq_id"])  # each group/leg has the same deterministic sequence
        group_timeline.setdefault(key, {}).setdefault(index, {})[m["leg_id"]] = Decimal(str(t["ask_price"])) * MULTIPLIER
        spread = (Decimal(str(t["ask_price"])) - Decimal(str(t["bid_price"]))) / Decimal(str(t["ask_price"]))
        max_spread = max(max_spread, spread)
    group_totals = {
        key: max(sum(legs.values()) for legs in timeline.values() if set(legs)=={"put","call"})
        for key, timeline in group_timeline.items()
    }
    max_gross = max(group_totals.values())
    if strategy == "strategy7_weekly":
        concurrent_by_index = {}
        for timeline in group_timeline.values():
            for index, legs in timeline.items():
                if set(legs)=={"put","call"}:
                    concurrent_by_index[index] = concurrent_by_index.get(index, Decimal("0")) + sum(legs.values())
        total_gross = max(concurrent_by_index.values())
    else:
        total_gross = max_gross
    manifest = {
        "schema_version": "q25-validation-only-synthetic-manifest-v1",
        "scenario_id": f"Q25_{strategy.upper()}_LIFECYCLE_V1",
        "strategy_id": strategy, "source_type": "SYNTHETIC",
        "validation_only": True, "runtime_eligible": False,
        "expiry_is_authoritative": False, "contract_identity_authority": "SYNTHETIC_ONLY",
        "dataset_path": str(dataset.relative_to(ROOT)).replace("\\","/"),
        "dataset_sha256": sha256(raw), "rows": len(rows),
        "groups": sorted(group_totals), "group_gross_premium_krw": {k:int(v) for k,v in group_totals.items()},
        "max_group_gross_premium_krw": int(max_gross),
        "max_concurrent_gross_premium_krw": int(total_gross),
        "max_bid_ask_spread_ratio": str(max_spread),
        "quote_quality_limit_ratio": "0.20",
        "provenance": "All quote, contract, expiry, DTE and regime fields are generated synthetic test inputs."
    }
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return manifest

def main():
    manifests = [write_dataset("strategy7_weekly"), write_dataset("strategy8_monthly")]
    s7, s8 = manifests
    # Validation budgets are derived from the generated maximum exposure with 25% headroom,
    # rounded up to the next 100,000 KRW. Original 250k operational proposal is recorded only
    # as a comparison baseline; it is not modified or used by this test profile.
    def budget(value):
        return int((Decimal(value) * Decimal("1.25") / Decimal("100000")).to_integral_value(rounding=ROUND_CEILING) * Decimal("100000"))
    profiles = {
        "schema_version": "q25-validation-only-risk-profile-v1",
        "currency": "KRW", "validation_only": True, "runtime_eligible": False,
        "allow_live_orders": False, "allow_kis_api": False, "allow_real_account": False,
        "risk_checks_enabled": True, "enforcement_mode": "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT",
        "operational_config_path": "config/risk/option-hedge-risk.v1.json",
        "operational_config_mutated": False,
        "profiles": {
            "track7_weekly_insurance": {
                "max_concurrent_groups": 2,
                "max_gross_premium_outlay_krw": budget(s7["max_concurrent_gross_premium_krw"]),
                "max_loss_krw": budget(s7["max_concurrent_gross_premium_krw"]),
                "operational_reference_limit_krw": 250000,
                "budget_basis": "sum of both BUY legs across two independent expiry groups; max loss capped at premium paid",
                "dataset_manifest": "data/derived_scenario/q25_strategy7_8/strategy7_weekly/manifest.json"
            },
            "track8_monthly_strangle": {
                "max_concurrent_groups": 1,
                "max_gross_premium_outlay_krw": budget(s8["max_concurrent_gross_premium_krw"]),
                "max_loss_krw": budget(s8["max_concurrent_gross_premium_krw"]),
                "operational_reference_limit_krw": 250000,
                "budget_basis": "one CALL + one PUT BUY pair; max loss capped at premium paid; no macro scale-up",
                "dataset_manifest": "data/derived_scenario/q25_strategy7_8/strategy8_monthly/manifest.json",
                "entry_policy": "Use confirmed No.1169 DTE >= 10 trading days; 200,000 KRW minimum-budget gate retired. This profile does not change strategy code."
            }
        },
        "audit_fields_required": ["computed_gross_premium_krw","computed_max_loss_krw","computed_concurrent_exposure_krw","operational_reference_overage_krw","validation_budget_overage_krw","run_id","scenario_id","manifest_sha256","dataset_sha256"]
    }
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(profiles, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"manifests":manifests,"profile_path":str(PROFILE.relative_to(ROOT)),"profiles":profiles["profiles"]},indent=2))
if __name__ == "__main__": main()
