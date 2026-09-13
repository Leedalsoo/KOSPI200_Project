# KOSPI200 Project200

## 프로젝트 정의

KOSPI200 옵션/선물을 대상으로 하나의 Standard Option Core를 중심으로 High-Speed Test, Virtual Trading, Paper Trading, Live Trading 환경을 선택·조립·검증하는 자동매매 플랫폼이다.

## 현재 기준점

- 작업 기준: `AGENTS.md`
- 작업 연속성: Notion `질문과답변`
- 현재 완료 단계: Control Tower UI 및 Runtime 경계 실제 검증 완료
- 다음 계획 단계: 서킷브레이커/예외처리 정밀화
- 기준 commit: `a82367c7b323d52ca022785520a9ea9562dfe26a`

## 핵심 원칙

- Core는 실행환경을 알지 못한다.
- 환경 교체는 Environment Bundle 교체다.
- Mock/Synthetic 성공은 실제 외부 시스템 검증 성공으로 표현하지 않는다.
- Legacy 경로는 실제 사용 증거 없이 신규 실행 경로로 복구하지 않는다.
- 실제 외부 KIS 검증이 필요한 항목은 인증/연결 조건을 충족하기 전까지 BLOCKED로 관리한다.

## 실행 구조

```text
Control Tower UI → Runtime Controller → Environment Hub/Factory → Environment Bundle → Standard Contracts → Standard Option Core
```

## 검증

Windows 작업폴더에서 Python 실행은 `py`를 사용한다. 최종 변경은 실제 테스트 PASS 후 Git `Project200`에 반영하고 원격 HEAD를 재검증한다.
