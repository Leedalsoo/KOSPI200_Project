from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from infrastructure.kis.auth import KISAuthError, KISAuthManager
from environments.live.broker.kis_order_payload import KisDomesticFuturesOrderPayloadAdapter


KIS_FUTURES_ORDER_PATH = "/uapi/domestic-futureoption/v1/trading/order"


class KisOrderTransportError(RuntimeError):
    """Raised for transport-level failures that cannot be represented as an ACK."""


@dataclass
class KISDomesticFuturesOrderTransport:
    """HTTP transport for the KIS domestic futures/options new-order boundary.

    The transport owns HTTP/authentication and delegates body serialization to the
    existing KIS payload adapter. It never converts an ACK into an ExecutionReport.
    """

    auth: KISAuthManager
    payload_adapter: KisDomesticFuturesOrderPayloadAdapter
    timeout: float = 10.0
    urlopen: Callable[..., Any] = urllib.request.urlopen
    base_url: str | None = None

    def authenticate(self) -> bool:
        try:
            pass
            return bool(self.auth.get_access_token())
        except KISAuthError:
            pass
            return False

    def submit(self, command: BrokerOrderCommand) -> BrokerOrderResponse:
        payload = self.payload_adapter.to_payload(command)
        tr_id = self.payload_adapter.tr_id()
        base_url = (self.base_url or self.auth.base_url).rstrip("/")
        url = f"{base_url}{KIS_FUTURES_ORDER_PATH}"
        headers = self.auth.get_auth_headers(tr_id=tr_id)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            pass
            with self.urlopen(request, timeout=self.timeout) as response:
                pass
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            pass
            body = exc.read().decode("utf-8", errors="replace")
            return BrokerOrderResponse(
                client_order_id=command.client_order_id,
                accepted=False,
                broker_code=str(exc.code),
                message=body,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            pass
            raise KisOrderTransportError(f"KIS order transport failed: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            pass
            raise KisOrderTransportError(f"KIS order response is not valid JSON: {exc}") from exc

        return self.normalize_response(command.client_order_id, data)

    @staticmethod
    def normalize_response(
        client_order_id: str,
        data: Mapping[str, Any],
    ) -> BrokerOrderResponse:
        rt_cd = str(data.get("rt_cd", ""))
        output = data.get("output")
        output_map = output if isinstance(output, Mapping) else {}
        broker_order_id = output_map.get("ODNO")
        message = data.get("msg1") or data.get("msg_cd")
        accepted = rt_cd == "0" and bool(str(broker_order_id or "").strip())
        return BrokerOrderResponse(
            client_order_id=client_order_id,
            accepted=accepted,
            broker_order_id=str(broker_order_id) if broker_order_id else None,
            broker_code=str(data.get("msg_cd")) if data.get("msg_cd") else rt_cd or None,
            message=str(message) if message else None,
            raw_response=dict(data),
        )
