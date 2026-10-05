# KIS Futures Broker Command Adapter

## 목적
`environments/live/futures_broker_command_adapter.py`의 broker-symbol 주입 경계를 설명한다.

## 현재 책임
`KisFuturesBrokerCommandAdapter.to_broker_command()`은 다음을 검증한다.
- `asset_type`은 `FUTURES`여야 한다.
- `instrument_id`가 비어 있지 않아야 한다.
- `FuturesBrokerSymbolSource.current_symbol()`이 비어 있지 않아야 한다.
- broker symbol은 authoritative source에서 공급받아 `broker_symbol`에 주입한다.

Adapter는 symbol을 문자열 조합이나 기본값으로 추정하지 않으며, payload serialization이나 network I/O를 담당하지 않는다.

## 연결 경계
`FuturesBrokerSymbolSource` → `KisFuturesBrokerCommandAdapter` → 상위 Broker/transport 계층.

이 문서는 현재 구현 경계를 설명하며 실제 Live 주문 실행을 의미하지 않는다. 현재 프로젝트에서는 실제 KIS 주문을 실행하지 않는다.
