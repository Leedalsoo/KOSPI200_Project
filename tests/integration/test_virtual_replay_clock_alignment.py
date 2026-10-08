from datetime import datetime

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


def test_replay_tick_synchronizes_virtual_clock_for_execution_timestamp():
    runtime = VirtualMarketSimulatorRuntime()
    observed_at = datetime(2025, 1, 3, 9, 5, 0)
    tick = ReferenceCanonicalMarketTick(
        timestamp=observed_at.isoformat(),
        underlying_price=350.0,
        bid_price=1.0,
        ask_price=1.1,
        last_price=1.05,
        strike_price=350.0,
        option_type="CALL",
        contract_multiplier=250000.0,
        expiry="20250116",
        symbol="SYN-202501-CALL-350",
        instrument_id="SYN-202501-CALL-350",
    )

    runtime.publish_replay_tick(tick)

    assert runtime.clock.current_time == observed_at
