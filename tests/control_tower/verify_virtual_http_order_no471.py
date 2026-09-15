"""End-to-end verification: HTTP client -> separate Control Tower server process."""

import json
import subprocess
import sys
import time
from http.client import HTTPConnection


def request_json(method, path, body=None):
    connection = HTTPConnection("127.0.0.1", 18084, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    raw = response.read()
    return response.status, json.loads(raw)


if __name__ == "__main__":
    process = subprocess.Popen([
        sys.executable, "-c",
        "from interfaces.control_tower.server import run_server; run_server(18084, '127.0.0.1')",
    ])
    try:
        for _ in range(30):
            try:
                status, _ = request_json("GET", "/api/environment/virtual_broker")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        body = json.dumps({"client_order_id":"HTTP-NO471-BUY-001","side":"BUY","order_type":"LIMIT","quantity":1})
        post_status, post = request_json("POST", "/api/environment/virtual_broker/order", body)
        get_status, dto = request_json("GET", "/api/environment/virtual_broker")
        report = post["execution_report"]
        result = {
            "post_http_status": post_status,
            "post_success": post["success"],
            "report_filled": report.get("status") == "FILLED" and report.get("filled_quantity") == 1,
            "execution_id_present": report.get("execution_id") == "EXEC-000001",
            "get_http_status": get_status,
            "margin_used": dto["margin_used"],
            "margin_available": dto["margin_available"],
            "recent_executions": len(dto["recent_executions"]),
            "positions": len(dto["positions"]),
            "position_qty": dto["positions"][0]["qty"],
            "position_avg": dto["positions"][0]["avg_price"],
            "position_current": dto["positions"][0]["current_price"],
            "position_pnl": dto["positions"][0]["pnl"],
            "same_server_runtime": dto["recent_executions"][0]["client_order_id"] == "HTTP-NO471-BUY-001",
        }
        print(json.dumps(result, ensure_ascii=False, default=str))
        assert result["post_http_status"] == 200
        assert result["post_success"] is True
        assert result["report_filled"] is True
        assert result["execution_id_present"] is True
        assert result["get_http_status"] == 200
        assert result["same_server_runtime"] is True
        assert result["recent_executions"] == 1
        assert result["positions"] == 1
        assert result["position_qty"] == 1
    finally:
        process.terminate()
        process.wait(timeout=5)
