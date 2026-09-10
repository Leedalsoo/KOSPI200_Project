# Integration contract test for No.491.

def test_explicit_lifecycle_order_and_shared_settlement_state():
    events = []
    shared_state = {"oms": "OMS-1", "position": "POSITION-1"}
    controller = RuntimeController(Hub(Bundle(events)))
    execution = Execution(events, shared_state)
    recovery = Recovery(events)
    bootstrap = LiveRuntimeBootstrap(
        execution=execution,
        order_router=object(),
        recovery_service=recovery,
    )

# controller.start("live-config", "live-policy")
    assert controller._state == "RUNNING"
    assert bootstrap.startup_reconcile("Q1") == "SETTLED"
# asyncio.run(bootstrap.start_execution("HTS"))
# assert asyncio.run(bootstrap.receive_execution_once()) is shared_state
# asyncio.run(bootstrap.close_execution())
# controller.stop()

    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "recovery.startup_reconcile", "execution.start",
        "execution.receive", "execution.close",
        "bundle.stop", "bundle.shutdown",
    ]
    assert controller._state == "STOPPED"
# assert controller._hub.active is None


def test_no_implicit_bootstrap_or_execution_lifecycle_inside_controller():
    events = []
    controller = RuntimeController(Hub(Bundle(events)))
# controller.start("live-config", "live-policy")
    assert events == ["bundle.initialize", "bundle.connect", "bundle.start"]
# controller.stop()
    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "bundle.stop", "bundle.shutdown",
    ]
