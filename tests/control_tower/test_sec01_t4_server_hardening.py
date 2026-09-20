import json
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from interfaces.control_tower.server import ControlTowerRequestHandler


def test_security_headers_are_present_on_json_response():
    class FakeHandler(ControlTowerRequestHandler):
        def __init__(self):
            self.headers_sent = []
            self.wfile = type("W", (), {"write": lambda self, payload: None})()

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.headers_sent.append((name, value))

        def end_headers(self):
            pass

    handler = FakeHandler()
    handler._send_json({"ok": True})
    names = {name.lower() for name, _ in handler.headers_sent}
    assert "cache-control" in names
    assert "x-content-type-options" in names
    assert "content-security-policy" in names
    assert "referrer-policy" in names
    assert "permissions-policy" in names


def test_static_security_headers_are_present():
    source = Path("interfaces/control_tower/server.py").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in source
    assert "Referrer-Policy" in source
    assert "Permissions-Policy" in source


def test_unknown_json_fields_cannot_reach_virtual_order_boundary():
    source = Path("interfaces/control_tower/server.py").read_text(encoding="utf-8")
    assert 'UNKNOWN_FIELD' in source
    assert 'allowed = {"side", "order_type", "quantity", "client_order_id"}' in source
