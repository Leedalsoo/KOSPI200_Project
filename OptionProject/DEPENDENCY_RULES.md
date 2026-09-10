# 의존성 규칙
## 허용
interfaces → application → contracts → core
## 금지
- core → KIS API
- core → KRX API
- core → Virtual Broker
- core → UI
- strategy → 특정 Broker
- UI → Broker 직접 호출
- UI → Environment 내부 구현 직접 호출
- Paper → Virtual Broker 의존
- Live → Paper Mock 의존
Core는 Contract에 정의된 표준 데이터만 입력받고, 외부 구현체가 Contract를 구현한다.
