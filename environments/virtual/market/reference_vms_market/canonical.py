from dataclasses import dataclass
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


@dataclass(frozen=True)
class ReferenceCanonicalMarketTick:
    timestamp: str
    underlying_price: float
    strike_price: float = 0.0
    option_type: str = "CALL"
    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    volume: int = 0
    seq_id: int = 0
    expiry: str = ""
    symbol: str = ""

    def __post_init__(self) -> None:
        if self.expiry:
            try:
                object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
            except CanonicalOptionExpiryError as exc:
                raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
