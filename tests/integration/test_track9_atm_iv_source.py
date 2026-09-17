from datetime import datetime
from decimal import Decimal

from contracts.track9_iv_timeseries import Track9IVObservation
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from infrastructure.kis.track9_atm_iv_source import KISTrack9ATMIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore


def _master() -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    for symbol, option_type, strike in (
        ("CALL500", "CALL", "500"),
        ("PUT500", "PUT", "500"),
        ("CALL502", "CALL", "502.5"),
        ("PUT502", "PUT", "502.5"),
    ):
        master.register_contract_identity(KisOptionContractIdentity(
            shrn_iscd=symbol, stnd_iscd=None, expiry="2026-10-15",
            option_type=option_type, strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
        ))
    return master


def _append(store, symbol, option_type, strike, iv, observed_at):
    store.append(Track9IVObservation(
        symbol=symbol, expiry="2026-10-15", option_type=option_type,
        strike=Decimal(str(strike)), implied_volatility=Decimal(str(iv)),
        observed_at=observed_at, source="KIS:H0IOCNT0",
    ))


def test_atm_source_selects_nearest_listed_strike_and_reads_history(tmp_path):
    store = KISTrack9IVObservationHistoryStore(tmp_path / "iv.jsonl")
    observed = datetime.fromisoformat("2026-09-18T09:00:00")
    _append(store, "CALL500", "CALL", "500", "0.24", observed)
    _append(store, "PUT500", "PUT", "500", "0.26", observed)
    _append(store, "CALL502", "CALL", "502.5", "0.30", observed)
    _append(store, "PUT502", "PUT", "502.5", "0.32", observed)

    source = KISTrack9ATMIVSource(option_master=_master(), history_source=store)
    snapshot = source.snapshot(
        symbol="KOSPI200", expiry="202610", current_price=Decimal("501.25"),
        observed_at=observed,
    )

    assert snapshot is not None
    assert snapshot.strike == Decimal("500")
    assert snapshot.call_iv == Decimal("0.24")
    assert snapshot.put_iv == Decimal("0.26")
    assert snapshot.observed_at == observed


def test_atm_source_tie_breaks_to_lower_listed_strike(tmp_path):
    store = KISTrack9IVObservationHistoryStore(tmp_path / "iv.jsonl")
    observed = datetime.fromisoformat("2026-09-18T10:00:00")
    _append(store, "CALL500", "CALL", "500", "0.25", observed)
    _append(store, "PUT500", "PUT", "500", "0.27", observed)
    _append(store, "CALL502", "CALL", "502.5", "0.31", observed)
    _append(store, "PUT502", "PUT", "502.5", "0.33", observed)

    source = KISTrack9ATMIVSource(option_master=_master(), history_source=store)
    snapshot = source.snapshot(
        symbol="KOSPI200", expiry="202610", current_price=Decimal("501.25"),
        observed_at=observed,
    )

    assert snapshot is not None
    assert snapshot.strike == Decimal("500")


def test_atm_source_uses_latest_observation_at_or_before_runtime_time(tmp_path):
    store = KISTrack9IVObservationHistoryStore(tmp_path / "iv.jsonl")
    first = datetime.fromisoformat("2026-09-18T09:00:00")
    second = datetime.fromisoformat("2026-09-18T09:30:00")
    _append(store, "CALL500", "CALL", "500", "0.24", first)
    _append(store, "PUT500", "PUT", "500", "0.26", first)
    _append(store, "CALL500", "CALL", "500", "0.28", second)
    _append(store, "PUT500", "PUT", "500", "0.30", second)

    source = KISTrack9ATMIVSource(option_master=_master(), history_source=store)
    snapshot = source.snapshot(
        symbol="KOSPI200", expiry="202610", current_price=Decimal("500.10"),
        observed_at=datetime.fromisoformat("2026-09-18T09:45:00"),
    )

    assert snapshot is not None
    assert snapshot.call_iv == Decimal("0.28")
    assert snapshot.put_iv == Decimal("0.30")
    assert snapshot.observed_at == second
