from environments.virtual.authoritative_vssf.canonical import CanonicalExecutionReport


class ExecutionEngine:
    def __init__(self):
        self.reports = []
        self._seq = 0

    def execute_order(self, command, price, qty, *, timestamp):
        self._seq += 1
        rep = CanonicalExecutionReport(
            f"EXEC-{self._seq:06d}", command.client_order_id, command.track_id,
            command.asset_type, command.side, int(qty), float(price), 0.0, 0.0,
            timestamp.isoformat(), symbol=getattr(command, "symbol", "KOSPI200"),
            option_type=getattr(command, "option_type", None),
            strike=float(getattr(command, "strike", 0.0)),
            expiry=getattr(command, "expiry", ""),
            strategy_id=getattr(command, "strategy_id", ""),
            group_id=getattr(command, "group_id", ""),
            leg_id=getattr(command, "leg_id", ""),
            instrument_id=getattr(command, "instrument_id", ""),
            contract_multiplier=getattr(command, "contract_multiplier", None),
            identity_source=getattr(command, "identity_source", ""),
        )
        self.reports.append(rep)
        return rep
