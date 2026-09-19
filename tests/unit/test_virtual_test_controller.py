from decimal import Decimal

import pytest

from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from interfaces.control_tower.virtual_test_controller import VirtualTestController
from tests.support import build_test_option_master


def build_controller():
    market = VirtualMarketSimulatorRuntime(option_master=build_test_option_master())
    return VirtualTestController(market=market)


def test_controller_exposes_scenarios_and_starts_fail_safe():
    controller = build_controller()

    state = controller.read_model()

    assert state["state"] == "READY"
    assert "CALM" in state["available_scenarios"]
    assert "HIGH_VOLATILITY" in state["available_scenarios"]
    assert state["kill_switch"] is True


def test_controller_can_start_pause_and_step_market():
    controller = build_controller()
    controller.set_scenario("CALM")
    controller.arm_for_test()

    controller.start()
    tick = controller.next_tick()
    controller.pause()

    assert tick is not None
    assert tick.contract_multiplier == 250000.0
    assert tick.strike_price == round(tick.underlying_price / 2.5) * 2.5
    assert controller.read_model()["state"] == "PAUSED"
    assert controller.read_model()["processed_ticks"] == 1


def test_controller_reset_creates_clean_run_state():
    controller = build_controller()
    controller.arm_for_test()
    controller.start()
    controller.next_tick()
    controller.reset()

    state = controller.read_model()
    assert state["state"] == "READY"
    assert state["processed_ticks"] == 0
    assert state["last_tick"] is None


def test_controller_kill_switch_blocks_next_tick_until_reset():
    controller = build_controller()
    controller.arm_for_test()
    controller.start()
    controller.engage_kill_switch("TEST_FAULT")

    with pytest.raises(RuntimeError, match="VIRTUAL_TEST_KILL_SWITCH_ENGAGED"):
        controller.next_tick()

    assert controller.read_model()["kill_switch"] is True
    controller.reset()
    assert controller.read_model()["kill_switch"] is True
