from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

PROFILE_ID = "S2-SYNTHETIC-SCENARIO-ONLY-v1"
IDENTITY_PREFIX = "SYNTHETIC_CONTRACT:S2:"
LEG_ORDER = ("inner_put", "inner_call", "outer_put", "outer_call")
PROVENANCE = "SYNTHETIC:DERIVED_SCENARIO"
KIS_OPTION_PRODUCT_SPEC_URL = "https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp"


class Track2SyntheticQuoteScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioBuildResult:
    output_dir: str
    manifest_path: str
    manifest_sha256: str
    quotes_path: str
    quotes_sha256: str
    candidates: int
    quote_rows: int


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise Track2SyntheticQuoteScenarioError(f"INVALID_DECIMAL:{field}") from exc
    if not result.is_finite():
        raise Track2SyntheticQuoteScenarioError(f"NONFINITE_DECIMAL:{field}")
    return result


def _round_tick(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    mode = ROUND_CEILING if rounding == "BUY_CEILING" else ROUND_FLOOR
    return (value / tick).to_integral_value(rounding=mode) * tick


def _identity(registry_id: str, expiry: str, option_type: str, strike: Decimal) -> str:
    key = "|".join((registry_id, expiry, option_type, format(strike, "f")))
    return IDENTITY_PREFIX + sha256(key.encode("utf-8")).hexdigest()[:32]


def validate_quote_snapshot(row: dict[str, Any], *, observed_at: datetime,
                            max_age_seconds: Decimal = Decimal("5"),
                            max_spread: Decimal = Decimal("0.20")) -> None:
    if row.get("source") != PROVENANCE or row.get("provenance") != "SYNTHETIC":
        raise Track2SyntheticQuoteScenarioError("QUOTE_PROVENANCE_INVALID")
    if not str(row.get("instrument_id", "")).startswith(IDENTITY_PREFIX):
        raise Track2SyntheticQuoteScenarioError("SYNTHETIC_CONTRACT_ID_REQUIRED")
    try:
        quote_at = datetime.fromisoformat(str(row["timestamp"]))
        bid, ask = _decimal(row["bid"], "bid"), _decimal(row["ask"], "ask")
    except (KeyError, TypeError, ValueError) as exc:
        raise Track2SyntheticQuoteScenarioError("QUOTE_FIELDS_INVALID") from exc
    if quote_at.tzinfo is None or observed_at.tzinfo is None:
        raise Track2SyntheticQuoteScenarioError("TIMEZONE_AWARE_TIMESTAMPS_REQUIRED")
    age = _decimal((observed_at - quote_at).total_seconds(), "age")
    if age < 0 or age > max_age_seconds:
        raise Track2SyntheticQuoteScenarioError("U21_QUOTE_AGE_BLOCKED")
    if bid <= 0 or ask < bid or ask - bid > max_spread:
        raise Track2SyntheticQuoteScenarioError("U21_QUOTE_SPREAD_BLOCKED")


def build_track2_synthetic_quote_scenario(*, base_dataset: str | Path,
        base_manifest: str | Path, profile_path: str | Path,
        candidates_path: str | Path, output_dir: str | Path) -> ScenarioBuildResult:
    """Build sidecar four-leg quote snapshots. Never mutates the accepted source dataset."""
    from core.risk.track2_synthetic_scenario_profile import load_track2_synthetic_scenario_profile
    from contracts.kis_option_product_spec import (
        KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
        kis_option_contract_multiplier,
    )

    dataset = Path(base_dataset).resolve()
    manifest_path = Path(base_manifest).resolve()
    profile_file = Path(profile_path).resolve()
    candidates_file = Path(candidates_path).resolve()
    target = Path(output_dir).resolve()
    if not dataset.is_dir() or manifest_path.parent != dataset or not manifest_path.is_file():
        raise Track2SyntheticQuoteScenarioError("BASE_DATASET_AND_LOCAL_MANIFEST_REQUIRED")
    if target.exists():
        raise Track2SyntheticQuoteScenarioError("OUTPUT_MUST_BE_NEW_VERSIONED_DIRECTORY")
    profile = load_track2_synthetic_scenario_profile(profile_file)
    base_manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if base_manifest_data.get("schema_version") != "accepted-market-data-runtime-v2":
        raise Track2SyntheticQuoteScenarioError("BASE_MANIFEST_SCHEMA_INVALID")
    if base_manifest_data.get("acceptance") != "ACCEPTED_FOR_PROJECT_VERIFICATION":
        raise Track2SyntheticQuoteScenarioError("BASE_DATASET_NOT_ACCEPTED")
    days = base_manifest_data.get("days")
    if not isinstance(days, list) or not days:
        raise Track2SyntheticQuoteScenarioError("BASE_MANIFEST_DAYS_REQUIRED")
    expected_dates = set()
    for day in days:
        trading_date = str(day.get("date") or "")
        if len(trading_date) != 8 or not trading_date.isdigit() or trading_date in expected_dates:
            raise Track2SyntheticQuoteScenarioError("BASE_MANIFEST_DATE_INVALID")
        expected_dates.add(trading_date)
        partition = dataset / f"{trading_date}.jsonl"
        if not partition.is_file() or _digest(partition) != str(day.get("sha256") or ""):
            raise Track2SyntheticQuoteScenarioError(f"BASE_PARTITION_HASH_MISMATCH:{trading_date}")
        actual_rows = sum(1 for line in partition.read_text(encoding="utf-8").splitlines() if line.strip())
        if actual_rows != day.get("rows"):
            raise Track2SyntheticQuoteScenarioError(f"BASE_PARTITION_ROW_COUNT_MISMATCH:{trading_date}")
    if {item.stem for item in dataset.glob("*.jsonl")} != expected_dates:
        raise Track2SyntheticQuoteScenarioError("BASE_PARTITION_SET_MISMATCH")
    candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
    if not isinstance(candidates, list) or not candidates:
        raise Track2SyntheticQuoteScenarioError("CANDIDATE_LIST_REQUIRED")

    policy = profile.u21_quote_policy
    max_age = _decimal(policy["max_age_seconds"], "max_age_seconds")
    max_spread = _decimal(policy["max_spread"], "max_spread")
    tick = _decimal(policy["tick_size"], "tick_size")
    if max_age != Decimal("5") or max_spread != Decimal("0.20"):
        raise Track2SyntheticQuoteScenarioError("U21_BASELINE_MISMATCH")
    registry = str(base_manifest_data["registry_id"])
    contract_multiplier = kis_option_contract_multiplier("STANDARD")
    if contract_multiplier != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
        raise Track2SyntheticQuoteScenarioError("KIS_STANDARD_MULTIPLIER_SOURCE_MISMATCH")
    rows: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_timestamp_role: set[tuple[str, str]] = set()

    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_OBJECT_REQUIRED")
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen_candidate_ids:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_ID_MISSING_OR_DUPLICATE")
        seen_candidate_ids.add(candidate_id)
        try:
            observed_at = datetime.fromisoformat(str(candidate["observed_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_TIMESTAMP_INVALID") from exc
        if observed_at.tzinfo is None:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_TIMESTAMP_MUST_INCLUDE_TIMEZONE")
        expiry = str(candidate.get("expiry") or "")
        if len(expiry) != 8 or not expiry.isdigit() or expiry < observed_at.strftime("%Y%m%d"):
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_EXPIRY_INVALID")
        underlying = _decimal(candidate.get("underlying_price"), "underlying_price")
        if underlying <= 0:
            raise Track2SyntheticQuoteScenarioError("UNDERLYING_PRICE_MUST_BE_POSITIVE")
        source_observation_id = str(candidate.get("source_observation_id") or "").strip()
        if not source_observation_id:
            raise Track2SyntheticQuoteScenarioError("SOURCE_OBSERVATION_ID_REQUIRED")
        legs = candidate.get("legs")
        if not isinstance(legs, list) or len(legs) != 4:
            raise Track2SyntheticQuoteScenarioError("EXACTLY_FOUR_LEGS_REQUIRED")
        by_role = {str(leg.get("role")): leg for leg in legs if isinstance(leg, dict)}
        if set(by_role) != set(LEG_ORDER) or len(by_role) != 4:
            raise Track2SyntheticQuoteScenarioError("FOUR_DISTINCT_TRACK2_LEG_ROLES_REQUIRED")

        for role in LEG_ORDER:
            leg = by_role[role]
            option_type = "PUT" if role.endswith("put") else "CALL"
            if str(leg.get("option_type", "")).upper() != option_type:
                raise Track2SyntheticQuoteScenarioError(f"LEG_OPTION_TYPE_MISMATCH:{role}")
            strike = _decimal(leg.get("strike"), f"{role}.strike")
            if strike <= 0:
                raise Track2SyntheticQuoteScenarioError(f"LEG_STRIKE_INVALID:{role}")
            uniqueness = (observed_at.isoformat(), role)
            if uniqueness in seen_timestamp_role:
                raise Track2SyntheticQuoteScenarioError("DUPLICATE_TIMESTAMP_LEG")
            seen_timestamp_role.add(uniqueness)
            intrinsic = max(Decimal("0"), strike - underlying) if option_type == "PUT" else max(Decimal("0"), underlying - strike)
            # Explicit deterministic fixture: intrinsic + 2.00 time-value points; not a market model.
            mid = max(tick * 2, _round_tick(intrinsic + Decimal("2.00"), tick, "BUY_CEILING"))
            bid = _round_tick(mid - tick, tick, "SELL_FLOOR")
            ask = _round_tick(mid + tick, tick, "BUY_CEILING")
            instrument_id = _identity(registry, expiry, option_type, strike)
            row = {
                "schema_version": "track2-synthetic-four-leg-quote-v2",
                "candidate_id": candidate_id,
                "leg_role": role,
                "instrument_id": instrument_id,
                "contract_identity_authority": "SYNTHETIC_ONLY_NOT_KIS_MASTER",
                "expiry": expiry,
                "option_type": option_type,
                "strike": format(strike, "f"),
                "contract_product_family": "STANDARD",
                "contract_cycle": "MONTHLY",
                "contract_multiplier": str(contract_multiplier),
                "contract_multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
                "contract_multiplier_source": KIS_OPTION_PRODUCT_SPEC_URL,
                "timestamp": observed_at.isoformat(),
                "bid": format(bid, "f"),
                "ask": format(ask, "f"),
                "last": format(mid, "f"),
                "source": PROVENANCE,
                "provenance": "SYNTHETIC",
                "source_registry_id": registry,
                "source_manifest_sha256": _digest(manifest_path),
                "source_observation_id": source_observation_id,
                "scenario_profile_id": profile.profile_id,
                "scenario_profile_sha256": profile.profile_sha256,
                "model": "DETERMINISTIC_INTRINSIC_PLUS_2_POINT_TIME_VALUE_FIXTURE_v1",
                "limitations": ["Not an observed quote", "Not a KIS-listed contract", "Not for performance or profitability certification"],
            }
            validate_quote_snapshot(row, observed_at=observed_at, max_age_seconds=max_age, max_spread=max_spread)
            rows.append(row)

    target.mkdir(parents=True, exist_ok=False)
    quote_path = target / "four_leg_quotes.jsonl"
    quote_bytes = ("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)).encode("utf-8")
    quote_path.write_bytes(quote_bytes)
    candidate_copy = target / "candidate_inputs.json"
    candidate_bytes = candidates_file.read_bytes()
    candidate_copy.write_bytes(candidate_bytes)
    manifest = {
        "schema_version": "track2-synthetic-four-leg-scenario-manifest-v2",
        "scenario_id": "S2-SYNTHETIC-FOUR-LEG-QUOTES-v2",
        "status": "SYNTHETIC_VALIDATION_ONLY_NOT_MARKET_EVIDENCE",
        "strategy_id": "track2_asymmetric_trap",
        "base_registry_id": registry,
        "base_manifest_sha256": _digest(manifest_path),
        "base_dataset_partitions": [{"date": item["date"], "sha256": item["sha256"], "rows": item["rows"]} for item in base_manifest_data["days"]],
        "contract_specification": {
            "product_family": "STANDARD",
            "contract_cycle": "MONTHLY",
            "multiplier": str(contract_multiplier),
            "multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
            "source_url": KIS_OPTION_PRODUCT_SPEC_URL,
        },
        "profile_id": profile.profile_id,
        "profile_sha256": profile.profile_sha256,
        "u21": {"max_age_seconds": str(max_age), "max_spread": str(max_spread), "tick_size": str(tick)},
        "candidate_input_file": {"path": candidate_copy.name, "sha256": sha256(candidate_bytes).hexdigest()},
        "candidate_count": len(candidates),
        "candidate_role_mapping_contract": {
            "inner_put": "LONG_PUT", "inner_call": "LONG_CALL",
            "outer_put": "SHORT_PUT", "outer_call": "SHORT_CALL",
            "authority": "core/oms/multi_leg_plan.py:build_trap_plan",
            "candidate_role_mapping_provenance": "ALIGNED_TO_EXECUTION_PLAN",
        },
        "source_candidate_inputs_sha256": str(candidates[0].get("source_candidate_inputs_sha256") or ""),
        "quote_rows": len(rows),
        "leg_order": list(LEG_ORDER),
        "quote_file": {"path": quote_path.name, "sha256": sha256(quote_bytes).hexdigest(), "rows": len(rows)},
        "price_model": "intrinsic_value_plus_fixed_2.00_time_value; one_tick_each_side; deterministic fixture only",
        "execution_enabled": False,
        "order_submission_enabled": False,
        "live_api_enabled": False,
        "real_vts_api_enabled": False,
        "limitations": ["Sidecar evidence only; not merged into accepted runtime dataset", "Synthetic IDs do not assert KIS identity", "No actual option pricing or volatility calibration", "No strategy performance or execution certification"],
    }
    manifest_path_out = target / "manifest.json"
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path_out.write_bytes(manifest_bytes)
    return ScenarioBuildResult(str(target), str(manifest_path_out), sha256(manifest_bytes).hexdigest(),
        str(quote_path), sha256(quote_bytes).hexdigest(), len(candidates), len(rows))





def _market_bs_price(spot: float, strike: float, years: float, volatility: float, option_type: str) -> float:
    import math
    if years <= 0:
        return max(spot - strike, 0.0) if option_type == "CALL" else max(strike - spot, 0.0)
    if spot <= 0 or strike <= 0 or volatility <= 0:
        raise Track2SyntheticQuoteScenarioError("MARKET_MODEL_INPUT_INVALID")
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * volatility * volatility * years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    cdf = lambda value: 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))
    if option_type == "CALL":
        return spot * cdf(d1) - strike * cdf(d2)
    if option_type == "PUT":
        return strike * cdf(-d2) - spot * cdf(-d1)
    raise Track2SyntheticQuoteScenarioError("MARKET_MODEL_OPTION_TYPE_INVALID")


def _market_implied_volatility(spot: float, strike: float, years: float, market_mid: float, option_type: str) -> float | None:
    intrinsic = max(spot - strike, 0.0) if option_type == "CALL" else max(strike - spot, 0.0)
    if years <= 0 or market_mid <= intrinsic + 1e-8 or market_mid >= max(spot, strike) * 0.99:
        return None
    low, high = 0.005, 3.0
    try:
        if _market_bs_price(spot, strike, years, high, option_type) < market_mid:
            return None
        for _ in range(90):
            middle = (low + high) / 2.0
            if _market_bs_price(spot, strike, years, middle, option_type) < market_mid:
                low = middle
            else:
                high = middle
        result = (low + high) / 2.0
        return result if 0.01 <= result <= 2.5 else None
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _market_nearest_anchors(anchors: list[dict[str, Any]], *, observed_at: datetime,
                            option_type: str, strike: Decimal, require_iv: bool) -> tuple[list[dict[str, Any]], str]:
    prior = [item for item in anchors if item["observed_at"] <= observed_at]
    if require_iv:
        prior = [item for item in prior if item.get("implied_volatility") is not None]
    if not prior:
        raise Track2SyntheticQuoteScenarioError("MARKET_CALIBRATION_PRIOR_ANCHOR_NOT_FOUND")
    same_type = [item for item in prior if item["option_type"] == option_type]
    pools = (
        (same_type, Decimal("25"), "SAME_TYPE_LOCAL"),
        (same_type, Decimal("40"), "SAME_TYPE_WIDE"),
        (prior, Decimal("40"), "CROSS_TYPE_LOCAL"),
        (same_type, Decimal("60"), "SAME_TYPE_WIDE"),
        (prior, Decimal("60"), "CROSS_TYPE_WIDE"),
        (prior, Decimal("100000"), "SAME_DATE_FALLBACK"),
    )
    for pool, max_distance, label in pools:
        selected = [
            item for item in pool
            if abs(item["strike"] - strike) <= max_distance
            and (observed_at - item["observed_at"]).total_seconds() <= 900
        ]
        if selected:
            selected.sort(key=lambda item: (
                abs(item["strike"] - strike) / Decimal("5")
                + Decimal(str((observed_at - item["observed_at"]).total_seconds())) / Decimal("300"),
                (observed_at - item["observed_at"]).total_seconds(),
                abs(item["strike"] - strike),
            ))
            return selected[:7], label
    raise Track2SyntheticQuoteScenarioError("MARKET_CALIBRATION_ANCHOR_WINDOW_EXHAUSTED")


def build_track2_market_calibrated_quote_scenario(*, base_dataset: str | Path,
        base_manifest: str | Path, profile_path: str | Path,
        candidates_path: str | Path, output_dir: str | Path) -> ScenarioBuildResult:
    """Build causal, market-calibrated synthetic four-leg snapshots from accepted KIS L1 observations."""
    from statistics import median
    from contracts.kis_option_product_spec import (
        KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER,
        kis_option_contract_multiplier,
    )
    from core.risk.track2_synthetic_scenario_profile import load_track2_synthetic_scenario_profile

    dataset = Path(base_dataset).resolve()
    manifest_path = Path(base_manifest).resolve()
    profile_file = Path(profile_path).resolve()
    candidates_file = Path(candidates_path).resolve()
    target = Path(output_dir).resolve()
    if not dataset.is_dir() or manifest_path.parent != dataset or not manifest_path.is_file():
        raise Track2SyntheticQuoteScenarioError("BASE_DATASET_AND_LOCAL_MANIFEST_REQUIRED")
    if target.exists():
        raise Track2SyntheticQuoteScenarioError("OUTPUT_MUST_BE_NEW_VERSIONED_DIRECTORY")
    profile = load_track2_synthetic_scenario_profile(profile_file)
    base_manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (base_manifest_data.get("schema_version") != "accepted-market-data-runtime-v2"
            or base_manifest_data.get("acceptance") != "ACCEPTED_FOR_PROJECT_VERIFICATION"):
        raise Track2SyntheticQuoteScenarioError("BASE_DATASET_NOT_ACCEPTED_RUNTIME_V2")
    days = base_manifest_data.get("days")
    if not isinstance(days, list) or not days:
        raise Track2SyntheticQuoteScenarioError("BASE_MANIFEST_DAYS_REQUIRED")
    expected_dates: set[str] = set()
    partitions: dict[str, Path] = {}
    for day in days:
        date = str(day.get("date") or "")
        if len(date) != 8 or not date.isdigit() or date in expected_dates:
            raise Track2SyntheticQuoteScenarioError("BASE_MANIFEST_DATE_INVALID")
        expected_dates.add(date)
        partition = dataset / f"{date}.jsonl"
        if not partition.is_file() or _digest(partition) != str(day.get("sha256") or ""):
            raise Track2SyntheticQuoteScenarioError(f"BASE_PARTITION_HASH_MISMATCH:{date}")
        actual_rows = sum(1 for line in partition.read_text(encoding="utf-8").splitlines() if line.strip())
        if actual_rows != day.get("rows"):
            raise Track2SyntheticQuoteScenarioError(f"BASE_PARTITION_ROW_COUNT_MISMATCH:{date}")
        partitions[date] = partition
    if {item.stem for item in dataset.glob("*.jsonl")} != expected_dates:
        raise Track2SyntheticQuoteScenarioError("BASE_PARTITION_SET_MISMATCH")

    candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
    if not isinstance(candidates, list) or not candidates:
        raise Track2SyntheticQuoteScenarioError("CANDIDATE_LIST_REQUIRED")
    policy = profile.u21_quote_policy
    max_age = _decimal(policy["max_age_seconds"], "max_age_seconds")
    max_spread = _decimal(policy["max_spread"], "max_spread")
    tick = _decimal(policy["tick_size"], "tick_size")
    if max_age != Decimal("5") or tick != Decimal("0.05"):
        raise Track2SyntheticQuoteScenarioError("MARKET_CALIBRATED_U21_BASELINE_MISMATCH")
    multiplier = kis_option_contract_multiplier("STANDARD")
    if multiplier != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
        raise Track2SyntheticQuoteScenarioError("KIS_STANDARD_MULTIPLIER_SOURCE_MISMATCH")

    # Use actual collected L1 bid/ask/trade fields. Ignore any price field explicitly filled by enrichment.
    anchors_by_date: dict[str, list[dict[str, Any]]] = {}
    all_actual_spreads: list[Decimal] = []
    raw_quote_rows = 0
    skipped_generated_quote_rows = 0
    for date, partition in partitions.items():
        day_anchors: list[dict[str, Any]] = []
        with partition.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                tick_data = record.get("tick") or {}
                meta = record.get("scenario_metadata") or {}
                generated = set(meta.get("generated_fields") or [])
                if "bid_price" in generated or "ask_price" in generated:
                    skipped_generated_quote_rows += 1
                    continue
                try:
                    observed = datetime.fromisoformat(str(tick_data["timestamp"]))
                    expiry = str(tick_data["expiry"])
                    option_type = str(tick_data["option_type"]).upper()
                    strike = _decimal(tick_data["strike_price"], "anchor.strike")
                    spot = _decimal(tick_data["underlying_price"], "anchor.underlying")
                    bid = _decimal(tick_data["bid_price"], "anchor.bid")
                    ask = _decimal(tick_data["ask_price"], "anchor.ask")
                    last = _decimal(tick_data["last_price"], "anchor.last")
                    volume = max(1, int(tick_data.get("volume") or 1))
                except (KeyError, TypeError, ValueError):
                    continue
                if (observed.tzinfo is None or observed.strftime("%Y%m%d") != date
                        or len(expiry) != 8 or option_type not in {"CALL", "PUT"}
                        or strike <= 0 or spot <= 0 or bid <= 0 or ask < bid or last <= 0):
                    continue
                spread = ask - bid
                all_actual_spreads.append(spread)
                raw_quote_rows += 1
                field_provenance = meta.get("field_provenance") or {}
                depth = field_provenance.get("order_book_quantities") or {}
                try:
                    bid_quantity = max(1, int(depth.get("bid_quantity") or 1))
                    ask_quantity = max(1, int(depth.get("ask_quantity") or 1))
                except (TypeError, ValueError):
                    bid_quantity = ask_quantity = 1
                expiry_at = datetime.strptime(expiry, "%Y%m%d").replace(
                    hour=15, minute=20, second=0, microsecond=0, tzinfo=observed.tzinfo,
                )
                years = (expiry_at - observed).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
                market_mid = float((bid + ask) / Decimal("2"))
                iv = _market_implied_volatility(float(spot), float(strike), years, market_mid, option_type)
                day_anchors.append({
                    "observed_at": observed, "expiry": expiry, "option_type": option_type,
                    "strike": strike, "spot": spot, "bid": bid, "ask": ask, "last": last,
                    "spread": spread, "volume": volume, "bid_quantity": bid_quantity,
                    "ask_quantity": ask_quantity, "implied_volatility": iv,
                    "source_observation_id": str(meta.get("source_observation_id") or ""),
                    "source_raw_sha256": str(meta.get("source_raw_sha256") or ""),
                    "source_canonical_sha256": str(meta.get("source_canonical_sha256") or ""),
                    "source_collected_at": str(meta.get("source_collected_at") or ""),
                    "source_line_number": line_number,
                    "source_instrument_code": str(tick_data.get("source_instrument_code") or tick_data.get("symbol") or ""),
                    "underlying_field_provenance": (
                        "KRX_DERIVED_SCENARIO" if "underlying_price" in generated
                        else str(tick_data.get("underlying_source") or "KIS_OBSERVED_OR_ACCEPTED_CANONICAL")
                    ),
                })
        anchors_by_date[date] = day_anchors

    if len(all_actual_spreads) < 20:
        raise Track2SyntheticQuoteScenarioError("INSUFFICIENT_ACCEPTED_ACTUAL_L1_SPREAD_SAMPLES")
    sorted_spreads = sorted(all_actual_spreads)
    p95_index = max(0, min(len(sorted_spreads) - 1, int((len(sorted_spreads) * 0.95) + 0.999999) - 1))
    empirical_p95 = sorted_spreads[p95_index]
    expected_max_spread = empirical_p95 + tick
    if max_spread != expected_max_spread:
        raise Track2SyntheticQuoteScenarioError(
            f"U21_MAX_SPREAD_MUST_MATCH_EMPIRICAL_P95_PLUS_ONE_TICK:{expected_max_spread}"
        )

    rows: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_timestamp_roles: set[tuple[str, str]] = set()
    candidate_calibration: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_OBJECT_REQUIRED")
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen_candidate_ids:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_ID_MISSING_OR_DUPLICATE")
        seen_candidate_ids.add(candidate_id)
        try:
            observed_at = datetime.fromisoformat(str(candidate["observed_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_TIMESTAMP_INVALID") from exc
        if observed_at.tzinfo is None:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_TIMESTAMP_MUST_INCLUDE_TIMEZONE")
        date = observed_at.strftime("%Y%m%d")
        if date not in anchors_by_date:
            raise Track2SyntheticQuoteScenarioError(f"CANDIDATE_SOURCE_DATE_NOT_IN_ACCEPTED_DATASET:{date}")
        expiry = str(candidate.get("expiry") or "")
        if len(expiry) != 8 or not expiry.isdigit() or expiry < date:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_EXPIRY_INVALID")
        spot = _decimal(candidate.get("underlying_price"), "candidate.underlying_price")
        if spot <= 0:
            raise Track2SyntheticQuoteScenarioError("UNDERLYING_PRICE_MUST_BE_POSITIVE")
        candidate_source_id = str(candidate.get("source_observation_id") or "").strip()
        if not candidate_source_id:
            raise Track2SyntheticQuoteScenarioError("SOURCE_OBSERVATION_ID_REQUIRED")
        legs = candidate.get("legs")
        if not isinstance(legs, list) or len(legs) != 4:
            raise Track2SyntheticQuoteScenarioError("EXACTLY_FOUR_LEGS_REQUIRED")
        by_role = {str(leg.get("role")): leg for leg in legs if isinstance(leg, dict)}
        if set(by_role) != set(LEG_ORDER) or len(by_role) != 4:
            raise Track2SyntheticQuoteScenarioError("FOUR_DISTINCT_TRACK2_LEG_ROLES_REQUIRED")
        expiry_at = datetime.strptime(expiry, "%Y%m%d").replace(
            hour=15, minute=20, second=0, microsecond=0, tzinfo=observed_at.tzinfo,
        )
        years = (expiry_at - observed_at).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        if years <= 0:
            raise Track2SyntheticQuoteScenarioError("CANDIDATE_AFTER_OPTION_EXPIRY")
        date_anchors = [item for item in anchors_by_date[date] if item["expiry"] == expiry]
        if not date_anchors:
            raise Track2SyntheticQuoteScenarioError(f"NO_SAME_DATE_EXPIRY_MARKET_ANCHORS:{candidate_id}")
        candidate_rows: list[dict[str, Any]] = []
        candidate_max_anchor_age = 0.0
        for role in LEG_ORDER:
            leg = by_role[role]
            option_type = "PUT" if role.endswith("put") else "CALL"
            if str(leg.get("option_type", "")).upper() != option_type:
                raise Track2SyntheticQuoteScenarioError(f"LEG_OPTION_TYPE_MISMATCH:{role}")
            strike = _decimal(leg.get("strike"), f"{role}.strike")
            if strike <= 0:
                raise Track2SyntheticQuoteScenarioError(f"LEG_STRIKE_INVALID:{role}")
            uniqueness = (observed_at.isoformat(), role)
            if uniqueness in seen_timestamp_roles:
                raise Track2SyntheticQuoteScenarioError("DUPLICATE_TIMESTAMP_LEG")
            seen_timestamp_roles.add(uniqueness)

            # Collapse repeated executions to the latest source observation per actual contract.
            latest_by_symbol: dict[str, dict[str, Any]] = {}
            for anchor in date_anchors:
                if anchor["observed_at"] > observed_at:
                    continue
                code = anchor["source_instrument_code"]
                current = latest_by_symbol.get(code)
                if current is None or anchor["observed_at"] >= current["observed_at"]:
                    latest_by_symbol[code] = anchor
            prior_anchors = list(latest_by_symbol.values())
            iv_anchors, iv_selection = _market_nearest_anchors(
                [item for item in prior_anchors if item.get("implied_volatility") is not None
                 and item["spread"] <= empirical_p95],
                observed_at=observed_at, option_type=option_type, strike=strike, require_iv=True,
            )
            spread_anchors, spread_selection = _market_nearest_anchors(
                [item for item in prior_anchors if item["spread"] <= empirical_p95],
                observed_at=observed_at, option_type=option_type, strike=strike, require_iv=False,
            )
            sigma = float(median(item["implied_volatility"] for item in iv_anchors))
            if not 0.03 <= sigma <= 2.5:
                raise Track2SyntheticQuoteScenarioError(f"CALIBRATED_VOLATILITY_OUT_OF_RANGE:{candidate_id}:{role}")
            theoretical_mid = _market_bs_price(float(spot), float(strike), years, sigma, option_type)
            mid = (Decimal(str(theoretical_mid)) / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
            if mid <= 0:
                raise Track2SyntheticQuoteScenarioError(f"CALIBRATED_OPTION_PRICE_NOT_POSITIVE:{candidate_id}:{role}")
            empirical_spread = Decimal(str(median(float(item["spread"]) for item in spread_anchors)))
            spread_ticks = max(1, int((empirical_spread / tick).to_integral_value(rounding=ROUND_HALF_UP)))
            bid_ticks = spread_ticks // 2
            ask_ticks = spread_ticks - bid_ticks
            bid = mid - Decimal(bid_ticks) * tick
            ask = mid + Decimal(ask_ticks) * tick
            actual_spread = ask - bid
            if bid <= 0 or ask <= bid or actual_spread > max_spread:
                raise Track2SyntheticQuoteScenarioError(
                    f"CALIBRATED_SPREAD_OUTSIDE_VALIDATION_PROFILE:{candidate_id}:{role}:{actual_spread}"
                )
            volume = max(1, int(round(median(item["volume"] for item in spread_anchors))))
            bid_quantity = max(1, int(round(median(item["bid_quantity"] for item in spread_anchors))))
            ask_quantity = max(1, int(round(median(item["ask_quantity"] for item in spread_anchors))))
            anchor_ids = list(dict.fromkeys(
                item["source_observation_id"] for item in (*iv_anchors, *spread_anchors)
                if item.get("source_observation_id")
            ))
            anchor_ages = [int((observed_at - item["observed_at"]).total_seconds())
                           for item in (*iv_anchors, *spread_anchors)]
            candidate_max_anchor_age = max(candidate_max_anchor_age, max(anchor_ages, default=0))
            instrument_id = _identity(str(base_manifest_data["registry_id"]), expiry, option_type, strike)
            row = {
                "schema_version": "track2-market-calibrated-four-leg-quote-v3",
                "candidate_id": candidate_id,
                "leg_role": role,
                "instrument_id": instrument_id,
                "contract_identity_authority": "SYNTHETIC_ONLY_NOT_KIS_MASTER",
                "expiry": expiry,
                "option_type": option_type,
                "strike": format(strike, "f"),
                "contract_product_family": "STANDARD",
                "contract_cycle": "MONTHLY",
                "contract_multiplier": str(multiplier),
                "contract_multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
                "contract_multiplier_source": KIS_OPTION_PRODUCT_SPEC_URL,
                "timestamp": observed_at.isoformat(),
                "bid": format(bid, "f"),
                "ask": format(ask, "f"),
                "last": format(mid, "f"),
                "volume": volume,
                "bid_quantity": bid_quantity,
                "ask_quantity": ask_quantity,
                "source": PROVENANCE,
                "provenance": "SYNTHETIC",
                "source_registry_id": str(base_manifest_data["registry_id"]),
                "source_manifest_sha256": _digest(manifest_path),
                "source_observation_id": candidate_source_id,
                "scenario_profile_id": profile.profile_id,
                "scenario_profile_sha256": profile.profile_sha256,
                "model": "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1",
                "market_calibration": {
                    "method": "PRIOR_SAME_TRADING_DAY_KIS_H0IOCNT0_L1_IV_AND_SPREAD_CALIBRATION",
                    "option_price_anchor": "OBSERVED_BID_ASK_MID",
                    "implied_volatility": sigma,
                    "iv_anchor_selection": iv_selection,
                    "iv_anchor_count": len(iv_anchors),
                    "iv_anchor_observation_ids": [item["source_observation_id"] for item in iv_anchors],
                    "iv_anchor_codes": [item["source_instrument_code"] for item in iv_anchors],
                    "iv_anchor_timestamps": [item["observed_at"].isoformat() for item in iv_anchors],
                    "iv_anchor_ages_seconds": [int((observed_at - item["observed_at"]).total_seconds()) for item in iv_anchors],
                    "iv_anchor_underlying_provenance": [item["underlying_field_provenance"] for item in iv_anchors],
                    "spread_anchor_selection": spread_selection,
                    "spread_anchor_count": len(spread_anchors),
                    "spread_anchor_observation_ids": [item["source_observation_id"] for item in spread_anchors],
                    "spread_anchor_codes": [item["source_instrument_code"] for item in spread_anchors],
                    "spread_anchor_timestamps": [item["observed_at"].isoformat() for item in spread_anchors],
                    "spread_anchor_ages_seconds": [int((observed_at - item["observed_at"]).total_seconds()) for item in spread_anchors],
                    "empirical_anchor_spread_median": format(empirical_spread, "f"),
                    "candidate_underlying_price": format(spot, "f"),
                    "candidate_underlying_provenance": "ACCEPTED_RUNTIME_V2_SCENARIO_INPUT",
                    "day_count": "ACT_365",
                    "risk_free_rate": "0.0_ASSUMPTION",
                    "dividend_yield": "0.0_ASSUMPTION",
                    "expiry_time_kst": "15:20:00",
                    "source_anchor_max_age_seconds": max(anchor_ages, default=0),
                    "target_quote_age_seconds": 0,
                    "volume_basis": "MEDIAN_PRIOR_ANCHOR_TRADE_SIZE",
                    "depth_basis": "MEDIAN_ACCEPTED_SYNTHETIC_L1_DEPTH_PROXY",
                    "last_price_basis": "MODEL_FAIR_VALUE_NOT_OBSERVED_TRADE",
                },
                "model_assumptions": [
                    "Black-Scholes zero-rate/zero-dividend scenario model",
                    "IV inferred from prior same-date accepted KIS L1 bid/ask mid; generated IV fields are ignored",
                    "Cross-option-type IV fallback is explicitly recorded when same-type prior IV is unavailable",
                    "Four target legs are generated as a synchronized validation-only snapshot; source anchors are not simultaneous",
                    "Underlying may contain accepted KRX-derived scenario fills; it is not promoted to KIS authority",
                ],
                "limitations": [
                    "Not an observed four-leg quote or actual KIS execution price",
                    "Target instrument IDs remain synthetic and do not assert KIS-listed identity",
                    "Market model and zero-rate/zero-dividend assumptions are validation-only",
                    "No strategy profitability, actual market execution, REAL_VTS, or Live certification",
                ],
            }
            validate_quote_snapshot(row, observed_at=observed_at,
                max_age_seconds=max_age, max_spread=max_spread)
            rows.append(row)
            candidate_rows.append(row)
        candidate_calibration.append({
            "candidate_id": candidate_id,
            "timestamp": observed_at.isoformat(),
            "quote_rows": len(candidate_rows),
            "max_source_anchor_age_seconds": candidate_max_anchor_age,
            "cross_type_iv_fallback_legs": sum(
                1 for row in candidate_rows
                if str(row["market_calibration"]["iv_anchor_selection"]).startswith("CROSS_TYPE")
            ),
        })

    target.mkdir(parents=True, exist_ok=False)
    quote_path = target / "four_leg_quotes.jsonl"
    quote_bytes = ("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)).encode("utf-8")
    quote_path.write_bytes(quote_bytes)
    candidate_copy = target / "candidate_inputs.json"
    candidate_bytes = candidates_file.read_bytes()
    candidate_copy.write_bytes(candidate_bytes)
    manifest = {
        "schema_version": "track2-synthetic-four-leg-scenario-manifest-v3",
        "scenario_id": "S2-MARKET-CALIBRATED-FOUR-LEG-QUOTES-v3",
        "status": "SYNTHETIC_VALIDATION_ONLY_MARKET_CALIBRATED_NOT_OBSERVED_QUOTES",
        "strategy_id": "track2_asymmetric_trap",
        "base_registry_id": str(base_manifest_data["registry_id"]),
        "base_manifest_sha256": _digest(manifest_path),
        "base_data_partitions": [{"date": item["date"], "sha256": item["sha256"], "rows": item["rows"]} for item in days],
        "contract_specification": {
            "product_family": "STANDARD", "contract_cycle": "MONTHLY",
            "multiplier": str(multiplier), "multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
            "source_url": KIS_OPTION_PRODUCT_SPEC_URL,
        },
        "profile_id": profile.profile_id,
        "profile_sha256": profile.profile_sha256,
        "u21": {"max_age_seconds": str(max_age), "max_spread": str(max_spread), "tick_size": str(tick)},
        "candidate_input_file": {"path": candidate_copy.name, "sha256": sha256(candidate_bytes).hexdigest()},
        "candidate_count": len(candidates),
        "candidate_role_mapping_contract": {
            "inner_put": "LONG_PUT", "inner_call": "LONG_CALL",
            "outer_put": "SHORT_PUT", "outer_call": "SHORT_CALL",
            "authority": "core/oms/multi_leg_plan.py:build_trap_plan",
            "candidate_role_mapping_provenance": "ALIGNED_TO_EXECUTION_PLAN",
        },
        "source_candidate_inputs_sha256": str(candidates[0].get("source_candidate_inputs_sha256") or ""),
        "quote_rows": len(rows),
        "unique_synthetic_contract_ids": len({row["instrument_id"] for row in rows}),
        "leg_order": list(LEG_ORDER),
        "quote_file": {"path": quote_path.name, "sha256": sha256(quote_bytes).hexdigest(), "rows": len(rows)},
        "price_model": "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1",
        "price_model_assumptions": {
            "day_count": "ACT_365", "risk_free_rate": 0.0, "dividend_yield": 0.0,
            "expiry_time_kst": "15:20:00", "iv_anchor_price": "OBSERVED_BID_ASK_MID",
            "iv_source": "PRIOR_SAME_DATE_ACCEPTED_KIS_H0IOCNT0_L1",
            "generated_iv_fields_used": False,
        },
        "spread_model": "MEDIAN_PRIOR_ACCEPTED_ACTUAL_L1_SPREAD_BY_LOCAL_CONTRACT_NEIGHBORHOOD",
        "empirical_spread_reference": {
            "actual_quote_rows": raw_quote_rows,
            "skipped_rows_with_generated_bid_or_ask": skipped_generated_quote_rows,
            "spread_quantile": 0.95,
            "spread_quantile_method": "NEAREST_RANK",
            "observed_spread_p95": format(empirical_p95, "f"),
            "validation_profile_max_spread": format(expected_max_spread, "f"),
            "validation_buffer": "ONE_TICK_FOR_BID_ASK_ROUNDING",
            "not_a_production_u21_approval": True,
        },
        "anchor_policy": {
            "trading_date_scope": "SAME_DATE_ONLY",
            "future_option_observations_allowed": False,
            "max_source_anchor_age_seconds": 900,
            "same_type_strike_distance_preferred": 25,
            "same_type_or_cross_type_fallback_max_distance": 60,
            "cross_type_iv_fallback": "SAME_DATE_PRIOR_PUT_OR_CALL_IV_MEDIAN; EXPLICITLY_RECORDED",
            "per_contract_anchor_deduplication": "LATEST_OBSERVATION_PER_SYMBOL_AT_OR_BEFORE_CANDIDATE",
            "spread_outlier_filter": "EXCLUDE_SOURCE_SPREAD_ABOVE_SAME_DATASET_P95",
        },
        "candidate_calibration": candidate_calibration,
        "execution_enabled": False,
        "order_submission_enabled": False,
        "live_api_enabled": False,
        "real_vts_api_enabled": False,
        "limitations": [
            "Four-leg snapshots are synchronized synthetic scenarios derived from prior non-simultaneous actual L1 observations",
            "Some source underlying values are accepted KRX-derived scenario fills; source provenance remains explicit",
            "The option price model is a zero-rate/zero-dividend Black-Scholes scenario model, not a KIS quote",
            "The empirical spread p95 plus one tick is a validation-only test threshold, not approved production U21 policy",
            "Depth quantities are synthetic accepted-data proxies; actual multi-level depth is not claimed",
            "Synthetic contract IDs are not actual KIS instrument IDs",
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path_out = target / "manifest.json"
    manifest_path_out.write_bytes(manifest_bytes)
    return ScenarioBuildResult(str(target), str(manifest_path_out), sha256(manifest_bytes).hexdigest(),
        str(quote_path), sha256(quote_bytes).hexdigest(), len(candidates), len(rows))
