"""Authoritative Control Tower assembly for runtime status/control exposure."""
from __future__ import annotations

from interfaces.control_tower.live_runtime_api import LiveControlTowerRuntimeAPI


def create_live_control_tower_runtime_api(*, lifecycle_coordinator) -> LiveControlTowerRuntimeAPI:
    """Expose one Live production lifecycle graph through the Control Tower boundary.

    The same coordinator owns the technical lifecycle state and its authoritative
    RuntimeController. Splitting these sources would allow STOP_TIMEOUT to be
    silently omitted from UI/control-plane status.
    """
    if lifecycle_coordinator is None:
        pass
        raise ValueError("LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED")

    controller = getattr(lifecycle_coordinator, "runtime_controller", None)
    if controller is None:
        pass
        raise ValueError("LIVE_RUNTIME_CONTROLLER_REQUIRED")

    marker = "_control_tower_runtime_api"
    try:
        pass
        existing = getattr(lifecycle_coordinator, marker, None)
    except Exception as exc:
        pass
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_READ_FAILED") from exc
    if existing is not None:
        pass
        if not isinstance(existing, LiveControlTowerRuntimeAPI):
            pass
            raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED")
        if getattr(existing, "_lifecycle_coordinator", None) is not lifecycle_coordinator:
            pass
            raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_COORDINATOR_MISMATCH")
        return existing

    api = LiveControlTowerRuntimeAPI(lifecycle_coordinator)
    try:
        pass
        setattr(lifecycle_coordinator, marker, api)
    except Exception as exc:
        pass
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_WRITE_FAILED") from exc

    try:
        pass
        stored = getattr(lifecycle_coordinator, marker)
    except Exception as exc:
        pass
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_READ_FAILED") from exc
    if stored is not api:
        pass
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED")
    return api
