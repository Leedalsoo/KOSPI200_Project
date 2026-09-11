"""Control Tower Web Server — Lightweight HTTP server serving UI and API endpoints."""

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


class ControlTowerRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Control Tower 5-environment UI."""

    adapter = ControlTowerUIAdapter()
    web_dir = os.path.join(os.path.dirname(__file__), "web")

    def _send_json(self, data: dict, status: int = HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API routes
        if path == "/api/status":
            self._send_json(self.adapter.get_summary())
            return
        elif path.startswith("/api/environment/"):
            tab_id = path.replace("/api/environment/", "").strip("/")
            detail = self.adapter.get_tab_detail(tab_id)
            status_code = HTTPStatus.OK if "error" not in detail else HTTPStatus.NOT_FOUND
            self._send_json(detail, status_code)
            return

        # 2. Static file routes
        if path == "/" or path == "/index.html":
            file_path = os.path.join(self.web_dir, "index.html")
        else:
            rel_path = path.lstrip("/")
            file_path = os.path.join(self.web_dir, rel_path)

        if os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "application/octet-stream"
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}

        if path == "/api/active_tab":
            tab_id = payload.get("tab_id", "")
            self.adapter.set_active_tab(tab_id)
            self._send_json({"success": True, "active_tab": tab_id})
        elif path == "/api/command":
            cmd = payload.get("command", "")
            result = self.adapter.handle_command(cmd)
            status_code = HTTPStatus.OK if result.get("success", False) else HTTPStatus.BAD_REQUEST
            self._send_json(result, status_code)
        else:
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
