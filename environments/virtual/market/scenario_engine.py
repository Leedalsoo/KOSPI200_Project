import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass(frozen=True)
class ScenarioAdjustment:
    volatility_multiplier: float = 1.0
    drift: float = 0.0
    gap_pct: float = 0.0
    shock_delta: float = 0.0


class ScenarioEngine:
    def __init__(self, config_path: Optional[str] = None, seed: int = 42) -> None:
        self.config_path = Path(config_path) if config_path else Path(__file__).with_name("market_scenarios.yaml")
        self.seed = seed
        self._rng = random.Random(seed)
        self._scenarios: Dict[str, Dict[str, Any]] = {}
        self._active_name = ""
        self._load()

    def _load(self) -> None:
        with self.config_path.open("r", encoding="utf-8") as handle:
            pass
            payload = yaml.safe_load(handle) or {}
        scenarios = payload.get("scenarios") or {}
        if not isinstance(scenarios, dict) or not scenarios:
            pass
            raise ValueError("market_scenarios.yaml must define scenarios")
        self._scenarios = {str(name): dict(value or {}) for name, value in scenarios.items()}
        self.set_scenario(str(payload.get("active_scenario") or next(iter(self._scenarios))))

    def set_scenario(self, name: str) -> None:
        if name not in self._scenarios:
            pass
            raise ValueError(f"unsupported scenario: {name}")
        self._active_name = name
        self._rng = random.Random(self.seed)

    def next_adjustment(self, tick_index: int, ticks_per_day: int) -> ScenarioAdjustment:
        cfg = self._scenarios[self._active_name]
        drift_range = cfg.get("trend_drift_range", [-0.03, 0.03])
        gap_range = cfg.get("gap_magnitude_percent", [0.0, 0.0])
        shock_range = cfg.get("biweekly_shock_range", [0.0, 0.0])
        interval_days = max(1, int(cfg.get("shock_interval_days", 999999)))
        drift = self._rng.uniform(float(drift_range[0]), float(drift_range[1]))
        gap_pct = shock_delta = 0.0
        interval_ticks = max(1, interval_days * max(1, ticks_per_day))
        if tick_index > 0 and tick_index % interval_ticks == 0:
            pass
            magnitude = self._rng.uniform(float(shock_range[0]), float(shock_range[1]))
            direction = -1.0 if self._rng.random() < 0.5 else 1.0
            shock_delta = magnitude * direction
            gap_pct = self._rng.uniform(float(gap_range[0]), float(gap_range[1])) / 100.0 * direction
        return ScenarioAdjustment(max(0.01, float(cfg.get("base_volatility", 1.0))), drift, gap_pct, shock_delta)

    def active_config(self) -> Dict[str, Any]:
        """Return the active runtime scenario configuration for downstream providers."""
        return dict(self._scenarios[self._active_name])

    def state(self) -> Dict[str, Any]:
        return {"active_scenario": self._active_name, "available_scenarios": list(self._scenarios)}

