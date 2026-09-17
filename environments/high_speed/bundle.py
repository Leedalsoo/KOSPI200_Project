from dataclasses import dataclass

from environments.high_speed.clock import AcceleratedClock, AcceleratedClockConfig
from environments.high_speed.replay import ReplayStream
from environments.high_speed.speed_policy import HighSpeedPolicy

@dataclass
class HighSpeedEnvironmentBundle:
    """High-Speed is a Virtual execution policy, not a second trading Core."""
    policy: HighSpeedPolicy
    clock: AcceleratedClock
    replay: ReplayStream

    @classmethod
    def create(cls, policy: HighSpeedPolicy, clock, replay: ReplayStream):
# policy.validate()
        accelerated = AcceleratedClock(
            AcceleratedClockConfig(policy.speed_multiplier), clock.now
        )
        return cls(policy=policy, clock=accelerated, replay=replay)

    def stop_safely(self, cpu_ratio: float, memory_ratio: float) -> bool:
        if cpu_ratio >= self.policy.max_cpu_ratio:
            return True
        if memory_ratio >= self.policy.max_memory_ratio:
            return True
        return False
