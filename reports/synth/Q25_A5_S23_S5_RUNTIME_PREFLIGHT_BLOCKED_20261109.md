기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 적용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-08, CB2-09

# Q25 A5 S23 — Strategy 5 natural-signal Runtime E2E 사전검증

## 1. 결과

- 판정: BLOCKED_INPUT
- S23 자연 신호 Runtime E2E, FAST/DETAILED 동등성, Position/PnL 대사 및 최종 Runtime verdict는 실행하지 않았다.
- 차단 원인은 Strategy 5의 기존 Option 포지션을 구성할 authoritative KIS multiplier 및 execution-backed open-lot provenance가 현재 검증 입력에서 확인되지 않은 것이다.

## 2. 기준 및 실행 범위

- Current Baseline v2 SHA-256: E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D (로컬 파일과 Notion SSOT 일치).
- A6 C01–C10 완료: No.1476 확인. 사용자의 직접 승인에 따라 A5 S23 사전검증을 재개했다.
- S22 기반 격리 worktree: Q25_A5_S22_S5_GROUP_CLOSE_20261109
- 작업 브랜치: q25-a5-s22-s5-group-close-20261109
- 사전검증 HEAD: 7afc49994097f7e06d35b7797105f2e08539291a
- 원격 cleanup/p2-quarantine-20261026 HEAD: f30fd3e0aa84751971538c5b5e59f08becfbb590
- AGENTS.md를 먼저 읽고 Current Baseline v2, No.1474, No.1475, No.1477을 대조했다.

## 3. 차단 근거

1. No.1474에서 KIS Option Master의 유효 anchor는 CALL B01611885/B01611887로 확인됐으나, KIS Master multiplier는 확인되지 않아 None으로 유지했다.
2. Current Baseline v2 CB2-05/CB2-06은 KIS-only authoritative runtime data를 요구하며 KIS multiplier 누락을 KRX 값 또는 상수로 대체하지 못하도록 한다.
3. VirtualPositionLotStore가 보존하는 PositionLotProvenance는 양수 contract_multiplier 및 instrument identity와의 일치를 요구한다. multiplier가 없는 Option lot은 authoritative open-position fixture로 검증할 수 없다.
4. No.1132/1134의 grouped terminal close는 실제 open Futures+Option lot 전체에서 side/quantity/identity를 도출해야 한다. Option lot provenance가 불완전한 상태에서 임의 multiplier·synthetic execution을 만들어 E2E를 진행하면 기준 위반이다.
5. No.1475의 S21 catalog SHA-256은 기록되어 있으나, catalog 산출물은 이번 S22 격리 worktree와 원본 작업폴더의 지정 reports/synth·verification 경로에서 찾지 못했다. 단, 이것은 보조 확인 사항이며 주 차단 원인은 multiplier/provenance 부재다.

## 4. 실행 및 변경 여부

- Runtime / Replay / FAST / DETAILED: NOT RUN (입력 gate에서 중단).
- S23 전용 pytest / 전체 pytest: NOT RUN.
- 소스·테스트·manifest·원본 데이터·운영 설정 변경: 없음.
- KIS API / REAL_VTS / Live / 실계좌 / 주문·정정·취소·잔고·증거금 API: 호출 없음.
- 원본 작업폴더의 dirty/untracked 항목 및 A6 worktree 미커밋 문서: 변경 없음.
- S22 구현·보고서 커밋은 로컬에 유지. 이번 S23 사전검증 결과로 push하지 않았다.

## 5. 재개 조건

- S5 대상 Standard Option의 KIS authoritative multiplier 증거.
- 해당 계약의 exact identity/expiry와 연결된 execution-backed existing open-lot provenance (run/group/leg/order/execution/side/remaining quantity 포함).
- 위 근거를 결합한 validation-only manifest/dataset 및 SHA-256.
- 조건 충족 후 S23에서 자연 terminal signal → Decision → Risk → grouped OMS/Router → Virtual Execution → authoritative flat/Position/PnL, 동일 입력 hash 기반 FAST/DETAILED parity를 재검증한다.

S5 신규 진입·hedge·re-entry 정책은 계속 BLOCKED. 본 결과는 Production/Live 실행 허가가 아니다.
