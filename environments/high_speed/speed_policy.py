from dataclasses import dataclass

ALLOWED_SPEEDS = (1.0, 100.0, 300.0, 500.0, 1000.0)

@dataclass(frozen=True)
class HighSpeedPolicy:
    speed_multiplier: float = 1.0
    max_cpu_ratio: float = 0.90
    max_memory_ratio: float = 0.90

    def validate(self) -> None:
        if self.speed_multiplier not in ALLOWED_SPEEDS and self.speed_multiplier != float("inf"):
            raise ValueError("unsupported speed multiplier")
        if not 0 < self.max_cpu_ratio <= 1:
            raise ValueError("invalid max_cpu_ratio")
        if not 0 < self.max_memory_ratio <= 1:
            raise ValueError("invalid max_memory_ratio")

    @property
    def is_max(self) -> bool:
        return self.speed_multiplier == float("inf")
