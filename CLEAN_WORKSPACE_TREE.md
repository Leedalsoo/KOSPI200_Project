# CLEAN WORKSPACE TREE — Project200

## 목적

현재 `Project200` 실행 구조만 설명한다. 과거 migration/phase 문서는 Notion 작업기록으로 보존하며 저장소의 현재 실행 기준 문서와 섞지 않는다.

## 현재 구조

```text
application/
contracts/
core/
environments/
infrastructure/
interfaces/control_tower/
shared/                 # legacy compatibility가 실제 필요할 때만 사용
support/
tests/
verification/
AGENTS.md
README.md
PROJECT_STATUS.md
ARCHITECTURE.md
STANDARD_CONTRACTS_SPEC.md
CANONICAL_DTO_SPEC.md
ENVIRONMENT_BUNDLE_BOUNDARY.md
RUNTIME_UI_BOUNDARY.md
```

## 문서 원칙

- 현재 실행 계약과 아키텍처에 필요한 문서만 저장소에 둔다.
- 완료된 migration/phase 기록은 저장소에서 반복 보존하지 않고 Notion `질문과답변`을 연속성 기준으로 사용한다.
- `*_children`, `[LEGACY_MISPLACED]`, zero-collection 테스트 파일, 빈 placeholder 문서는 저장하지 않는다.
- 테스트 파일은 실제 pytest 수집/실행 경로에 있는 것만 유지한다.
- `.pytest_cache/`와 `__pycache__/`는 생성물이며 Git에 포함하지 않는다.

## 현재 실행 단계

Control Tower UI 단계까지 실제 실행 검증을 완료했다. 다음 활성 단계는 실제 장기 모의투자 관찰 근거를 바탕으로 한 서킷브레이커/예외처리 정밀화다.
