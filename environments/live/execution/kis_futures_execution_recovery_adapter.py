from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Sequence

from contracts.types import DataQuality, ExecutionReport


KIS_FUTURES_EXECUTION_INQUIRY_PATH = "/uapi/domestic-futureoption/v1/trading/inquire-ccnl"
KIS_FUTURES_EXECUTION_INQUIRY_REAL_TR_ID = "TTTO5201R"
KIS_FUTURES_EXECUTION_INQUIRY_VTS_TR_ID = "VTTO5201R"


class KISExecutionRecoveryInvalid(ValueError):
    """Raised when authoritative REST recovery data cannot be safely normalized."""


@dataclass(frozen=True)
class KISExecutionRecoveryQuery:
    cano: str
    account_product_code: str
    start_order_date: str
    end_order_date: str
    virtual: bool = False
    ctx_area_fk200: str = ""
    ctx_area_nk200: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.cano, "CANO"),
            (self.account_product_code, "ACNT_PRDT_CD"),
            (self.start_order_date, "STRT_ORD_DT"),
            (self.end_order_date, "END_ORD_DT"),
        ):
            if not str(value).strip():
                raise KISExecutionRecoveryInvalid(f"{name}_REQUIRED")

    @property
    def tr_id(self) -> str:
        return (
            KIS_FUTURES_EXECUTION_INQUIRY_VTS_TR_ID
            if self.virtual
            else KIS_FUTURES_EXECUTION_INQUIRY_REAL_TR_ID
        )

    def params(self) -> Mapping[str, str]:
        return {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.account_product_code,
            "STRT_ORD_DT": self.start_order_date,
            "END_ORD_DT": self.end_order_date,
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_NCCS_DVSN": "01",
            "SORT_SQN": "DS",
            "PDNO": "",
            "STRT_ODNO": "",
            "MKET_ID_CD": "",
            "CTX_AREA_FK200": self.ctx_area_fk200,
            "CTX_AREA_NK200": self.ctx_area_nk200,
        }


@dataclass(frozen=True)
class KISExecutionRecoveryContext:
    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int = 0
    prior_average_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise KISExecutionRecoveryInvalid("CLIENT_ORDER_ID_REQUIRED")
        if self.order_quantity <= 0:
            raise KISExecutionRecoveryInvalid("ORDER_QUANTITY_REQUIRED")
        if self.prior_filled_quantity < 0:
            raise KISExecutionRecoveryInvalid("PRIOR_FILLED_QUANTITY_INVALID")


class KISFuturesExecutionRecoveryAdapter:
    """Normalize the official KIS inquire-ccnl order-level fill snapshot."""

    PATH = KIS_FUTURES_EXECUTION_INQUIRY_PATH

    def build_request(self, query: KISExecutionRecoveryQuery) -> tuple[str, str, Mapping[str, str]]:
        return self.PATH, query.tr_id, query.params()

    def to_execution_report(
        self,
        row: Mapping[str, object],
        context: KISExecutionRecoveryContext,
    ) -> ExecutionReport | None:
        order_id = self._required(row, "odno")
        cumulative = self._non_negative_int(row, "tot_ccld_qty")
        if cumulative < context.prior_filled_quantity:
            raise KISExecutionRecoveryInvalid("CUMULATIVE_FILLED_QUANTITY_REGRESSION")
        if cumulative > context.order_quantity:
            raise KISExecutionRecoveryInvalid("EXECUTION_QUANTITY_EXCEEDS_ORDER")

        delta = cumulative - context.prior_filled_quantity
        if delta == 0:
            return None

        cumulative_average = self._positive_decimal(row, "avg_idx")
        price = self._delta_execution_price(
            cumulative=cumulative,
            cumulative_average=cumulative_average,
            prior_filled_quantity=context.prior_filled_quantity,
            prior_average_price=context.prior_average_price,
        )
        status = "FILLED" if cumulative == context.order_quantity else "PARTIALLY_FILLED"
        execution_id = self._snapshot_identity(order_id, cumulative, cumulative_average)

        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=order_id,
            execution_id=execution_id,
            status=status,
            filled_quantity=delta,
            remaining_quantity=context.order_quantity - cumulative,
            execution_price=price,
            execution_timestamp=self._timestamp_or_none(row),
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="KIS inquire-ccnl REST recovery order snapshot",
            ),
        )

    def normalize(
        self,
        response: Mapping[str, object],
        context_for_order: Callable[[str], KISExecutionRecoveryContext],
    ) -> tuple[ExecutionReport, ...]:
        rows = response.get("output1")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise KISExecutionRecoveryInvalid("OUTPUT1_REQUIRED")

        reports: list[ExecutionReport] = []
        cumulative_by_order: dict[str, int] = {}
        average_by_order: dict[str, Decimal | None] = {}
        context_by_order: dict[str, KISExecutionRecoveryContext] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise KISExecutionRecoveryInvalid("OUTPUT1_ROW_INVALID")
            order_id = self._required(row, "odno")
            if order_id not in context_by_order:
                context_by_order[order_id] = context_for_order(order_id)
                cumulative_by_order[order_id] = context_by_order[order_id].prior_filled_quantity
                average_by_order[order_id] = context_by_order[order_id].prior_average_price
            base_context = context_by_order[order_id]
            current_context = KISExecutionRecoveryContext(
                client_order_id=base_context.client_order_id,
                order_quantity=base_context.order_quantity,
                prior_filled_quantity=cumulative_by_order[order_id],
                prior_average_price=average_by_order[order_id],
            )
            report = self.to_execution_report(row, current_context)
            if report is not None:
                reports.append(report)
                cumulative_by_order[order_id] += report.filled_quantity
                average_by_order[order_id] = self._positive_decimal(row, "avg_idx")
        return tuple(reports)

    @staticmethod
    def _required(row: Mapping[str, object], key: str) -> str:
        value = str(row.get(key, "")).strip()
        if not value:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_REQUIRED")
        return value

    @staticmethod
    def _non_negative_int(row: Mapping[str, object], key: str) -> int:
        try:
            value = int(str(row.get(key, "")).strip())
        except (TypeError, ValueError) as exc:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID") from exc
        if value < 0:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID")
        return value

    @staticmethod
    def _positive_decimal(row: Mapping[str, object], key: str) -> Decimal:
        try:
            value = Decimal(str(row.get(key, "")).strip())
        except (InvalidOperation, ValueError) as exc:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID") from exc
        if value <= 0:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID")
        return value

    @staticmethod
    def _delta_execution_price(
        *,
        cumulative: int,
        cumulative_average: Decimal,
        prior_filled_quantity: int,
        prior_average_price: Decimal | None,
    ) -> Decimal:
        if prior_filled_quantity == 0:
            return cumulative_average
        if prior_average_price is None:
            raise KISExecutionRecoveryInvalid("PRIOR_AVERAGE_PRICE_REQUIRED_FOR_DELTA_PRICE")
        delta_quantity = cumulative - prior_filled_quantity
        if delta_quantity <= 0:
            raise KISExecutionRecoveryInvalid("DELTA_QUANTITY_INVALID")
        delta_price = (
            cumulative_average * Decimal(cumulative)
            - prior_average_price * Decimal(prior_filled_quantity)
        ) / Decimal(delta_quantity)
        if delta_price <= 0:
            raise KISExecutionRecoveryInvalid("DELTA_EXECUTION_PRICE_INVALID")
        return delta_price

    @staticmethod
    def _snapshot_identity(order_id: str, cumulative: int, cumulative_average: Decimal) -> str:
        return f"REST-CCNL-SNAPSHOT|{order_id}|{cumulative}|{cumulative_average}"

    @staticmethod
    def _timestamp_or_none(row: Mapping[str, object]) -> datetime | None:
        order_date = str(row.get("ord_dt", "")).strip()
        order_time = str(row.get("ord_tmd", "")).strip()
        if len(order_date) == 8 and order_date.isdigit() and len(order_time) == 6 and order_time.isdigit():
            return datetime.strptime(order_date + order_time, "%Y%m%d%H%M%S")
        return None
