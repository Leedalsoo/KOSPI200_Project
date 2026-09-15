"""Contract tests for the Control Tower Virtual Broker order API."""

import importlib
import json
import threading
from http.client import HTTPConnection

import pytest

from interfaces.control_tower import server as server_module


@pytest.fixture
def api_server():
    server = importlib.reload(server_module)
    http_server = server.HTTPServer(("127.0.0.1", 0), server.ControlTowerRequestHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, http_server.server_address[1]
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=5)


def request(port, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body, headers)
    response = conn.getresponse()
    raw = response.read()
    return response.status, json.loads(raw)


def test_buy_limit_qty_one_matches_contract(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "BUY", "order_type": "LIMIT", "quantity": 1,
        "client_order_id": "CT-CONTRACT-001",
    }))
    report = body["execution_report"]
    assert status == 200
    assert body["success"] is True
    assert body["environment"] == "virtual"
    assert report["status"] == "FILLED"
    assert report["filled_quantity"] == 1
    assert report["client_order_id"] == "CT-CONTRACT-001"
    assert report["execution_id"] == "EXEC-000001"
    assert report["execution_price"] == 350.1476


def test_invalid_quantity_returns_reject_dto(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "BUY", "order_type": "LIMIT", "quantity": 2,
    }))
    assert status == 400
    assert body == {"success": False, "error": {
        "code": "INVALID_QUANTITY",
        "message": "Virtual Broker order quantity must be exactly 1.",
    }}


def test_invalid_side_returns_reject_dto(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "SELL", "order_type": "LIMIT", "quantity": 1,
    }))
    assert status == 400
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_SIDE"
    assert "BUY" in body["error"]["message"]


def test_invalid_order_type_returns_reject_dto(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "BUY", "order_type": "MARKET", "quantity": 1,
    }))
    assert status == 400
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_ORDER_TYPE"
    assert "LIMIT" in body["error"]["message"]


def test_missing_required_field_returns_400_dto(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "BUY", "order_type": "LIMIT",
    }))
    assert status == 400
    assert body["success"] is False
    assert body["error"]["code"] == "MISSING_REQUIRED_FIELD"
    assert "quantity" in body["error"]["message"]


def test_invalid_json_returns_400_dto(api_server):
    _, port = api_server
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", '{"side":"BUY",')
    assert status == 400
    assert body == {"success": False, "error": {"code": "INVALID_JSON", "message": "Request body is not valid JSON."}}


def test_runtime_error_returns_error_dto(api_server):
    server, port = api_server
    def fail_submit(_command):
        raise RuntimeError("synthetic broker failure")
    server._virtual_bootstrap.bundle.broker.submit = fail_submit
    status, body = request(port, "POST", "/api/environment/virtual_broker/order", json.dumps({
        "side": "BUY", "order_type": "LIMIT", "quantity": 1,
    }))
    assert status == 503
    assert body["success"] is False
    assert body["error"]["code"] == "VIRTUAL_ORDER_SUBMIT_FAILED"
    assert body["error"]["message"] == "Virtual Broker order submission failed."
