from dataclasses import dataclass
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


@dataclass(frozen=True)
class ReferenceCanonicalMarketTick:
    timestamp: str
    underlying_price: float | None = None
    underlying_symbol: str = ""
    underlying_observed_hour: str = ""
    underlying_source: str = ""
    strike_price: float = 0.0
    option_type: str = "CALL"
    contract_multiplier: float | None = None
    bid_price: float = 0.0
    ask_price: float = 0.0
    # Missing trade fields stay missing; quote prices/quantities are not trades.
    last_price: float | None = None
    volume: int | None = None
    seq_id: int = 0
    expiry: str = ""
    symbol: str = ""

    option_observed_hour: str = ""
    option_source: str = ""
    underlying_sequence: int = 0
    instrument_id: str = ""
    # Kept distinct from instrument_id so synthetic identity provenance remains explicit.
    synthetic_contract_id: str = ""
    source_instrument_code: str = ""
    instrument_identity_status: str = ""
    contract_class: str = "monthly"
    contract_month: str = ""
    theoretical_mid_price: float | None = None
    intrinsic_value: float | None = None
    time_value: float | None = None
    time_to_expiry_seconds: int | None = None
    # Per-option analytics carried from authoritative MarketObservation.
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    def __post_init__(self) -> None:
        if self.expiry:
            try:
                object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
            except CanonicalOptionExpiryError as exc:
                raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
