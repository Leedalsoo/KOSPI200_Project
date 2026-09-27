from datetime import datetime
from decimal import Decimal

import pytest

from application.composition.virtual_track4_attribution_source import VirtualTrack4AttributionSource
from contracts.track4_attribution_provider import Track4AttributionSourceUnavailable


class Report:
    def __init__(self, asset_type, side, price, qty):
        self.asset_type = asset_type
        self.side = side
        self.executed_price = price
        self.executed_qty = qty


class Engine:
    reports = ()


def test_virtual_attribution_uses_executed_option_buys_only():
    engine = Engine()
    engine.reports = (
        Report("OPTION", "BUY", "125.5", 2),
        Report("OPTION", "SELL", "200", 1),
        Report("FUTURES", "BUY", "350", 1),
    )
    source = VirtualTrack4AttributionSource(engine, observed_at=datetime(2026, 9, 22, 10, 0))
    assert source.premium_spent() == Decimal("251.0")
    assert source.snapshot().source == "VirtualExchange.VirtualBroker.VSSF.execution_ledger"


def test_unavailable_attribution_components_fail_closed():
    source = VirtualTrack4AttributionSource(Engine(), observed_at=datetime(2026, 9, 22, 10, 0))
    with pytest.raises(Track4AttributionSourceUnavailable):
        source.accumulated_gamma_profit()
    with pytest.raises(Track4AttributionSourceUnavailable):
        source.theta_decay_cost()
