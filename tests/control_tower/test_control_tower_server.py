"""Test Control Tower HTTP Server and Request Handler."""

import io
import json
from http import HTTPStatus
from unittest.mock import MagicMock

from interfaces.control_tower.server import ControlTowerRequestHandler


class _MockSocket:
    def __init__(self, data=b""):
        self._rfile = io.BytesIO(data)
        self._wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if "r" in mode:
            return self._rfile
        return self._wfile

    def sendall(self, data):
        self._wfile.write(data)


def test_control_tower_server_status_api():
    request_data = b"GET /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n"
    sock = _MockSocket(request_data)
    server = MagicMock()

    handler = ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    response_bytes = sock._wfile.getvalue()

    assert b"200 OK" in response_bytes
    assert b"high_speed" in response_bytes
    assert b"virtual_exchange" in response_bytes
    assert b"virtual_broker" in response_bytes
    assert b"paper" in response_bytes
    assert b"live" in response_bytes


def test_control_tower_server_tab_detail_api():
    request_data = b"GET /api/environment/high_speed HTTP/1.1\r\nHost: localhost\r\n\r\n"
    sock = _MockSocket(request_data)
    server = MagicMock()

    handler = ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    response_bytes = sock._wfile.getvalue()

    assert b"200 OK" in response_bytes
    assert b"High-Speed Test" in response_bytes


def test_control_tower_server_serves_index_html():
    request_data = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    sock = _MockSocket(request_data)
    server = MagicMock()

    handler = ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    response_bytes = sock._wfile.getvalue()

    assert b"200 OK" in response_bytes
    assert b"text/html" in response_bytes
    assert b"Project200 Control Tower" in response_bytes


def test_control_tower_server_panic_halt_command_api():
    body = json.dumps({"command": "PANIC_HALT"}).encode("utf-8")
    request_data = (
        b"POST /api/command HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
    )
    sock = _MockSocket(request_data)
    server = MagicMock()

    handler = ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    response_bytes = sock._wfile.getvalue()

    assert b"503 Service Unavailable" in response_bytes
    assert b"PANIC_HALT" in response_bytes
    assert b"success" in response_bytes


def test_control_tower_server_rejects_path_traversal():
    request_data = b"GET /..%2F..%2FAGENTS.md HTTP/1.1\r\nHost: localhost\r\n\r\n"
    sock = _MockSocket(request_data)
    server = MagicMock()
    ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    response_bytes = sock._wfile.getvalue()
    assert b"404" in response_bytes


def test_control_tower_server_rejects_invalid_active_tab():
    body = json.dumps({"tab_id": "invalid"}).encode("utf-8")
    request_data = (b"POST /api/active_tab HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    sock = _MockSocket(request_data)
    server = MagicMock()
    ControlTowerRequestHandler(sock, ("127.0.0.1", 12345), server)
    assert b"400 Bad Request" in sock._wfile.getvalue()
