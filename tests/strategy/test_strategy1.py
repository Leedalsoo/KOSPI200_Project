from datetime import datetime, timezone
from decimal import Decimal
from core.domain.market_models import CanonicalMarketTick, DataQuality, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input, Track1TailDefense

def ctx(price="350", **kwargs):
    now=datetime.now(timezone.utc)
    tick=CanonicalMarketTick("KOSPI200",now,Decimal(price),None)
    state=MarketState(now,{"KOSPI200":tick},{"KOSPI200":DataQuality(True,True,True)})
    return StrategyContext(state,"TRACK1_TAIL_DEFENSE",StrategyInput(CommonStrategyInput(as_of=now,current_price=Decimal(price)),Track1Input(**kwargs)))

def test_strategy1_entry_contract():
    signals=Track1TailDefense().evaluate(ctx())
    assert len(signals)==3
    assert signals[0].execution_proposal.asset_type=="OPTION"
    assert signals[0].execution_proposal.option_type=="CALL"

def test_strategy1_missing_delta_fails_closed_for_futures_hedge():
    s=Track1TailDefense(); s.evaluate(ctx())
    signals=s.evaluate(ctx("343",momentum_confirmed=True,short_option_net_delta=None))
    assert not any("FUTURES_HEDGE_TRIGGER" in x.reason for x in signals)
