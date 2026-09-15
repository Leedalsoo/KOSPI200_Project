# PROJECT STATUS

## 현재 기준
- Local branch: `master`
- Remote release branch: `Project200`
- Current checkpoint before this cleanup: `0f8b9d8`
- Primary environment: Virtual Trading
- Real KIS order execution: BLOCKED / not run

## 검증된 기반
- 9개 Strategy Registry 및 Orchestrator 연결
- Virtual Runtime tick → strategy → Risk/OMS → Virtual Broker → ExecutionReport 폐쇄루프
- Multi-leg 2-leg/4-leg 주문 구조 및 Virtual 체결 경로
- Control Tower의 Runtime/Execution/Position 상태 projection 기반
- 전체 pytest 기준선: 478 passed (cleanup 전)

## 이번 정리 범위
- `Process/` 전체 제거
- `.pytest_cache/` 제거
- migration 단계 문서 및 테스트 설명용 markdown 제거
- 일회성 verification runner 제거
- 폐기 Legacy UI 및 실행 로그/생성 검증 JSON 제거
- 중복/구식 root 문서 제거
- `AGENTS.md`를 현재 자동매매 방향과 Virtual 우선 검증 원칙에 맞게 갱신

## 다음 검증 대상
1. 9개 Strategy Runtime Input authoritative source
2. Multi-leg option identity / quote / contract multiplier
3. Grouped Position/PnL authoritative projection
4. strategy → group → leg → client order → execution provenance
5. Control Tower DTO 및 HTTP 경계

## 원칙
검증 결과는 실제 실행 증거 기준으로 `PASS / FAIL / BLOCKED`를 구분한다. 추정값이나 fixture를 실제 source처럼 사용하지 않는다.
