새 Runtime에 다음 항목을 직접 이식하지 않는다.

## 명확한 격리 후보

- .agents/AGENTS_ARCHIVE_*: 과거 Agent 지침

- Simple_Insert.py: 일회성 삽입 도구

- .bak_stage2 및 백업 계열

- 과거 구조를 전제로 하는 compatibility wrapper

- 임시 검증 runner

## 주의

'파일을 삭제한다'와 '기능을 폐기한다'는 다르다.

필요한 기능은 Reference Baseline Git History에서 기능 단위로 재구현한다.

## 중복 위험

- option_program/control HTML vs web_interface

- main.py orchestration vs program_runtime

- Broker interface와 VSSF Broker 구현

- 환경별 시간/시장 데이터 구현의 중복

최종 판정은 신규 Contract 하나당 구현체 책임 하나를 원칙으로 한다.

[Child Page] factory.py
구현 예정: Architecture와 Standard Contract 확정 후 실제 코드 작성.