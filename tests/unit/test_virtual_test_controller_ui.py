from application.control_tower_hub import ControlTowerHub


class FakeRuntimeController:
    def status(self):
        return type("Status", (), {"state": "STOPPED"})()


class FakeUIAdapter:
    def get_summary(self):
        return {"active_environment": "virtual_exchange"}

    def get_tab_detail(self, tab_id):
        return {"tab_id": tab_id}

    def handle_command(self, command):
        return {"command": command}


class FakeVirtualTestController:
    def __init__(self):
        self.commands = []

    def read_model(self):
        return {"state": "READY", "kill_switch": True}

    def arm_for_test(self):
        self.commands.append("ARM")

    def start(self):
        self.commands.append("START")

    def pause(self):
        self.commands.append("PAUSE")

    def next_tick(self):
        self.commands.append("NEXT_TICK")
        return "tick"

    def reset(self):
        self.commands.append("RESET")

    def engage_kill_switch(self, reason):
        self.commands.append(("KILL", reason))


def build_hub(controller):
    return ControlTowerHub(
        runtime_controller=FakeRuntimeController(),
        ui_adapter=FakeUIAdapter(),
        virtual_test_controller=controller,
    )


def test_control_tower_exposes_virtual_test_read_model_and_actions():
    controller = FakeVirtualTestController()
    hub = build_hub(controller)

    assert hub.virtual_test_read_model() == {"state": "READY", "kill_switch": True}
    assert hub.virtual_test_action("ARM") == {"state": "READY", "kill_switch": True}
    assert hub.virtual_test_action("START")["state"] == "READY"
    assert hub.virtual_test_action("NEXT_TICK")["tick"] == "tick"
    assert controller.commands == ["ARM", "START", "NEXT_TICK"]


def test_control_tower_rejects_unknown_virtual_test_action():
    hub = build_hub(FakeVirtualTestController())
    try:
        hub.virtual_test_action("UNKNOWN")
    except ValueError as exc:
        assert str(exc) == "UNSUPPORTED_VIRTUAL_TEST_ACTION:UNKNOWN"
    else:
        raise AssertionError("unknown virtual test action must be rejected")
