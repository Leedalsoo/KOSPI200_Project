from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceCanonicalMarketTick:
    timestamp: str
    underlying_price: float | None = None
    underlying_symbol: str = ""
    underlying_observed_hour: str = ""
    underlying_source: str = ""
    strike_price: float = 0.0
    option_type: str = "CALL"
    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    volume: int = 0
    seq_id: int = 0
    expiry: str = ""
    symbol: str = ""
