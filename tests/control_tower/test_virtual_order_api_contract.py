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

# Consolidated from tests\control_tower\test_virtual_http_order_path.py; retained because it covers the same production boundary.

"""Integration verification for the authoritative Virtual HTTP order path."""

import importlib
import json
import threading
from http.client import HTTPConnection

from interfaces.control_tower import server as server_module


def test_http_virtual_buy_updates_same_server_runtime():
    server = importlib.reload(server_module)
    http_server = server.HTTPServer(("127.0.0.1", 0), server.ControlTowerRequestHandler)
    port = http_server.server_address[1]
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"client_order_id":"HTTP-NO471-BUY-001","side":"BUY","order_type":"LIMIT","quantity":1})
        connection.request("POST", "/api/environment/virtual_broker/order", body, {"Content-Type":"application/json"})
        response = connection.getresponse()
        post = json.loads(response.read())
        assert response.status == 200
        assert post["success"] is True
        report = post["execution_report"]
        assert isinstance(report, dict)
        assert report["status"] == "FILLED"
        assert report["filled_quantity"] == 1
        assert report["execution_id"] == "EXEC-000001"
        assert report["source_freshness"]["reason"] == "vssf_authoritative_execution"

        connection.request("GET", "/api/environment/virtual_broker")
        response = connection.getresponse()
        dto = json.loads(response.read())
        assert response.status == 200
        assert dto["margin_used"] == 87536900.0
        assert dto["margin_available"] == 162463100.0
        assert len(dto["recent_executions"]) == 1
        assert len(dto["positions"]) == 1
        assert dto["positions"][0]["qty"] == 1
        assert dto["positions"][0]["avg_price"] == 350.1476
        assert dto["positions"][0]["current_price"] == 350.0976
        assert dto["positions"][0]["pnl"] == -12500.000000002841
    finally:
        http_server.shutdown()
        http_server.server_close()
        thread.join(timeout=5)
