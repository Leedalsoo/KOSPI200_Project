from datetime import datetime
from decimal import Decimal

from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine
from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
from environments.virtual.authoritative_vssf.position_manager import PositionManager
from shared.contracts.canonical import CanonicalAccountSummary


class PaperTradingAccount:
    def __init__(
        self, initial_capital=25000000.0, *,
        validation_run_id: str | None = None,
        validation_candidate_id: str | None = None,
    ):
        if (validation_run_id is None) != (validation_candidate_id is None):
            raise ValueError("VSSF_ACCOUNT_VALIDATION_RUN_AND_CANDIDATE_ID_REQUIRED_TOGETHER")
        if validation_run_id is not None and (
            not validation_run_id.strip() or not validation_candidate_id.strip()
        ):
            raise ValueError("VSSF_ACCOUNT_VALIDATION_SCOPE_ID_REQUIRED")
        self.validation_run_id = validation_run_id
        self.validation_candidate_id = validation_candidate_id
        capital=Decimal(str(initial_capital)); self.balance=capital; self.realized_pnl=Decimal('0'); self.unrealized_pnl=Decimal('0'); self.position_mgr=PositionManager(); self.pnl_engine=PnLEngine(); self.margin_engine=MarginEngine(initial_capital); self.ledger_engine=LedgerEngine(); self.free_margin=capital; self.used_margin=Decimal('0')
    @property
    def positions(self): return self.position_mgr.positions
    def get_canonical_summary(self):
        total=self.balance+self.realized_pnl+self.unrealized_pnl
        return CanonicalAccountSummary('ACC-VSSF-001',total,self.realized_pnl,self.unrealized_pnl,self.used_margin,self.free_margin,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),positions={k:dict(v) for k,v in self.positions.items()})
    def update_tick_price(self, price, instrument_id=None):
        if instrument_id is not None:
            self.position_mgr.update_market_price(str(instrument_id), price)
        self.unrealized_pnl=self.pnl_engine.calculate_unrealized(self.positions,price); self.used_margin=self.margin_engine.calculate_used_margin(self.positions); equity=self.balance+self.realized_pnl+self.unrealized_pnl; self.free_margin=self.margin_engine.calculate_free_margin(equity,self.used_margin)
    @staticmethod
    def _execution_identity_fingerprint(rep):
        from decimal import Decimal

        execution_id = str(getattr(rep, "exec_id", "") or "").strip()
        if not execution_id:
            raise ValueError("VSSF_ACCOUNT_EXECUTION_ID_REQUIRED")
        side = getattr(rep, "side", "")
        side = str(getattr(side, "value", side)).upper()
        price = Decimal(str(rep.executed_price))
        fee = Decimal(str(getattr(rep, "fee", 0) or 0))
        multiplier = getattr(rep, "contract_multiplier", None)
        multiplier = None if multiplier is None else Decimal(str(multiplier))
        def enum_value(value):
            return str(getattr(value, "value", value) or "")

        strike = getattr(rep, "strike", None)
        strike = None if strike is None else str(Decimal(str(strike)).normalize())
        return (
            str(getattr(rep, "client_order_id", "") or ""),
            str(getattr(rep, "track_id", "") or ""),
            str(getattr(rep, "strategy_id", "") or ""),
            str(getattr(rep, "group_id", "") or ""),
            str(getattr(rep, "leg_id", "") or ""),
            str(getattr(rep, "instrument_id", "") or ""),
            str(getattr(rep, "identity_source", "") or ""),
            str(getattr(rep, "symbol", "") or ""),
            enum_value(getattr(rep, "asset_type", "")),
            enum_value(getattr(rep, "option_type", "")),
            strike,
            str(getattr(rep, "expiry", "") or ""),
            side,
            int(getattr(rep, "executed_qty", 0)),
            str(price.normalize()),
            str(fee.normalize()),
            None if multiplier is None else str(multiplier.normalize()),
            str(getattr(rep, "timestamp", getattr(rep, "execution_timestamp", "")) or ""),
        )

    def apply_execution(self, rep):
        execution_id = str(getattr(rep, "exec_id", "") or "").strip()
        fingerprint = self._execution_identity_fingerprint(rep)
        matching_rows = [
            row for row in self.ledger_engine.transactions
            if isinstance(row, dict) and row.get("exec_id") == execution_id
        ]
        if len(matching_rows) > 1:
            raise ValueError("VSSF_ACCOUNT_EXECUTION_ID_DUPLICATE_LEDGER_ROWS")
        if matching_rows:
            prior = matching_rows[0].get("execution_fingerprint")
            if prior is None:
                raise ValueError("VSSF_ACCOUNT_EXECUTION_IDENTITY_UNVERIFIABLE")
            if tuple(prior) != fingerprint:
                raise ValueError("VSSF_ACCOUNT_EXECUTION_ID_PAYLOAD_CONFLICT")
            return matching_rows[0].get("realized_pnl_delta", Decimal(0))
        pnl = self.position_mgr.update_position(
            rep.symbol,
            rep.side.value if hasattr(rep.side, "value") else str(rep.side),
            rep.executed_qty,
            rep.executed_price,
            contract_multiplier=getattr(rep, "contract_multiplier", None),
        )
        self.pnl_engine.add_realized(pnl)
        self.realized_pnl = self.pnl_engine.realized_pnl
        self.balance -= Decimal(str(rep.fee))
        self.unrealized_pnl = self.pnl_engine.calculate_unrealized(
            self.positions, rep.executed_price,
        )
        self.used_margin = self.margin_engine.calculate_used_margin(self.positions)
        equity = self.balance + self.realized_pnl + self.unrealized_pnl
        self.free_margin = self.margin_engine.calculate_free_margin(equity, self.used_margin)
        self.ledger_engine.transactions.append({"exec_id": execution_id, "execution_fingerprint": fingerprint, "realized_pnl_delta": Decimal(str(pnl))})
