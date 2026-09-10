"""Test Kis Order Payload — 테스트 사양 문서.

from decimal import Decimal
import pytest
from contracts.types import BrokerOrderCommand
from environments.live.kis_order_payload import (
KisDomesticFuturesOrderPayloadAdapter,
KisOrderAccountContext,
KisOrderPayloadError,
)
def command(**changes):
values = {
"client_order_id": "ORD-1",
"instrument_id": "FUT-1",
"side": "BUY",
"quantity": 2,
"order_type": "LIMIT",
"broker_symbol": "101V3000",
"asset_type": "FUTURES",
"requested_price": Decimal("350.10"),
}
values.update(changes)
return BrokerOrderCommand(**values)
def adapter(is_vts=False):
return KisDomesticFuturesOrderPayloadAdapter(
account=KisOrderAccountContext(cano="12345678", acnt_prdt_cd="01"),
is_vts=is_vts,
)
def test_real_buy_limit_payload_is_lossless_at_execution_fields():
payload_adapter = adapter()
assert payload_adapter.to_payload(command()) == {
"CANO": "12345678",
"ACNT_PRDT_CD": "01",
"SHTN_PDNO": "101V3000",
"ORD_PRCS_DVSN_CD": "02",
"SLL_BUY_DVSN_CD": "02",
"ORD_DVSN_CD": "00",
"UNIT_PRICE": "350.10",
"ORD_QTY": "2",
"NMPR_TYPE_CD": "01",
"KRX_NMPR_CNDT_CD": "0",
}
assert payload_adapter.tr_id() == "TTTO1101U"
def test_sell_maps_side_only_and_keeps_same_order_tr_id():
payload_adapter = adapter()
payload = payload_adapter.to_payload(command(side="SELL"))
assert payload["SLL_BUY_DVSN_CD"] == "01"
assert payload_adapter.tr_id() == "TTTO1101U"
def test_vts_uses_vtto1101u():
assert adapter(is_vts=True).tr_id() == "VTTO1101U"
def test_invalid_or_missing_broker_symbol_fails_closed():
with pytest.raises(KisOrderPayloadError, match="SHTN_PDNO_REQUIRED"):
pass
adapter().to_payload(command(broker_symbol=None))
with pytest.raises(KisOrderPayloadError, match="FUTURES_SHTN_PDNO_PRODUCT_PREFIX_REQUIRED"):
pass
adapter().to_payload(command(broker_symbol="KOSPI200"))
def test_quantity_and_price_are_required():
with pytest.raises(KisOrderPayloadError, match="ORD_QTY_REQUIRED"):
pass
adapter().to_payload(command(quantity=0))
with pytest.raises(KisOrderPayloadError, match="UNIT_PRICE_REQUIRED"):
pass
adapter().to_payload(command(requested_price=None))
def test_unsupported_market_order_is_not_guessed():
with pytest.raises(KisOrderPayloadError, match="UNSUPPORTED_ORDER_TYPE"):
pass
adapter().to_payload(command(order_type="MARKET"))
"""
