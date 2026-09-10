## 신규 분류

- unit: Standard Core 단위

- contract: Contracts와 구현체 호환성

- integration: Environment Bundle 조립

- replay: Virtual/High-Speed 재현성

- regression: Reference Baseline 기능 비교

- safety: Paper/Live 주문 안전·복구·Kill Switch

## 기존 테스트 처리

기존 import 경로를 유지하기 위해 테스트를 이식하지 않는다.

테스트의 검증 의도를 추출해 신규 Architecture 기준으로 재작성한다.

## 현재 상태

실제 실행 환경 검증은 BLOCKED일 수 있으므로:

- STATIC 구조 검증

- 의존성 규칙 검토

- Contract completeness

까지 우선 확정한다.

실행 가능한 환경이 확보되면 runtime evidence를 별도 추가한다.