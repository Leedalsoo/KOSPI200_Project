"""Synthetic-only Runtime Input Sources for High-Speed validation.

These sources are explicitly marked SYNTHETIC and are never used by Live/KIS paths.
They make the generated market dataset exercise existing Runtime contracts without
pretending that synthetic values are authoritative market evidence.
"""
from __future__ import annotations

import json
from collections import deque
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from contracts.basis_source import BasisObservation
from contracts.option_orderbook_source import OptionOrderBookLevel, OptionOrderBookSnapshot
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.track2_market_metrics_source import Track2MarketMetrics
from contracts.track2_option_iv_source import Track2OptionIVObservation
from contracts.track9_authoritative_sources import Track9EventRiskSnapshot
from contracts.trading_state import SensorLevel
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity

SYNTHETIC_SOURCE = "SYNTHETIC:high-speed-market-model-v2"


class SyntheticRuntimeSources:
    def __init__(self) -> None:
        self._tick: Any | None = None
        self._iv: dict[tuple[str, str, Decimal], Decimal] = {}
        self._history: deque[tuple[datetime, Decimal, Decimal]] = deque(maxlen=60)
        self._poc: Decimal | None = None
        self._basis: Decimal | None = None
        self._metrics: Track2MarketMetrics | None = None
        self.calendar = SyntheticTradingCalendar()
        self.source_name = SYNTHETIC_SOURCE
        self._greeks = {
            "delta": Decimal("0.50"),
            "gamma": Decimal("0.01"),
            "theta": Decimal("-0.01"),
            "iv": Decimal("0.20"),
        }

    @property
    def snapshot(self):
        from contracts.track4_kis_greeks_provider import Track4KisGreeksSnapshot
        observed_at = self._tick.timestamp if self._tick is not None else datetime.now().isoformat()
        instrument_id = self._tick.instrument_id if self._tick is not None else "SYNTHETIC"
        return Track4KisGreeksSnapshot(
            instrument_id=instrument_id, observed_at=observed_at,
            delta=self._greeks["delta"], gamma=self._greeks["gamma"],
            theta=self._greeks["theta"], implied_volatility=self._greeks["iv"],
            source=SYNTHETIC_SOURCE,
        )

    def current_delta(self) -> Decimal: return self._greeks["delta"]
    def current_gamma(self) -> Decimal: return self._greeks["gamma"]
    def current_theta(self) -> Decimal: return self._greeks["theta"]
    def active_vol(self) -> Decimal: return self._greeks["iv"]

    def set_tick(self, tick: Any) -> None:
        self._tick = tick
        observed = datetime.fromisoformat(tick.timestamp)
        price = Decimal(str(tick.last_price))
        volume = Decimal(str(max(1, tick.volume)))
        self._history.append((observed, price, volume))
        expiry = str(tick.expiry)
        strike = Decimal(str(tick.strike_price))
        # IV is reconstructed from the synthetic option quote model; this is
        # deliberately a synthetic source, not a claim of KIS IV evidence.
        moneyness = abs(float(strike) - float(tick.underlying_price)) / max(float(tick.underlying_price), 1.0)
        iv = Decimal(str(round(max(0.08, 0.18 + moneyness * 0.015), 6)))
        call_iv = iv + Decimal("0.04") if int(tick.seq_id) % 17 == 0 else iv
        put_iv = max(Decimal("0.08"), iv - Decimal("0.01")) if int(tick.seq_id) % 17 == 0 else iv
        self._iv[(expiry, "CALL", strike)] = call_iv
        self._iv[(expiry, "PUT", strike)] = put_iv
        spot = Decimal(str(tick.underlying_price))
        self._basis = spot * Decimal("0.0008")
        # Synthetic POC is derived from the generated underlying path. It is
        # only a test input for the synthetic environment.
        direction = Decimal("2") if int(tick.seq_id) % 17 == 0 else Decimal("0")
        self._poc = spot - direction
        prices = tuple(x[1] for x in self._history)
        volumes = tuple(x[2] for x in self._history)
        returns = tuple(abs(prices[i] / prices[i - 1] - 1) for i in range(1, len(prices)) if prices[i - 1])
        active = (sum(returns, Decimal("0")) / Decimal(len(returns))) if returns else Decimal("0")
        base = (sum(returns[-20:], Decimal("0")) / Decimal(len(returns[-20:]))) if returns[-20:] else active
        trigger = int(tick.seq_id) % 17 == 0
        bbw = tuple(max(p, price + Decimal("1")) for p in prices[-19:]) + (price,) if trigger else tuple(prices[-20:])
        current_volume = volume * Decimal("12") if trigger else volume
        vol_window = tuple(volumes[-19:]) + (current_volume,) if trigger else tuple(volumes[-20:])
        self._metrics = Track2MarketMetrics(
            bbw_window=bbw,
            volume_window=vol_window,
            active_vol=active,
            base_vol=base,
        )

    def get_iv(self, *, expiry: str, option_type: str, strike: Decimal) -> Decimal | None:
        return self._iv.get((str(expiry), str(option_type).upper(), Decimal(str(strike))))

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        if self._tick is None or symbol != self._tick.symbol:
            return None
        mid = Decimal(str(self._tick.last_price))
        qty = Decimal(str(max(1, int(self._tick.volume))))
        trigger = int(self._tick.seq_id) % 17 == 0
        asks = tuple(OptionOrderBookLevel(mid + Decimal("0.01") * i, qty + Decimal(i * 2)) for i in range(1, 6))
        bid_base = qty * Decimal("8") if trigger else qty
        bids = tuple(OptionOrderBookLevel(max(Decimal("0.01"), mid - Decimal("0.01") * i), bid_base + Decimal(i * 4)) for i in range(1, 6))
        return OptionOrderBookSnapshot(symbol, self._tick.option_observed_hour, asks, bids, SYNTHETIC_SOURCE)

    def get_poc(self, symbol: str) -> Decimal | None:
        return self._poc

    def get_basis(self, symbol: str) -> Decimal | None:
        return self._basis

    def get_metrics(self, symbol: str) -> Track2MarketMetrics | None:
        return self._metrics

    def get(self, *, symbol: str, observed_at: datetime, current_price: Decimal):
        window = tuple(x[1] for x in self._history)
        if not window:
            return None
        return type("SupportResistance", (), {
            "support": min(window[-20:]),
            "resistance": max(window[-20:]),
            "source": SYNTHETIC_SOURCE,
        })()

    def is_strategy_timed_out(self, strategy_id: str, observed_at: datetime) -> bool:
        return False

    def snapshot(self) -> RiskGuardStatusSnapshot:
        observed = datetime.fromisoformat(self._tick.timestamp) if self._tick is not None else datetime.now()
        return RiskGuardStatusSnapshot(observed, True, False, SensorLevel.GREEN, SYNTHETIC_SOURCE, "SYNTHETIC-HS-V2")

    def upcoming(self, *, run_id: str, as_of) -> object | None:
        return type("SyntheticEvent", (), {"upcoming": True, "source": SYNTHETIC_SOURCE})()

    def event_risk(self, *, run_id: str, as_of) -> Track9EventRiskSnapshot:
        return Track9EventRiskSnapshot(Decimal("500000"), Decimal("100000"), SYNTHETIC_SOURCE)


class SyntheticEventRiskSource:
    def __init__(self, source: SyntheticRuntimeSources) -> None:
        self.source = source

    def snapshot(self, *, run_id: str, as_of) -> Track9EventRiskSnapshot:
        return self.source.event_risk(run_id=run_id, as_of=as_of)


class SyntheticOptionContractMaster(InMemoryOptionContractMaster):
    def get_expiry(self, symbol: str):
        identity = self.get_contract_identity(symbol)
        if identity is None or not identity.expiry:
            return None
        raw = str(identity.expiry).replace("-", "")[:6]
        year, month = int(raw[:4]), int(raw[4:6])
        first = date(year, month, 1)
        expiry = first + timedelta(days=(3 - first.weekday()) % 7 + 14)
        return expiry.isoformat()

    def find_contract_identity(self, expiry: str, option_type: str, strike: Decimal):
        found = super().find_contract_identity(expiry, option_type, strike)
        if found is not None:
            return found
        target = str(expiry).replace("-", "")
        month_target = target[:6]
        for identity in self.list_contract_identities():
            if str(identity.expiry).replace("-", "")[:6] == month_target and str(identity.option_type).upper() == str(option_type).upper() and identity.strike == Decimal(str(strike)):
                return identity
        # Execution plans may intentionally choose strikes between the dataset's
        # observed grid points. In the synthetic environment only, create an
        # explicit synthetic contract identity for that requested strike.
        requested_strike = Decimal(str(strike))
        synthetic_id = f"SYN-{month_target}-{str(option_type).upper()}-{requested_strike:.4f}"
        identity = KisOptionContractIdentity(
            shrn_iscd=synthetic_id,
            stnd_iscd=synthetic_id,
            expiry=target[:8],
            option_type=str(option_type).upper(),
            strike=requested_strike,
            info_type="SYNTHETIC",
            contract_multiplier=Decimal("250000"),
        )
        self.register_contract_identity(identity)
        return identity


def build_synthetic_option_master(dataset: str | Path) -> InMemoryOptionContractMaster:
    master = SyntheticOptionContractMaster(auto_load_kis_source=False)
    root = Path(dataset)
    for path in sorted(root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                tick = record["tick"]
                identity = KisOptionContractIdentity(
                    shrn_iscd=str(tick["instrument_id"]),
                    stnd_iscd=str(tick["instrument_id"]),
                    expiry=str(tick["expiry"]),
                    option_type=str(tick["option_type"]),
                    strike=Decimal(str(tick["strike_price"])),
                    info_type="SYNTHETIC",
                    contract_multiplier=Decimal(str(tick["contract_multiplier"])),
                )
                existing = master.get_contract_identity(str(tick["instrument_id"]))
                if existing is not None:
                    existing_month = str(existing.expiry).replace("-", "")[:6]
                    incoming_month = str(identity.expiry).replace("-", "")[:6]
                    if existing_month == incoming_month and existing.option_type == identity.option_type and existing.strike == identity.strike and existing.contract_multiplier == identity.contract_multiplier:
                        continue
                master.register_contract_identity(identity)
    return master


class SyntheticTradingCalendar:
    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5

    def prev_trading_day(self, value: date) -> date:
        candidate = value - timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    def resolve_option_expiry(self, tick: Any) -> date:
        raw = str(tick.expiry).replace("-", "")
        year, month = int(raw[:4]), int(raw[4:6])
        first = date(year, month, 1)
        third_thursday = first + timedelta(days=(3 - first.weekday()) % 7 + 14)
        return third_thursday

    def flags(self, observed_date: date, option_expiry: date | None):
        if option_expiry is None:
            return None, None, None
        return observed_date.weekday() == 0, observed_date == option_expiry, observed_date.weekday() == 4


__all__ = ["SYNTHETIC_SOURCE", "SyntheticRuntimeSources", "SyntheticEventRiskSource", "SyntheticTradingCalendar", "build_synthetic_option_master"]
