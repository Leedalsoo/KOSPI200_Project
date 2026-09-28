from __future__ import annotations
import argparse
import json
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

DATASET = "synthetic-1y-5min-v1"
SOURCE = "synthetic:market-model-v1"
PROVIDER = "KOSPI200_SYNTHETIC_MARKET"
SCHEMA = "reference-canonical-market-tick-v1"
START = date(2025, 1, 2)
END = date(2025, 12, 31)
TRADING_DAYS = 252
BAR_MINUTES = 5
CONTRACT_OFFSETS = (-100.0, -50.0, 0.0, 50.0, 100.0)
CONTRACT_MULTIPLIER = 250000.0

def trading_days() -> list[date]:
    days = []
    current = START
    while current <= END and len(days) < TRADING_DAYS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days

def third_thursday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (3 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)

def next_expiry(day: date) -> str:
    year, month = day.year, day.month
    expiry = third_thursday(year, month)
    if day >= expiry:
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return f"{year:04d}{month:02d}"

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def option_mid(spot: float, strike: float, years: float, iv: float, kind: str) -> float:
    if years <= 0 or iv <= 0:
        return max(0.01, spot - strike if kind == "CALL" else strike - spot)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / (iv * math.sqrt(years))
    d2 = d1 - iv * math.sqrt(years)
    if kind == "CALL":
        return max(0.01, spot * normal_cdf(d1) - strike * normal_cdf(d2))
    return max(0.01, strike * normal_cdf(-d2) - spot * normal_cdf(-d1))

def regime(day_index: int, bar_index: int) -> tuple[float, float]:
    phase = (day_index // 21) % 8
    profiles = (
        (0.00010, 0.0040), (0.00025, 0.0060), (0.0, 0.0020),
        (-0.00020, 0.0050), (-0.00045, 0.0120), (0.00035, 0.0100),
        (0.0, 0.0012), (0.0, 0.0080),
    )
    drift, vol = profiles[phase]
    if bar_index in (18, 19) and phase in (4, 5, 7):
        drift += 0.004 if phase == 5 else -0.004 if phase == 4 else 0.0
        vol *= 2.5
    return drift, vol

def make_tick(day: date, day_index: int, bar_index: int, kind: str, strike: float,
              spot: float, rng: random.Random, sequence: int) -> dict:
    expiry = next_expiry(day)
    expiry_day = third_thursday(int(expiry[:4]), int(expiry[4:]))
    years = max(1.0 / 365.0, (expiry_day - day).days / 365.0)
    _, regime_vol = regime(day_index, bar_index)
    iv = max(0.08, 0.18 + regime_vol * 12.0 + 0.015 * abs(strike - spot) / max(spot, 1.0))
    mid = option_mid(spot, strike, years, iv, kind)
    spread = max(0.02, mid * (0.008 + iv * 0.015))
    noise = rng.uniform(-spread * 0.25, spread * 0.25)
    last = max(0.01, mid + noise)
    volume = int(max(1, 50 + rng.random() * (500 + regime_vol * 50000)))
    ts = datetime.combine(day, time(9, 0)) + timedelta(minutes=BAR_MINUTES * bar_index)
    instrument_id = f"SYN-{expiry}-{kind}-{strike:.1f}"
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "dataset": DATASET,
        "provenance": "SYNTHETIC",
        "provider": PROVIDER,
        "tick": {
            "timestamp": ts.isoformat(),
            "underlying_price": round(spot, 4),
            "underlying_symbol": "KOSPI200_SYNTHETIC",
            "strike_price": strike,
            "option_type": kind,
            "contract_multiplier": CONTRACT_MULTIPLIER,
            "bid_price": round(max(0.01, mid - spread / 2), 6),
            "ask_price": round(mid + spread / 2, 6),
            "last_price": round(last, 6),
            "volume": volume,
            "seq_id": sequence,
            "expiry": expiry,
            "symbol": "KOSPI200_SYNTHETIC",
            "option_observed_hour": ts.strftime("%H:%M"),
            "option_source": SOURCE,
            "instrument_id": instrument_id,
        },
    }
def generate_dataset(root: Path, seed: int = 2005) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    days = trading_days()
    spot = 1100.0
    sequence = 0
    total = 0
    manifest_days = []
    for day_index, day in enumerate(days):
        path = root / f"{day.isoformat()}.jsonl"
        day_count = 0
        with path.open("w", encoding="utf-8") as handle:
            for bar_index in range(78):
                drift, vol = regime(day_index, bar_index)
                shock = rng.gauss(drift, vol)
                spot = max(700.0, spot * (1.0 + shock))
                base_strike = round(spot / 10.0) * 10.0
                for kind in ("CALL", "PUT"):
                    for offset in CONTRACT_OFFSETS:
                        sequence += 1
                        strike = base_strike + offset
                        record = make_tick(
                            day, day_index, bar_index, kind, strike, spot,
                            rng, sequence
                        )
                        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                        day_count += 1
        total += day_count
        manifest_days.append({
            "date": day.isoformat(),
            "file": path.name,
            "events": day_count,
            "source": SOURCE,
        })
    manifest = {
        "dataset": DATASET,
        "provenance": "SYNTHETIC",
        "source": SOURCE,
        "provider": PROVIDER,
        "schema": SCHEMA,
        "calendar": "weekday-only synthetic calendar; not KRX holiday authoritative",
        "date_start": days[0].isoformat(),
        "date_end": days[-1].isoformat(),
        "trading_days": len(days),
        "bar_interval_minutes": BAR_MINUTES,
        "contracts_per_bar": 10,
        "events": total,
        "seed": seed,
        "days": manifest_days,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/synthetic_market_data/1y_5min_v1")
    parser.add_argument("--seed", type=int, default=2005)
    args = parser.parse_args()
    manifest = generate_dataset(Path(args.output), args.seed)
    print(f"DATASET={manifest['dataset']}")
    print(f"EVENTS={manifest['events']}")
    print(f"TRADING_DAYS={manifest['trading_days']}")
    print(f"DATE_RANGE={manifest['date_start']}..{manifest['date_end']}")
    print(f"PROVENANCE={manifest['provenance']}")

if __name__ == "__main__":
    main()
