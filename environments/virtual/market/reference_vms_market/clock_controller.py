from datetime import datetime, timedelta
from typing import Optional


class VMSClockController:
    def __init__(self, start_time: Optional[datetime] = None):
        self.current_time = start_time or datetime(2026, 8, 23, 9, 0, 0)

    def advance_tick(self, milliseconds: int = 500) -> datetime:
        self.current_time += timedelta(milliseconds=milliseconds)
        return self.current_time

    def get_time_str(self) -> str:
        return self.current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
