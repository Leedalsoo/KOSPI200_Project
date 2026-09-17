from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from application.composition.virtual_track3_runtime_input_source import VirtualTrack3RuntimeInputSource


class Master:
    def find_contract_identity(self, expiry, option_type, strike):
        return SimpleNamespace(
            shrn_iscd=f"{option_type}-{strike}",
            expiry=expiry,
            option_type=option_type,
            strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
        )


def runtime():
    start = datetime(2026, 9, 17, 9, 0)
    ticks = []
    for index in range(12):
        price = 350.0 + index * 0.1
        ticks.append(SimpleNamespace(
            timestamp=(start + timedelta(minutes=index)).isoformat(),
            underlying_price=price,
            bid_price=price - 0.05,
            ask_price=price + 0.05,
            last_price=price,
            symbol="KOSPI200",
            expiry="202609",
        ))
    market = SimpleNamespace(
        recent_ticks=tuple(ticks),
        last_tick=ticks[-1],
        option_quotes={
            ("CALL", 350.0, "202609"): {
                "bid": 2.0, "ask": 2.1, "last": 2.05,
                "contract_multiplier": 250000,
            },
            ("PUT", 350.0, "202609"): {
                "bid": 1.8, "ask": 1.9, "last": 1.85,
                "contract_multiplier": 250000,
            },
        },
    )
    report = SimpleNamespace(
        fee=3000.0, asset_type="OPTION", side="BUY",
        executed_price=2.0, executed_qty=1,
    )
    vssf = SimpleNamespace(execution_engine=SimpleNamespace(reports=[report]))
    return market, vssf, ticks[-1]


def test_virtual_runtime_source_materializes_authoritative_input():
    market, vssf, tick = runtime()
    source = VirtualTrack3RuntimeInputSource(
        market, account=SimpleNamespace(), vssf_runtime=vssf, option_master=Master()
    )
    payload = source.get_input("KOSPI200", datetime.fromisoformat(tick.timestamp))
    assert payload is not None
    assert payload.source == "VirtualExchange.VMS+VirtualBroker.VSSF"
    assert len(payload.spread_history) == 11
    assert payload.active_vol > 0
    assert payload.base_vol > 0
    assert payload.total_fees == 3000.0
    assert payload.premium_spent == 2.0
    assert len(payload.options_legs) == 2
    assert payload.contract_multiplier == 250000.0


def test_virtual_runtime_source_rejects_insufficient_history():
    market, vssf, tick = runtime()
    market.recent_ticks = market.recent_ticks[:5]
    source = VirtualTrack3RuntimeInputSource(
        market, account=SimpleNamespace(), vssf_runtime=vssf, option_master=Master()
    )
    assert source.get_input("KOSPI200", datetime.fromisoformat(tick.timestamp)) is None


def test_virtual_runtime_source_rejects_missing_option_multiplier():
    market, vssf, tick = runtime()
    market.option_quotes[("CALL", 350.0, "202609")]["contract_multiplier"] = None
    source = VirtualTrack3RuntimeInputSource(
        market, account=SimpleNamespace(), vssf_runtime=vssf, option_master=Master()
    )
    payload = source.get_input("KOSPI200", datetime.fromisoformat(tick.timestamp))
    assert payload is not None
    assert all("CALL" not in str(leg["instrument_id"]) for leg in payload.options_legs)
