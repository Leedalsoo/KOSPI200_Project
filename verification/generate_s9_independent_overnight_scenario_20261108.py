from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ID = "S9_INDEPENDENT_ATM_OVERNIGHT_001"
DATA_DIR = ROOT / "data/derived_scenario/q25_s9_independent_overnight_20261108"
DATA_FILE = DATA_DIR / "20261106.jsonl"
RISK_DIR = ROOT / "config/validation_only/q25_s9_independent_overnight_20261108"
RISK_FILE = RISK_DIR / "risk_profile.json"
CONTRACT_PROFILE = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"REFUSE_OVERWRITE:{path.relative_to(ROOT)}")
    path.write_bytes(data)


def tick(seq: int, timestamp: str, option_type: str, bid: float, ask: float, last: float,
         underlying: float, dte: int) -> dict:
    strike = 500.0
    expiry = "20261112"
    code = f"S9-{option_type}-{expiry}-{int(strike)}"
    return {
        "schema": "reference-canonical-market-tick-v1",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "tick": {
            "timestamp": timestamp,
            "underlying_price": underlying,
            "underlying_symbol": "KOSPI200",
            "underlying_observed_hour": timestamp[11:19],
            "underlying_source": "SYNTHETIC:DERIVED_SCENARIO",
            "strike_price": strike,
            "option_type": option_type,
            "contract_multiplier": 100000.0,
            "bid_price": bid,
            "ask_price": ask,
            "last_price": last,
            "volume": 100,
            "seq_id": seq,
            "expiry": expiry,
            "symbol": code,
            "option_observed_hour": timestamp[11:19],
            "option_source": "SYNTHETIC:DERIVED_SCENARIO",
            "instrument_id": None,
            "synthetic_contract_id": f"SYNTHETIC_CONTRACT:S9-{expiry}-{option_type}-{int(strike)}",
            "source_instrument_code": code,
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "contract_class": "monthly",
            "contract_month": "202611",
            "theoretical_mid_price": last,
            "intrinsic_value": 0.0,
            "time_value": last,
            "time_to_expiry_seconds": dte * 86400,
            "implied_volatility": 0.20,
            "delta": -0.50 if option_type == "PUT" else 0.50,
            "gamma": 0.01,
            "theta": -0.01,
            "vega": 0.10,
        },
        "scenario_metadata": {
            "scenario_id": SCENARIO_ID,
            "validation_only": True,
            "regime": "NORMAL",
            "dte_trading_days": dte,
            "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "instrument_family": "STANDARD",
            "product_series": "MONTHLY",
            "group_id": "S9-OVERNIGHT-001",
        },
    }


def main() -> None:
    contract_hash = digest(CONTRACT_PROFILE.read_bytes())
    risk = {
        "schema_version": "track9-independent-virtual-risk-profile-v1",
        "profile_id": "S9_INDEPENDENT_OVERNIGHT_VIRTUAL_RISK_V1",
        "provenance": "SYNTHETIC",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "allow_kis_api": False,
        "allow_real_vts": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "virtual_broker_orders_allowed": True,
        "operational_config_mutated": False,
        "risk_checks_enabled": True,
        "initial_capital_krw": 10000000,
        "account_source": "SYNTHETIC:VIRTUAL_ACCOUNT",
        "fee_assumption": {"fee_per_contract_krw": 0, "provenance": "SYNTHETIC_ZERO_FEE_ASSUMPTION"},
        "limits": {
            "max_gross_premium_krw": 5000000,
            "max_loss_krw": 5000000,
            "max_quantity_per_leg": 1,
            "max_concurrent_groups": 1,
            "max_quote_age_seconds": 5,
        },
        "audit_fields_required": [
            "run_id", "scenario_id", "manifest_sha256", "dataset_sha256",
            "risk_profile_sha256", "group_id", "purpose", "gross_premium_krw", "status",
        ],
        "notes": [
            "Every amount and limit is synthetic validation input, not an operational account or risk limit.",
            "The virtual broker is enabled only inside this manifest-bound replay; KIS, REAL_VTS, Live and real accounts remain denied.",
            "The zero-fee assumption is synthetic and must be replaced by an official fee schedule before real-account validation.",
        ],
    }
    risk_bytes = (json.dumps(risk, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    risk_hash = digest(risk_bytes)
    records = [
        tick(1, "2026-11-06T15:00:00+09:00", "PUT", 4.8, 5.0, 4.9, 500.4, 4),
        tick(2, "2026-11-06T15:00:00+09:00", "CALL", 5.2, 5.4, 5.3, 500.4, 4),
        tick(3, "2026-11-09T09:00:00+09:00", "PUT", 10.0, 10.2, 10.1, 506.0, 3),
        tick(4, "2026-11-09T09:00:00+09:00", "CALL", 11.0, 11.2, 11.1, 506.0, 3),
    ]
    dataset_bytes = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in records)
    dataset_hash = digest(dataset_bytes)
    manifest = {
        "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
        "dataset_id": "Q25_S9_INDEPENDENT_ATM_OVERNIGHT_20261108",
        "scenario_id": SCENARIO_ID,
        "scenario_ids": [SCENARIO_ID],
        "scenario_count": 1,
        "scenario_regimes": {SCENARIO_ID: "NORMAL"},
        "source_type": "DERIVED_SCENARIO",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "expiry_is_authoritative": False,
        "official_data_status": {
            "official_contract_multiplier": "MISSING",
            "official_tradability": "MISSING",
            "official_previous_close": "MISSING",
            "official_next_session_open": "MISSING",
            "official_option_quotes": "MISSING",
            "official_trading_calendar": "MISSING",
            "official_virtual_account": "MISSING",
            "kis_live_order_access": "MISSING",
        },
        "strategy_id": "track9_event_overnight_insurance",
        "strategy_code_version": "3.0",
        "strategy_policy": {
            "entry_evaluation_time": "15:00:00",
            "entry_evaluation_timezone": "Asia/Seoul",
            "entry_instrument_selection": "NEAREST_EXPIRY_SAME_STRIKE_ATM_PUT_CALL",
            "pair_quantity_per_leg": 1,
            "opening_move_threshold": "0.01",
            "opening_move_metric": "ABS((next_session_open-previous_close)/previous_close)",
            "at_or_above_threshold_action": "CLOSE_INSURANCE",
            "below_threshold_action": "STOP_LOSS",
            "trailing_profit_exit": "NOT_USED",
        },
        "orders_allowed": False,
        "validation_identity_namespace": "SYNTHETIC_CONTRACT:S9-",
        "dataset_file": DATA_FILE.name,
        "output_path": DATA_FILE.relative_to(ROOT).as_posix(),
        "output_sha256": dataset_hash,
        "dataset_sha256": dataset_hash,
        "output_bytes": len(dataset_bytes),
        "rows": len(records),
        "entry_date": "2026-11-06",
        "next_session_date": "2026-11-09",
        "expiry": "20261112",
        "synthetic_reference_inputs": {
            "previous_official_close": "500",
            "next_session_official_open": "506",
            "previous_official_close_provenance": "SYNTHETIC",
            "next_session_official_open_provenance": "SYNTHETIC",
        },
        "contract_profile_path": CONTRACT_PROFILE.relative_to(ROOT).as_posix(),
        "contract_profile_sha256": contract_hash,
        "risk_profile_path": RISK_FILE.relative_to(ROOT).as_posix(),
        "risk_profile_sha256": risk_hash,
        "trading_calendar": {
            "calendar_id": "S9_SYNTHETIC_CALENDAR_20261108",
            "source_type": "SYNTHETIC",
            "authoritative": False,
            "timezone": "Asia/Seoul",
            "trading_days": ["2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"],
        },
        "notes": [
            "Standalone S9 ATM PUT+CALL overnight insurance; no S1 short-PUT linkage or S1 strategy code is used.",
            "Contract identities, multiplier, tradability, quotes, previous close, next open, calendar, account and risk limits are all explicitly SYNTHETIC.",
            "The 1.2% next-session opening move exercises the P0 >=1% close-insurance branch.",
            "No official contract multiplier, listing/tradability, KIS account, REAL_VTS, Live or real order is asserted or accessed.",
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    write_new(DATA_FILE, dataset_bytes)
    write_new(RISK_FILE, risk_bytes)
    write_new(DATA_DIR / "manifest.json", manifest_bytes)
    write_new(DATA_DIR / "20261106.jsonl.sha256", (dataset_hash + "  20261106.jsonl\n").encode())
    write_new(DATA_DIR / "manifest.json.sha256", (digest(manifest_bytes) + "  manifest.json\n").encode())
    write_new(RISK_FILE.with_suffix(".json.sha256"), (risk_hash + "  risk_profile.json\n").encode())

    print(json.dumps({
        "result": "S9_SYNTHETIC_SCENARIO_CREATED",
        "scenario_id": SCENARIO_ID,
        "rows": len(records),
        "dataset_sha256": dataset_hash,
        "manifest_sha256": digest(manifest_bytes),
        "contract_profile_sha256": contract_hash,
        "risk_profile_sha256": risk_hash,
        "data_path": DATA_DIR.relative_to(ROOT).as_posix(),
        "risk_profile_path": RISK_FILE.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
