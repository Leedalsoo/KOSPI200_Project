# KOSPI200 Project200

## 목적
KOSPI200 선물·옵션 자동매매 시스템을 구축한다. Standard Core를 중심으로 High-Speed, Virtual, Paper, Live 환경을 교체·검증한다.

## 현재 개발 기준
- 기본 검증 환경: Virtual Trading
- 실행 흐름: Market Tick → Strategy → Orchestrator → Risk → OMS/Router → Broker → ExecutionReport → Position/PnL → Control Tower
- Control Tower: 감독·운영 계층이며 정상 주문 생성의 주 경로가 아니다.
- Real KIS 주문: 현재 실행하지 않으며 외부 인증·실주문 검증은 BLOCKED로 관리한다.

## 저장소 구조
- `contracts/` 표준 계약·DTO·port
- `core/` 환경 독립 domain/strategy/risk/OMS
- `application/` orchestration/composition
- `environments/` 실행 환경 구현
- `infrastructure/` KIS/KRX 등 외부 source adapter
- `interfaces/` Control Tower/API/UI
- `tests/` 실행 가능한 현재 회귀·통합 검증

## 작업 기준
상세 작업 지침은 `AGENTS.md`를 따른다. Notion `질문과답변`은 작업 연속성 기록이다.

과거 단계별 Process 문서와 일회성 검증 파일은 저장소에서 유지하지 않는다.

Windows에서 Python 검증은 `py`를 사용한다.
