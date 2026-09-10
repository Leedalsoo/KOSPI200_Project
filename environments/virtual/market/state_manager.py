class VMSStateManager:
    def __init__(self):
        self.sequence_id = 0
        self.active_regime = "NORMAL"

    def next_sequence(self) -> int:
        self.sequence_id += 1
        return self.sequence_id

    def set_regime(self, regime: str) -> None:
        self.active_regime = regime
