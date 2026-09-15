from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VirtualBrokerConfig:
    replay_speed: int = 1
    slippage_multiplier: float = 1.0
    fee_rate_multiplier: float = 1.0
    volatility_scale: float = 1.0
    scenario_name: str = "COVID_PANIC_2020"
    gap_pct: float = 0.0
    base_spread: float = 0.05
    latency_ms: int = 50
    futures_basis_points: float = 0.0
    option_quote_qty: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class VirtualBrokerControlInterface:
    def __init__(self, config: Optional[VirtualBrokerConfig] = None) -> None:
        self.config = config or VirtualBrokerConfig()

    def get_config(self) -> Dict[str, Any]:
        return self.config.to_dict()

