from datetime import date
from decimal import Decimal

from application.composition.track7_calendar_source import Track7CalendarSource
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class FakeTradingCalendar:
    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5

    def prev_trading_day(self, value: date) -> date:
        from datetime import timedelta
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current


def test_track7_calendar_flags_use_trading_calendar_not_weekday_fallback():
    source = Track7CalendarSource(FakeTradingCalendar())
    assert source.flags(date(2026, 9, 14), date(2026, 9, 17)) == (True, False, False)
    assert source.flags(date(2026, 9, 18), date(2026, 9, 18)) == (False, True, True)


def test_virtual_runtime_projects_option_master_expiry_and_calendar_flags():
    calendar = FakeTradingCalendar()
    master = InMemoryOptionContractMaster(calendar=calendar)
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="KOSPI200", stnd_iscd=None, expiry="2026-09-15",
        option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"),
    ))
    market = VirtualMarketSimulatorRuntime(option_master=master)
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-01-05T09:00:00", underlying_price=350, strike_price=350,
        option_type="CALL", contract_multiplier=Decimal("250000"),
        bid_price=349.95, ask_price=350.05, last_price=350, volume=1000,
        seq_id=1, expiry="202601", symbol="KOSPI200",
    )
    expiry_source = type("Expiry", (), {"resolve_expiry": lambda self, symbol: date(2026, 1, 8)})()
    data = VirtualRuntimeDataProvider(
        market, option_expiry_source=expiry_source, trading_calendar=calendar, option_master=master
    ).snapshot(tick)
    assert data.status["track7_calendar"].available is True
    assert data.status["track7_calendar"].source == "KIS.TradingCalendar"
    assert data.is_new_week_start is True
    assert data.is_expiry_day is False
    assert data.is_week_end is False


def test_track7_calendar_resolves_expiry_from_option_master_identity():
    calendar = FakeTradingCalendar()
    master = InMemoryOptionContractMaster(calendar=calendar)
    master.register_contract_identity(KisOptionContractIdentity(
        shrn_iscd="OPT350C", stnd_iscd=None, expiry="2026-01-08",
        option_type="CALL", strike=Decimal("350"), contract_multiplier=Decimal("250000"),
    ))
    source = Track7CalendarSource(calendar, master)
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-01-08T09:00:00", underlying_price=350, strike_price=350,
        option_type="CALL", contract_multiplier=Decimal("250000"),
        bid_price=1, ask_price=2, last_price=1.5, volume=1, seq_id=1,
        expiry="202601", symbol="OPT350C",
    )
    assert source.resolve_option_expiry(tick) == date(2026, 1, 8)
    assert source.flags(date(2026, 1, 8), date(2026, 1, 8)) == (False, True, False)

