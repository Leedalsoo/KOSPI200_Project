"""Control Tower Web Server — local UI/API boundary.

Static assets and JSON API are served from the Control Tower web directory.
The server fails closed for unsupported commands and unsafe paths.
"""

import json
from dataclasses import asdict, is_dataclass
import mimetypes
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from application.bootstrap import create_virtual_runtime_bootstrap
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from interfaces.control_tower.view_models import TabEnvironmentId

_virtual_bootstrap = create_virtual_runtime_bootstrap()
next(_virtual_bootstrap.bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))

class ControlTowerRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Control Tower UI."""
    adapter = _virtual_bootstrap.ui_adapter
    web_dir = Path(__file__).resolve().parent / "web"

    def _send_json(self, data: dict, status: int = HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _safe_static_path(self, request_path: str) -> Path | None:
        relative = request_path.lstrip("/") or "index.html"
        candidate = (self.web_dir / relative).resolve()
        try:
            candidate.relative_to(self.web_dir)
        except ValueError:
            return None
        return candidate

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self._send_json(self.adapter.get_summary())
            return
        if path.startswith("/api/environment/"):
            tab_id = path.removeprefix("/api/environment/").strip("/")
            detail = self.adapter.get_tab_detail(tab_id)
            self._send_json(detail, HTTPStatus.OK if "error" not in detail else HTTPStatus.NOT_FOUND)
            return
        file_path = self._safe_static_path(path)
        if file_path is None or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        mime_type, _ = mimetypes.guess_type(str(file_path))
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"success": False, "error": {"code": "INVALID_CONTENT_LENGTH", "message": "Content-Length must be a valid integer."}}, HTTPStatus.BAD_REQUEST)
            return
        if length > 64 * 1024:
            self._send_json({"success": False, "error": {"code": "REQUEST_TOO_LARGE", "message": "Request body exceeds the 64 KiB limit."}}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"success": False, "error": {"code": "INVALID_JSON", "message": "Request body is not valid JSON."}}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/environment/virtual_broker/order":
            self._submit_virtual_order(payload)
            return
        if path == "/api/active_tab":
            tab_id = payload.get("tab_id", "")
            valid = tab_id in {tab.value for tab in TabEnvironmentId}
            if not valid:
                self._send_json({"success": False, "error": "UNKNOWN_TAB_ID"}, HTTPStatus.BAD_REQUEST)
                return
            self.adapter.set_active_tab(tab_id)
            self._send_json({"success": True, "active_tab": tab_id})
            return
        if path == "/api/command":
            result = self.adapter.handle_command(payload.get("command", ""))
            status_code = HTTPStatus.OK if result.get("success") else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(result, status_code)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def _submit_virtual_order(self, payload: dict) -> None:
        """Submit a contract-valid Virtual Broker order through the authoritative broker boundary."""
        if not isinstance(payload, dict):
            self._send_json({"success": False, "error": {"code": "INVALID_REQUEST", "message": "Request body must be a JSON object."}}, HTTPStatus.BAD_REQUEST)
            return
        allowed = {"side", "order_type", "quantity", "client_order_id"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            self._send_json({"success": False, "error": {"code": "UNKNOWN_FIELD", "message": f"Unknown field(s): {', '.join(unknown)}."}}, HTTPStatus.BAD_REQUEST)
            return
        required = {"side", "order_type", "quantity"}
        missing = sorted(required - payload.keys())
        if missing:
            self._send_json({"success": False, "error": {"code": "MISSING_REQUIRED_FIELD", "message": f"Missing required field(s): {', '.join(missing)}."}}, HTTPStatus.BAD_REQUEST)
            return
        side = str(payload["side"]).upper()
        order_type = str(payload["order_type"]).upper()
        quantity = payload["quantity"]
        if side != "BUY":
            self._send_json({"success": False, "error": {"code": "INVALID_SIDE", "message": "Only BUY is supported by the Virtual Broker order endpoint."}}, HTTPStatus.BAD_REQUEST)
            return
        if order_type != "LIMIT":
            self._send_json({"success": False, "error": {"code": "INVALID_ORDER_TYPE", "message": "Only LIMIT is supported by the Virtual Broker order endpoint."}}, HTTPStatus.BAD_REQUEST)
            return
        if quantity != 1 or isinstance(quantity, bool):
            self._send_json({"success": False, "error": {"code": "INVALID_QUANTITY", "message": "Virtual Broker order quantity must be exactly 1."}}, HTTPStatus.BAD_REQUEST)
            return
        if "client_order_id" in payload and (not isinstance(payload["client_order_id"], str) or not payload["client_order_id"].strip()):
            self._send_json({"success": False, "error": {"code": "INVALID_CLIENT_ORDER_ID", "message": "client_order_id must be a non-empty string when supplied."}}, HTTPStatus.BAD_REQUEST)
            return
        market = _virtual_bootstrap.bundle.market
        last_tick = getattr(market, "last_tick", None)
        if last_tick is None:
            self._send_json({"success": False, "error": "VIRTUAL_MARKET_TICK_REQUIRED"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        ask_price = getattr(last_tick, "ask_price", None)
        if ask_price is None:
            self._send_json({"success": False, "error": "VIRTUAL_MARKET_ASK_REQUIRED"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        client_order_id = str(payload.get("client_order_id", "HTTP-VIRTUAL-BUY-001"))
        identity = OptionInstrumentIdentity(
            instrument_id="KOSPI200", symbol="KOSPI200", expiry="202609",
            option_type="CALL", strike=Decimal("350"),
        )
        command = BrokerOrderCommand(
            client_order_id=client_order_id,
            instrument_id=identity.instrument_id,
            side=side, quantity=quantity, order_type=order_type,
            broker_symbol=identity.symbol, instrument_identity=identity,
            asset_type="OPTION", requested_price=Decimal(str(ask_price)),
            order_purpose="CONTROL_TOWER_VIRTUAL_TEST", track_id="CT-NO471",
            tag_id="CONTROL_TOWER",
        )
        try:
            report = _virtual_bootstrap.bundle.broker.submit(command)
        except Exception as exc:
            self._send_json({"success": False, "error": {"code": "VIRTUAL_ORDER_SUBMIT_FAILED", "message": "Virtual Broker order submission failed.", "detail": str(exc)}}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        execution_report = asdict(report) if is_dataclass(report) else report
        self._send_json({"success": True, "environment": "virtual", "execution_report": execution_report}, HTTPStatus.OK)


def run_server(port: int = 8080, host: str = "127.0.0.1"):
    server = HTTPServer((host, port), ControlTowerRequestHandler)
    print(f"Control Tower Server running at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
