폴더 페이지

실제 KIS 국내선물옵션 체결통보(H0IFCNI0) 기반 Live Execution adapter를 둔다. ACK/주문전송과 분리하고, canonical ExecutionReport만 반환한다.

[Child Page] kis_futures_execution_adapter.py
```python
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
            raise KISFuturesExecutionAdapterInvalid("KIS execution notice has no order number")
        return value

    @property
    def filled_quantity(self) -> int:
        try:
            quantity = int(self.values["cntg_qty"].strip())
        except (TypeError, ValueError) as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_qty") from exc
        if quantity <= 0:
            raise KISFuturesExecutionAdapterInvalid("KIS execution quantity must be positive")
        return quantity

    @property
    def execution_price(self) -> Decimal:
        try:
            price = Decimal(self.values["cntg_unpr"].strip())
        except (InvalidOperation, ValueError) as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_unpr") from exc
        if price <= 0:
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
            raise KISFuturesExecutionAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise KISFuturesExecutionAdapterInvalid("unexpected KIS execution notice TR ID")
        try:
            field_count = int(parts[2])
        except ValueError as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS field count") from exc
        values = parts[3].split("^")
        if field_count != len(values) or len(values) != len(_FIELDS):
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
            raise KISFuturesExecutionAdapterInvalid("client_order_id is required")
        if context.order_quantity <= 0:
            raise KISFuturesExecutionAdapterInvalid("order_quantity must be positive")
        if context.prior_filled_quantity < 0:
            raise KISFuturesExecutionAdapterInvalid("prior_filled_quantity must be non-negative")
        if notice.values["cntg_yn"].strip().upper() != "Y":
            raise KISFuturesExecutionAdapterInvalid("notice is not an execution event")

        fill_qty = notice.filled_quantity
        cumulative = context.prior_filled_quantity + fill_qty
        if cumulative > context.order_quantity:
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
            group_id=context.group_id,
            leg_id=context.leg_id,
        )
```
## KIS authoritative source
    - H0IFCNI0 = 국내선물옵션 실시간체결통보.
    - KIS 공식 예제의 필드는 oder_no, cntg_qty, cntg_unpr, stck_cntg_hour, cntg_yn, oder_qty 등을 포함한다.
    - ACK(BrokerOrderResponse)와 분리하고 실제 cntg_yn=Y 이벤트만 ExecutionReport로 변환한다.
    - client_order_id는 KIS notice에 없으므로 OMS correlation context에서 공급한다.
    - remaining_quantity는 주문수량과 이전 누적체결수량을 사용해 계산한다. cntg_qty는 해당 체결통보의 체결수량으로 취급한다.
    - 날짜가 없는 stck_cntg_hour를 임의 날짜와 결합하지 않아 execution_timestamp=None으로 보존한다.
    - execution_id는 원문 wire frame SHA-256으로 생성하여 동일 frame 재수신을 동일 event로 식별한다.

[Child Page] execution_event_deduplicator.py
```python
from __future__ import annotations

from contracts.types import ExecutionReport


class ExecutionEventDeduplicator:
    """Live-owned exactly-once delivery gate for execution events."""

    def __init__(self) -> None:
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if execution_id in self._seen_execution_ids:
            return False
        self._seen_execution_ids.add(execution_id)
        return True

    def contains(self, execution_id: str) -> bool:
        return str(execution_id).strip() in self._seen_execution_ids
```
## Boundary rules
    - ExecutionReport.execution_id is the authoritative execution-event identity.
    - The first occurrence returns True and records the identity.
    - A repeated identity returns False and is not delivered downstream.
    - Missing execution identity fails closed; no fallback identity is generated.
    - This implementation is Live-owned and does not import Virtual execution code.

[Child Page] kis_futures_execution_correlation_provider.py
```python
from __future__ import annotations

from core.oms.oms_fsm import ExecutionCorrelation, OrderStateMachine


class KISFuturesExecutionCorrelationError(ValueError):
    """Raised when a KIS execution notice cannot be correlated safely."""


class KISFuturesExecutionCorrelationProvider:
    """Resolve H0IFCNI0 broker order numbers from OMS-owned state.

    This provider never creates client_order_id, order quantity, prior fill
    quantity, or prior average price. All values come from the accepted ACK/order
    and execution state already owned by OMS.
    """

    def __init__(self, order_state_machine: OrderStateMachine) -> None:
        self._orders = order_state_machine

    def resolve(self, broker_order_id: str) -> ExecutionCorrelation:
        try:
            return self._orders.resolve_execution_correlation(broker_order_id)
        except Exception as exc:
            raise KISFuturesExecutionCorrelationError(str(exc)) from exc
```
## Boundary
    - Source: OMS OrderStateMachine only.
    - Lookup key: authoritative KIS oder_no / broker_order_id.
    - Returned state: client_order_id, original order quantity, prior cumulative fill quantity, and OMS-maintained prior average execution price when available.
    - No synthetic identity, quantity, date, or broker mapping is generated.
    - Unknown broker order IDs fail closed before ExecutionReport creation.

[Child Page] kis_futures_execution_consumer.py
```python
from __future__ import annotations

from typing import Awaitable, Callable

from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)


class KISFuturesExecutionConsumer:
    """Concrete H0IFCNI0 execution ingress."""

    def __init__(self, transport, adapter: KISFuturesExecutionNoticeAdapter, correlation_provider: KISFuturesExecutionCorrelationProvider, on_report: Callable[[object], Awaitable[None] | None]) -> None:
        self._transport = transport
        self._adapter = adapter
        self._correlation_provider = correlation_provider
        self._on_report = on_report

    async def start(self, hts_id: str) -> None:
        if not hts_id.strip():
            raise ValueError("HTS ID is required")
        await self._transport.connect()
        await self._transport.subscribe(self._adapter.TR_ID, hts_id)

    async def receive_once(self):
        frame = await self._transport.recv()
        notice = self._adapter.parse(frame)
        correlation = self._correlation_provider.resolve(notice.broker_order_id)
        report = self._adapter.to_execution_report(
            notice,
            KISFuturesExecutionContext(correlation.client_order_id, correlation.order_quantity, correlation.prior_filled_quantity),
        )
        result = self._on_report(report)
        if hasattr(result, "__await__"):
            await result
        return report

    async def cancel_receive(self) -> None:
        """Request transport-level interruption of a blocked receive."""
        cancel = getattr(self._transport, "cancel_recv", None)
        if callable(cancel):
            result = cancel()
            if hasattr(result, "__await__"):
                await result
            return
        await self._transport.close()

    async def close(self) -> None:
        await self._transport.close()
```
책임 경계:
    - dedicated execution transport → H0IFCNI0 adapter → OMS correlation → ExecutionReport.
    - Position mutation은 기존 LiveExecutionPositionBridge에 맡긴다.
    - Market consumer/MarketState를 참조하지 않는다.
    - cancel_receive()는 transport-level receive interruption만 수행하며 Domain 주문 상태를 변경하지 않는다.

[Child Page] kis_futures_execution_recovery_adapter.py
```python
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
    """Normalize the official KIS inquire-ccnl order-level fill snapshot.

    The official response exposes order-level cumulative fields such as
    ``odno``, ``ord_qty``, ``qty``, ``tot_ccld_qty`` and ``avg_idx``. It does
    not expose an authoritative execution-level ID. Therefore this adapter
    derives a *REST-source-local snapshot identity* only for exactly-once
    handling of repeated recovery snapshots; it never claims that identity is
    equivalent to the H0IFCNI0 wire identity.
    """

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
```
## Boundary
    - Official KIS inquire-ccnl REST recovery is treated as an order-level cumulative snapshot, not an execution-level event stream.
    - tot_ccld_qty is authoritative cumulative filled quantity and avg_idx is the official average execution index/price field.
    - filled_quantity is the delta from the OMS correlation context's prior cumulative fill.
    - Because avg_idx is an order-level cumulative average, a later snapshot's incremental execution price is derived as (current_avg × current_cumulative_qty − prior_avg × prior_cumulative_qty) / delta_qty when prior average price is available.
    - If recovery starts from an already partially filled OMS state but no authoritative prior average price is available, the incremental execution price is fail-closed rather than guessed.
    - execution_id is a REST-source-local snapshot identity only; it is not asserted to equal H0IFCNI0 identity.
    - ctx_area_fk200 / ctx_area_nk200 are carried by the query for official pagination.
    - Synthetic cross-source identity mapping remains prohibited.

[Child Page] test_kis_futures_execution_recovery_adapter.py
```python
from decimal import Decimal

import pytest

from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryInvalid,
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)


def row(**overrides):
    value = {
        "odno": "00012345",
        "ord_qty": "5",
        "tot_ccld_qty": "2",
        "avg_idx": "350.25",
        "ord_dt": "20260906",
        "ord_tmd": "101530",
    }
    value.update(overrides)
    return value


def context(**overrides):
    value = {
        "client_order_id": "CLIENT-1",
        "order_quantity": 5,
        "prior_filled_quantity": 0,
        "prior_average_price": None,
    }
    value.update(overrides)
    return KISExecutionRecoveryContext(**value)


def test_real_request_contract_matches_official_inquire_ccnl():
    path, tr_id, params = KISFuturesExecutionRecoveryAdapter().build_request(
        KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906")
    )
    assert path == "/uapi/domestic-futureoption/v1/trading/inquire-ccnl"
    assert tr_id == "TTTO5201R"
    assert params["CCLD_NCCS_DVSN"] == "01"
    assert params["SLL_BUY_DVSN_CD"] == "00"
    assert params["SORT_SQN"] == "DS"
    assert params["CTX_AREA_FK200"] == ""
    assert params["CTX_AREA_NK200"] == ""


def test_vts_request_uses_vt_tr_id():
    query = KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906", virtual=True)
    assert query.tr_id == "VTTO5201R"


def test_official_order_snapshot_maps_cumulative_total_to_delta_report():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
    assert report is not None
    assert report.execution_id == "REST-CCNL-SNAPSHOT|00012345|2|350.25"
    assert report.filled_quantity == 2
    assert report.execution_price == Decimal("350.25")
    assert report.status == "PARTIALLY_FILLED"
    assert report.remaining_quantity == 3


def test_recovery_snapshot_uses_prior_fill_and_average_to_calculate_delta_price():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
        row(tot_ccld_qty="5", avg_idx="351.00"),
        context(prior_filled_quantity=2, prior_average_price=Decimal("350.25")),
    )
    assert report is not None
    assert report.filled_quantity == 3
    assert report.execution_price == Decimal("351.50")
    assert report.remaining_quantity == 0
    assert report.status == "FILLED"


def test_preexisting_partial_recovery_without_prior_average_fails_closed():
    with pytest.raises(KISExecutionRecoveryInvalid, match="PRIOR_AVERAGE_PRICE_REQUIRED_FOR_DELTA_PRICE"):
        KISFuturesExecutionRecoveryAdapter().to_execution_report(
            row(tot_ccld_qty="5", avg_idx="351.00"),
            context(prior_filled_quantity=2),
        )


def test_order_date_and_time_reconstruct_execution_timestamp():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
    assert report is not None
    assert report.execution_timestamp is not None
    assert report.execution_timestamp.strftime("%Y%m%d%H%M%S") == "20260906101530"


def test_repeated_same_snapshot_produces_no_new_execution():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
        row(tot_ccld_qty="2"),
        context(prior_filled_quantity=2),
    )
    assert report is None


def test_cumulative_regression_fails_closed():
    with pytest.raises(KISExecutionRecoveryInvalid, match="CUMULATIVE_FILLED_QUANTITY_REGRESSION"):
        KISFuturesExecutionRecoveryAdapter().to_execution_report(
            row(tot_ccld_qty="1"), context(prior_filled_quantity=2)
        )


def test_response_output1_normalization_uses_order_context():
    adapter = KISFuturesExecutionRecoveryAdapter()
    reports = adapter.normalize(
        {
            "output1": [
                row(odno="B1", tot_ccld_qty="2"),
                row(odno="B2", tot_ccld_qty="5", avg_idx="351.25"),
            ]
        },
        lambda order_id: context(client_order_id=f"C-{order_id}"),
    )
    assert [report.client_order_id for report in reports] == ["C-B1", "C-B2"]
    assert [report.filled_quantity for report in reports] == [2, 5]

```
## Targeted verification
    - REAL/VTS TR-ID 분기.
    - 공식 inquire-ccnl request parameters 및 continuation keys.
    - 공식 order-level tot_ccld_qty cumulative snapshot을 delta fill로 변환.
    - 공식 avg_idx 평균지수/가격 field 보존.
    - 반복 동일 snapshot의 no-op 처리.
    - cumulative regression 및 과주문량 fail-closed.
    - REST-source-local snapshot identity와 H0IFCNI0 cross-source identity를 구분.

[Child Page] kis_futures_execution_recovery_transport.py
```python
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from infrastructure.kis.auth import KISAuthManager
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryQuery,
    KISExecutionRecoveryInvalid,
    KIS_FUTURES_EXECUTION_INQUIRY_PATH,
)


class KISExecutionRecoveryTransportError(RuntimeError):
    """Raised when the KIS execution recovery HTTP request cannot complete safely."""


@dataclass
class KISFuturesExecutionRecoveryTransport:
    """Authenticated GET transport for KIS inquire-ccnl recovery.

    The transport owns HTTP/authentication and official KIS continuation. Row
    normalization remains in KISFuturesExecutionRecoveryAdapter and settlement
    remains in Application.
    """

    auth: KISAuthManager
    timeout: float = 10.0
    urlopen: Callable[..., Any] = urllib.request.urlopen
    base_url: str | None = None
    max_pages: int = 100

    def authenticate(self) -> bool:
        return bool(self.auth.get_access_token())

    def inquire(self, query: KISExecutionRecoveryQuery) -> Mapping[str, object]:
        if self.max_pages <= 0:
            raise KISExecutionRecoveryInvalid("MAX_PAGES_INVALID")

        all_rows: list[object] = []
        current_query = query
        continuation = ""
        last_data: Mapping[str, object] | None = None

        for _page in range(self.max_pages):
            data, continuation = self._request(current_query, continuation)
            last_data = data
            rows = data.get("output1")
            if rows is not None:
                if not isinstance(rows, list):
                    raise KISExecutionRecoveryTransportError("KIS output1 must be an array")
                all_rows.extend(rows)

            if continuation != "M":
                break

            current_query = replace(
                current_query,
                ctx_area_fk200=str(data.get("ctx_area_fk200", "") or ""),
                ctx_area_nk200=str(data.get("ctx_area_nk200", "") or ""),
            )
        else:
            raise KISExecutionRecoveryTransportError("KIS execution recovery pagination limit exceeded")

        if last_data is None:
            raise KISExecutionRecoveryTransportError("KIS execution recovery returned no response")

        result = dict(last_data)
        result["output1"] = all_rows
        return result

    def _request(
        self,
        query: KISExecutionRecoveryQuery,
        tr_cont: str,
    ) -> tuple[Mapping[str, object], str]:
        base_url = (self.base_url or self.auth.base_url).rstrip("/")
        params = urllib.parse.urlencode(query.params())
        url = f"{base_url}{KIS_FUTURES_EXECUTION_INQUIRY_PATH}?{params}"
        headers = self.auth.get_auth_headers(tr_id=query.tr_id)
        if tr_cont:
            headers["tr_cont"] = tr_cont
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                response_tr_cont = str(response.headers.get("tr_cont", "")).strip().upper()
            data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery HTTP {exc.code}: {body}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery transport failed: {exc}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery response is not valid JSON: {exc}"
            ) from exc

        if not isinstance(data, Mapping):
            raise KISExecutionRecoveryTransportError("KIS execution recovery response must be object")
        if str(data.get("rt_cd", "")).strip() != "0":
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery rejected: {data.get('msg_cd')} {data.get('msg1')}"
            )
        return data, response_tr_cont
```
## Boundary
    - GET /uapi/domestic-futureoption/v1/trading/inquire-ccnl only.
    - Reuses KISAuthManager.get_auth_headers(tr_id=...) and adds official tr_cont only for continuation requests.
    - Query serialization includes official CTX_AREA_FK200 / CTX_AREA_NK200 continuation values.
    - Response pages are accumulated through the official tr_cont response header values M / F and body continuation keys.
    - Pagination has an explicit safety limit; it is not inferred from row count.
    - HTTP/auth failures are transport errors; no synthetic empty response is returned.

[Child Page] live_execution_recovery_service.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from contracts.types import ExecutionReport
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)


class RecoveryTransport(Protocol):
    def inquire(self, query: KISExecutionRecoveryQuery) -> dict[str, object]: ...


class ExecutionCorrelationProvider(Protocol):
    def resolve(self, broker_order_id: str): ...


@dataclass
class LiveExecutionRecoveryService:
    """Application-owned reconciliation entry for REST recovery reports."""

    transport: RecoveryTransport
    adapter: KISFuturesExecutionRecoveryAdapter
    correlation_provider: ExecutionCorrelationProvider
    on_report: Callable[[ExecutionReport], object]

    def recover(self, query: KISExecutionRecoveryQuery) -> tuple[object, ...]:
        response = self.transport.inquire(query)

        def context_for_order(broker_order_id: str) -> KISExecutionRecoveryContext:
            correlation = self.correlation_provider.resolve(broker_order_id)
            return KISExecutionRecoveryContext(
                client_order_id=correlation.client_order_id,
                order_quantity=correlation.order_quantity,
                prior_filled_quantity=correlation.prior_filled_quantity,
                prior_average_price=getattr(correlation, "prior_average_price", None),
            )

        reports = self.adapter.normalize(response, context_for_order)
        return tuple(self.on_report(report) for report in reports)
```
## Responsibility
    - REST recovery and H0IFCNI0 remain separate ingress sources.
    - Both paths converge only through the existing ExecutionReport -> dedup -> OMS -> Position settlement callback.
    - OMS correlation remains authoritative for client order identity and fill context.
    - Duplicate reports are not filtered here; the shared Live deduplicator remains the single exactly-once gate.