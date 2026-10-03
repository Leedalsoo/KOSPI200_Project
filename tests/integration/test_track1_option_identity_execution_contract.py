from types import SimpleNamespace
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from environments.virtual.market.replay_engine import HistoricalReplayEngine
from tests.risk_guard_test_support import allow_risk_guard


def test_option_master_standard_identity_is_shared_by_replay_and_execution():
    bootstrap = create_virtual_runtime_bootstrap(
        initial_capital=250_000_000.0,
        risk_guard_status_source=allow_risk_guard(),
    )
    loop = bootstrap.automated_loop
    master = bootstrap.bundle.option_master

    identity = master.find_contract_identity(
        "2026-10-08", "CALL", Decimal("1105.0")
    )
    assert identity is not None
    assert identity.stnd_iscd
    assert identity.shrn_iscd

    evaluation = SimpleNamespace(
        result=SimpleNamespace(
            execution_proposal=SimpleNamespace(
                asset_type="OPTION",
                option_type="CALL",
                strike=Decimal("1105.0"),
            )
        )
    )
    runtime_identity = loop.identity_provider(evaluation, SimpleNamespace(expiry="2026-10-08"))
    assert runtime_identity.instrument_id == identity.stnd_iscd
    assert runtime_identity.symbol == identity.shrn_iscd

    store = HistoricalMarketStore(
        "data/kis_market_data_restart/2026-09-28/historical_market_observations.jsonl"
    )
    replay = HistoricalReplayEngine.from_observation_store(store)
    tick = replay.next_tick()
    published = bootstrap.bundle.market.publish_replay_tick(tick)
    replay_identity = master.find_contract_identity(
        published.expiry, published.option_type, Decimal(str(published.strike_price))
    )
    assert replay_identity is not None
    # Replay preserves the broker-observed WS identity; Master identity is resolved separately.
    assert published.instrument_id == tick.instrument_id
    assert published.symbol == tick.symbol
    assert replay_identity.stnd_iscd != published.instrument_id
    assert replay_identity.shrn_iscd == published.symbol
