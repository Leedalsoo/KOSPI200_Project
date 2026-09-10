Reference Baseline → Asset Audit → Classification → Clean Implementation → Contract Test → Integration

## 분류

KEEP / REFACTOR / REBUILD / MERGE / DELETE

## 절대 규칙

- 구 코드의 import 구조를 그대로 가져오지 않는다.

- compatibility shim을 기본값으로 만들지 않는다.

- 실제 API 구현체는 infrastructure/environments에만 둔다.

- 전략은 Framework Contract만 본다.

- 검증 불가능한 외부 연결은 BLOCKED로 유지한다.