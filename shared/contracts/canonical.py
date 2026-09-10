from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
class CanonicalOrderSide(str, Enum): BUY="BUY"; SELL="SELL"
class CanonicalAssetType(str, Enum): FUTURES="FUTURES"; OPTION="OPTION"
class CanonicalOptionType(str, Enum): CALL="CALL"; PUT="PUT"
@dataclass(frozen=True)
class CanonicalMarketTick:
 timestamp:str; underlying_price:float; strike_price:float=0.0; option_type:str="CALL"; bid_price:float=0.0; ask_price:float=0.0; last_price:float=0.0; volume:int=0; seq_id:int=0; source_sequence:int|None=None; expiry:str=""; symbol:str=""
@dataclass(frozen=True)
class CanonicalOrderCommand:
 client_order_id:str; track_id:str; asset_type:CanonicalAssetType; side:CanonicalOrderSide; qty:int; price:float; option_type:Optional[CanonicalOptionType]=None; strike:float=0.0; symbol:str="KOSPI200"; expiry:str=""; tag_id:str=""
@dataclass(frozen=True)
class CanonicalExecutionReport:
 exec_id:str; client_order_id:str; track_id:str; asset_type:CanonicalAssetType; side:CanonicalOrderSide; executed_qty:int; executed_price:float; fee:float; slippage:float; timestamp:str; symbol:str="KOSPI200"; option_type:Optional[CanonicalOptionType]=None; strike:float=0.0; expiry:str=""
@dataclass
class CanonicalAccountSummary:
 account_id:str; total_balance:float; realized_pnl:float; unrealized_pnl:float; used_margin:float; free_margin:float; timestamp:str=""; positions:Dict[str,Dict[str,Any]]=field(default_factory=dict)

# Reference-compatible VSSF canonical DTO의 단일 import ownership.


@dataclass(frozen=True)
class CanonicalStrategySignal:
    """Strategy signal after the authoritative Runtime/Controller boundary."""
    signal_id: str
    track_id: str
    asset_type: CanonicalAssetType
    side: CanonicalOrderSide
    qty: int
    price: float
    option_type: Optional[CanonicalOptionType] = None
    strike: float = 0.0
    tag_id: str = ""
    reason: str = ""
    timestamp: str = ""
    symbol: str = ""
    expiry: str = ""
    instrument_id: str = ""
