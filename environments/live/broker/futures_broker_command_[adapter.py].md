```python
from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from contracts.types import BrokerOrderCommand


class FuturesBrokerSymbolSource(Protocol):
    def current_symbol(self) -> str: ...


class KisFuturesBrokerCommandAdapter:
    """Attach the authoritative KIS FUTURES broker symbol to a broker command."""

    def __init__(self, symbol_source: FuturesBrokerSymbolSource) -> None:
        self._symbol_source = symbol_source

    def to_broker_command(self, command: BrokerOrderCommand) -> BrokerOrderCommand:
        if command.asset_type != "FUTURES":
            raise ValueError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.instrument_id.strip():
            raise ValueError("FUTURES_INSTRUMENT_ID_REQUIRED")

        symbol = self._symbol_source.current_symbol().strip()
        if not symbol:
            raise ValueError("FUTURES_BROKER_SYMBOL_REQUIRED")

        return replace(command, broker_symbol=symbol)
```

## 책임 경계

- Standard instrument_id는 변경하지 않는다.

- KIS shrn_iscd 기반의 authoritative execution symbol만 broker_symbol에 주입한다.

- symbol을 조합하거나 기본값으로 생성하지 않는다.

- 주문 payload 직렬화와 network I/O는 담당하지 않는다.

- FUTURES 이외 asset type은 이 Adapter의 책임이 아니므로 fail-closed 한다.

## 연결 경로

KIS FUTURES Master → KisFuturesExecutionSymbolSource.current_symbol() → KisFuturesBrokerCommandAdapter.to_broker_command() → LiveBrokerAdapter → KisDomesticFuturesOrderPayloadAdapter → KISDomesticFuturesOrderTransport

instrument_id와 broker_symbol은 서로 다른 identity seam으로 유지한다.