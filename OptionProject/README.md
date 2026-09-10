# 프로젝트 정의
## 최종 목표
하나의 Standard Option Core를 중심으로 High-Speed Test, Virtual Trading, Paper Trading, Live Trading 4개 실행환경을 선택·조립·실행할 수 있는 표준 옵션 트레이딩 플랫폼을 구축한다.
## 핵심 원칙
- Core는 실행환경을 알지 못한다.
- 환경 교체는 API 문자열 교체가 아니라 Environment Bundle 교체다.
- Exp_Detail_1은 Reference Baseline으로만 사용한다.
- 레거시를 통째로 복사하지 않고 검증된 기능만 새 구조에 맞춰 이식한다.
- Mock/Synthetic 성공은 실제 외부 시스템 검증 성공으로 표현하지 않는다.
## 실행 구조
```plain text
Control Tower UI → Runtime Controller → Environment Hub/Factory → Environment Bundle → Standard Contracts → Standard Option Core
```
이 Notion OptionProject는 Clean Build Source-of-Design이며 각 페이지는 실제 프로젝트의 폴더 또는 파일에 대응한다.
