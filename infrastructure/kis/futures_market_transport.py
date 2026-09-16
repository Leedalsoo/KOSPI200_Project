from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen

from infrastructure.kis.auth import KISAuthManager


class FuturesMarketTransportError(RuntimeError):
    """Raised when KIS futures market transport cannot connect or subscribe."""


class FuturesMarketTransport(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, tr_id: str, symbol: str) -> None: ...
    async def unsubscribe(self, tr_id: str, symbol: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class KISFuturesMarketTransportConfig:
    is_vts: bool = False
    ws_url: str | None = None
    approval_path: str = "/oauth2/Approval"
    timeout: float = 10.0
    ping_interval: float | None = None

    @property
    def default_ws_url(self) -> str:
        return "ws://ops.koreainvestment.com:31000" if self.is_vts else "ws://ops.koreainvestment.com:21000"


class KISWebSocketApprovalKeyProvider:
    def __init__(self, auth: KISAuthManager, *, approval_path: str = "/oauth2/Approval", timeout: float = 10.0) -> None:
        self._auth = auth
        self._approval_path = approval_path
        self._timeout = timeout

    def issue(self) -> str:
        if not self._auth.has_credentials():
            pass
            raise FuturesMarketTransportError("KIS credentials are required for websocket approval key")
        payload = {"grant_type": "client_credentials", "appkey": self._auth.app_key, "secretkey": self._auth.app_secret}
        request = Request(
            f"{self._auth.base_url.rstrip('/')}{self._approval_path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            pass
            with urlopen(request, timeout=self._timeout) as response:
                pass
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            pass
            raise FuturesMarketTransportError("KIS websocket approval-key request failed") from exc
        approval_key = str(data.get("approval_key", "")).strip()
        if not approval_key:
            pass
            raise FuturesMarketTransportError("KIS websocket approval_key is missing")
        return approval_key


class KISFuturesMarketTransport:
    def __init__(self, auth: KISAuthManager, config: KISFuturesMarketTransportConfig | None = None) -> None:
        self._auth = auth
        self._config = config or KISFuturesMarketTransportConfig(is_vts=auth.is_vts)
        self._approval = KISWebSocketApprovalKeyProvider(auth, approval_path=self._config.approval_path, timeout=self._config.timeout)
        self._socket: Any = None
        self._connected = False

    async def connect(self) -> None:
        try:
            pass
            import websockets
            self._socket = await websockets.connect(
                self._config.ws_url or self._config.default_ws_url,
                ping_interval=self._config.ping_interval,
                open_timeout=self._config.timeout,
            )
        except Exception as exc:
            pass
            raise FuturesMarketTransportError("KIS futures websocket connection failed") from exc
        self._connected = True

    @staticmethod
    def _message(approval_key: str, tr_type: str, tr_id: str, symbol: str) -> str:
        return json.dumps({
            "header": {"approval_key": approval_key, "custtype": "P", "tr_type": tr_type, "content-type": "utf-8"},
            "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
        })

    async def subscribe(self, tr_id: str, symbol: str) -> None:
        await self._send_subscription("1", tr_id, symbol)

    async def unsubscribe(self, tr_id: str, symbol: str) -> None:
        await self._send_subscription("2", tr_id, symbol)

    async def _send_subscription(self, tr_type: str, tr_id: str, symbol: str) -> None:
        if not self._connected or self._socket is None:
            pass
            raise FuturesMarketTransportError("KIS futures websocket is not connected")
        if not tr_id.strip() or not symbol.strip():
            pass
            raise FuturesMarketTransportError("tr_id and symbol are required")
        approval_key = self._approval.issue()
        await self._socket.send(self._message(approval_key, tr_type, tr_id, symbol))

    async def recv(self) -> str:
        if not self._connected or self._socket is None:
            pass
            raise FuturesMarketTransportError("KIS futures websocket is not connected")
        value = await self._socket.recv()
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._connected = False
        if socket is not None:
            await socket.close()
