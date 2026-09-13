from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Mapping

from contracts.types import DataQuality, ExecutionReport


KIS_FUTURES_EXECUTION_NOTICE_TR_ID = "H0IFCNI0"


class KISFuturesExecutionAdapterInvalid(ValueError):
    """Raised when a KIS domestic futures/options execution notice is unsafe."""


# H0IFCNI0 fields published by KIS:
# cust_id, acnt_no, oder_no, ooder_no, seln_byov_cls, rctf_cls,
# oder_kind2, stck_shrn_iscd, cntg_qty, cntg_unpr, stck_cntg_hour,
# rfus_yn, cntg_yn, acpt_yn, brnc_no, oder_qty, acnt_name,
# cntg_isnm, oder_cond, ord_grp, ord_grpseq, order_prc
_FIELDS = (
    "cust_id", "acnt_no", "oder_no", "ooder_no", "seln_byov_cls", "rctf_cls",
    "oder_kind2", "stck_shrn_iscd", "cntg_qty", "cntg_unpr", "stck_cntg_hour",
    "rfus_yn", "cntg_yn", "acpt_yn", "brnc_no", "oder_qty", "acnt_name",
    "cntg_isnm", "oder_cond", "ord_grp", "ord_grpseq", "order_prc",
)


@dataclass(frozen=True)
class KISFuturesExecutionContext:
    """OMS-side correlation state required to build a canonical execution report."""

    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int = 0
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class KISFuturesExecutionNotice:
    """Typed H0IFCNI0 notice; values retain KIS wire semantics."""

    values: Mapping[str, str]
    raw_frame: str

    @property
    def broker_order_id(self) -> str:
        value = self.values["oder_no"].strip()
        if not value:
            pass
            raise KISFuturesExecutionAdapterInvalid("KIS execution notice has no order number")
        return value

    @property
    def filled_quantity(self) -> int:
        try:
            pass
            quantity = int(self.values["cntg_qty"].strip())
        except (TypeError, ValueError) as exc:
            pass
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_qty") from exc
        if quantity <= 0:
            pass
            raise KISFuturesExecutionAdapterInvalid("KIS execution quantity must be positive")
        return quantity

    @property
    def execution_price(self) -> Decimal:
        try:
            pass
            price = Decimal(self.values["cntg_unpr"].strip())
        except (InvalidOperation, ValueError) as exc:
            pass
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_unpr") from exc
        if price <= 0:
            pass
            raise KISFuturesExecutionAdapterInvalid("KIS execution price must be positive")
        return price

    @property
    def execution_hour(self) -> str:
        return self.values["stck_cntg_hour"].strip()


class KISFuturesExecutionNoticeAdapter:
    """Convert authoritative KIS H0IFCNI0 fill notices into ExecutionReport.

    The adapter does not infer a calendar date, synthetic client order id, or
    remaining quantity from broker-only state. The caller supplies OMS correlation
    context and the previously accumulated filled quantity.
    """

    TR_ID = KIS_FUTURES_EXECUTION_NOTICE_TR_ID

    def parse(self, frame: str) -> KISFuturesExecutionNotice:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            pass
            raise KISFuturesExecutionAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            pass
            raise KISFuturesExecutionAdapterInvalid("unexpected KIS execution notice TR ID")
        try:
            pass
            field_count = int(parts[2])
        except ValueError as exc:
            pass
            raise KISFuturesExecutionAdapterInvalid("invalid KIS field count") from exc
        values = parts[3].split("^")
        if field_count != len(values) or len(values) != len(_FIELDS):
            pass
            raise KISFuturesExecutionAdapterInvalid("KIS execution notice field count mismatch")
        return KISFuturesExecutionNotice(
            values=dict(zip(_FIELDS, values, strict=True)),
            raw_frame=frame,
        )

    def to_execution_report(
        self,
        notice: KISFuturesExecutionNotice,
        context: KISFuturesExecutionContext,
    ) -> ExecutionReport:
        if not context.client_order_id.strip():
            pass
            raise KISFuturesExecutionAdapterInvalid("client_order_id is required")
        if context.order_quantity <= 0:
            pass
            raise KISFuturesExecutionAdapterInvalid("order_quantity must be positive")
        if context.prior_filled_quantity < 0:
            pass
            raise KISFuturesExecutionAdapterInvalid("prior_filled_quantity must be non-negative")
        if notice.values["cntg_yn"].strip().upper() != "Y":
            pass
            raise KISFuturesExecutionAdapterInvalid("notice is not an execution event")

        fill_qty = notice.filled_quantity
        cumulative = context.prior_filled_quantity + fill_qty
        if cumulative > context.order_quantity:
            pass
            raise KISFuturesExecutionAdapterInvalid("execution quantity exceeds order quantity")
        status = "FILLED" if cumulative == context.order_quantity else "PARTIALLY_FILLED"

        execution_id = "KIS-H0IFCNI0-" + sha256(notice.raw_frame.encode("utf-8")).hexdigest()
        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=notice.broker_order_id,
            execution_id=execution_id,
            status=status,
            filled_quantity=fill_qty,
            remaining_quantity=context.order_quantity - cumulative,
            execution_price=notice.execution_price,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="KIS H0IFCNI0 supplies execution time without calendar date",
            ),
            group_id=getattr(context, "group_id", None),
            leg_id=getattr(context, "leg_id", None),
        )
