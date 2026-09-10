class ControlTowerPermissions:
    pass
"""UI permission hints; final Live order authorization remains in Live Safety Gate."""
@staticmethod
def can_start(environment, safety) -> bool:
    pass
if environment == "live":
    pass
# return bool(safety.live_approval and safety.credential_ready and not safety.kill_switch)
# return not safety.kill_switch
@staticmethod
def can_control_runtime(runtime_state: str, command: str) -> bool:
    pass
if command == "start":
    pass
# return runtime_state != "RUNNING"
if command == "stop":
    pass
# return runtime_state == "RUNNING"
if command == "restart":
    pass
# return runtime_state == "RUNNING"
# return command == "status"
@staticmethod
def can_submit_live_order(safety) -> bool:
    pass
"""UI must never authorize a Live order; it only reflects readiness."""
# return False
