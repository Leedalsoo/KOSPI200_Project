from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from verification.track2_synthetic_quote_scenario import (
    _market_bs_price,
    _market_implied_volatility,
    _market_nearest_anchors,
    build_track2_market_calibrated_quote_scenario,
)


def test_black_scholes_market_mid_round_trips_to_implied_volatility() -> None:
    for option_type in ("CALL", "PUT"):
        market_mid = _market_bs_price(100.0, 102.5, 30 / 365, 0.48, option_type)
        implied = _market_implied_volatility(100.0, 102.5, 30 / 365, market_mid, option_type)
        assert implied is not None
        assert abs(implied - 0.48) < 1e-8


def test_market_anchor_selection_never_uses_future_observations() -> None:
    target = datetime.fromisoformat("2026-10-13T09:00:00+09:00")
    prior = {
        "observed_at": datetime.fromisoformat("2026-10-13T08:59:00+09:00"),
        "option_type": "PUT", "strike": Decimal("100.0"), "implied_volatility": 0.45,
    }
    future = {
        "observed_at": datetime.fromisoformat("2026-10-13T09:01:00+09:00"),
        "option_type": "PUT", "strike": Decimal("100.0"), "implied_volatility": 0.90,
    }
    selected, method = _market_nearest_anchors(
        [prior, future], observed_at=target, option_type="PUT", strike=prior["strike"], require_iv=True,
    )
    assert selected == [prior]
    assert method == "SAME_TYPE_LOCAL"


def test_market_calibrated_builder_generates_four_legs_from_prior_observed_quotes(tmp_path: Path) -> None:
    dataset = tmp_path / "accepted"
    dataset.mkdir()
    profile_source = Path(__file__).resolve().parents[2] / "config/validation_only/track2/synthetic_scenario_profile.v1.json"
    profile = json.loads(profile_source.read_text(encoding="utf-8-sig"))
    profile["profile_id"] = "TEST-MARKET-CALIBRATED-v1"
    profile["U16_quote_policy"]["max_spread"] = "0.15"
    profile["U21_quote_policy"]["max_spread"] = "0.15"
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    records = []
    expiry = "20261112"
    spot = 100.0
    strike_mid = {
        "CALL": {90.0: 12.0, 92.5: 10.0, 95.0: 7.5, 97.5: 5.0, 100.0: 3.0,
                 102.5: 2.5, 105.0: 2.0, 107.5: 1.5, 110.0: 1.2, 112.5: 1.0},
        "PUT": {90.0: 1.0, 92.5: 1.2, 95.0: 1.5, 97.5: 2.5, 100.0: 3.0,
                102.5: 5.0, 105.0: 7.5, 107.5: 10.0, 110.0: 12.0, 112.5: 15.0},
    }
    for option_type, values in strike_mid.items():
        for strike, mid in values.items():
            code = f"{option_type}-{strike}"
            records.append({
                "tick": {
                    "timestamp": "2026-10-12T09:20:00+09:00", "expiry": expiry,
                    "option_type": option_type, "strike_price": str(strike),
                    "underlying_price": str(spot), "bid_price": str(mid - 0.05),
                    "ask_price": str(mid + 0.05), "last_price": str(mid), "volume": 12,
                    "symbol": code, "source_instrument_code": code,
                },
                "scenario_metadata": {
                    "source_observation_id": f"obs-{code}",
                    "source_raw_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "source_canonical_sha256": hashlib.sha256((code + "-c").encode()).hexdigest(),
                    "source_collected_at": "2026-10-12T09:20:01+09:00",
                    "generated_fields": ["implied_volatility"],
                    "field_provenance": {"order_book_quantities": {"bid_quantity": 20, "ask_quantity": 25}},
                },
            })
    partition = dataset / "20261012.jsonl"
    partition.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    base_manifest = {
        "schema_version": "accepted-market-data-runtime-v2",
        "acceptance": "ACCEPTED_FOR_PROJECT_VERIFICATION",
        "registry_id": "TEST_ACCEPTED_MARKET_DATA",
        "days": [{"date": "20261012", "sha256": hashlib.sha256(partition.read_bytes()).hexdigest(), "rows": len(records)}],
    }
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps([{
        "candidate_id": "candidate-1", "observed_at": "2026-10-12T09:26:00+09:00",
        "expiry": expiry, "underlying_price": "100.0", "source_observation_id": "candidate-source-1",
        "legs": [
            {"role": "inner_put", "option_type": "PUT", "strike": "100.0"},
            {"role": "inner_call", "option_type": "CALL", "strike": "105.0"},
            {"role": "outer_put", "option_type": "PUT", "strike": "95.0"},
            {"role": "outer_call", "option_type": "CALL", "strike": "110.0"},
        ],
    }]), encoding="utf-8")

    result = build_track2_market_calibrated_quote_scenario(
        base_dataset=dataset, base_manifest=manifest_path, profile_path=profile_path,
        candidates_path=candidates_path, output_dir=tmp_path / "market-calibrated-v1",
    )
    rows = [json.loads(line) for line in Path(result.quotes_path).read_text(encoding="utf-8").splitlines()]
    assert result.candidates == 1 and result.quote_rows == 4
    assert {row["leg_role"] for row in rows} == {"inner_put", "inner_call", "outer_put", "outer_call"}
    for row in rows:
        calibration = row["market_calibration"]
        assert row["model"] == "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1"
        assert calibration["iv_anchor_count"] >= 1
        assert calibration["last_price_basis"] == "MODEL_FAIR_VALUE_NOT_OBSERVED_TRADE"
        assert all(datetime.fromisoformat(value) <= datetime.fromisoformat(row["timestamp"])
                   for value in calibration["iv_anchor_timestamps"])
        assert float(row["ask"]) > float(row["bid"]) > 0
        assert row["volume"] > 0 and row["bid_quantity"] > 0 and row["ask_quantity"] > 0
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["empirical_spread_reference"]["observed_spread_p95"] == "0.10"
    assert manifest["empirical_spread_reference"]["validation_profile_max_spread"] == "0.15"
