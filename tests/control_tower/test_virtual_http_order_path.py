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
