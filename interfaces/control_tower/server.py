"""Control Tower Web Server — local UI/API boundary.

Static assets and JSON API are served from the Control Tower web directory.
The server fails closed for unsupported commands and unsafe paths.
"""

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter
from interfaces.control_tower.view_models import TabEnvironmentId


class ControlTowerRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Control Tower UI."""

    adapter = ControlTowerUIAdapter()
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
            self._send_json({"success": False, "error": "INVALID_CONTENT_LENGTH"}, HTTPStatus.BAD_REQUEST)
            return
        if length > 64 * 1024:
            self._send_json({"success": False, "error": "REQUEST_TOO_LARGE"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"success": False, "error": "INVALID_JSON"}, HTTPStatus.BAD_REQUEST)
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
