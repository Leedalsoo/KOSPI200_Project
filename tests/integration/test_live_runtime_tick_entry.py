import pytest

class Runtime:
    def process_tick(self,t,o): return ('eval',)
class S2D:
    def evaluate(self,x): return ('decision',)
class D2C:
    def commands(self,d,e): return ('command',)

def test_tick_entry_preserves_existing_chain():
    from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
    calls=[]
    entry=LiveRuntimeTickEntry(Runtime(),S2D(),D2C(),'risk',
# lambda command, **kw: calls.append((command,kw)) or 'routed',
      lambda:'account',lambda:'positions')
    assert entry.process_tick('tick','asof',risk_context='ctx') == ('routed',)
    assert calls[0][0]=='command'

def test_tick_entry_fails_without_authoritative_risk_state():
    from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
    entry=LiveRuntimeTickEntry(Runtime(),S2D(),D2C(),'risk',lambda *a,**k:None,lambda:None,lambda:'p')
    with pytest.raises(ValueError, match='RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED'):
        pass
        entry.process_tick('tick','asof',risk_context='ctx')
