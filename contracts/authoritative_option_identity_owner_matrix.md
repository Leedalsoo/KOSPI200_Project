# Standard instrument_id authoritative owner 후보 대조표

## 목적

Standard OptionInstrumentIdentity.instrument_id의 실제 Production authoritative owner를 확정하기 위한 대조 경계다.

## 최소 공급 계약

- instrument_id

- symbol

- expiry

- option_type

- strike

## 후보 대조

<!-- Notion table block -->
| 후보 | 확인 가능한 값 | Standard instrument_id 공급 | 판정 |
| KIS Option Master (fo_idx_code_mts.mst) | shrn_iscd, stnd_iscd, 상품/행사가/월물/만기 정보 | 확인되지 않음 | 사용 불가 |
| KIS Market Data | symbol/shrn_iscd, 가격, expiry 등 | 확인되지 않음 | 사용 불가 |
| KIS Real Broker | SHTN_PDNO/broker symbol 경계 | Standard ID 공급원 아님 | 사용 불가 |
| Virtual/Replay fixture | 테스트용 authoritative ID | Production source 아님 | 사용 불가 |
| 외부 Product/Instrument Master | 실제 owner/record 미확보 | 미확인 | blocker 유지 |

## 금지

- KIS 식별자를 Standard instrument_id로 변환/승격하지 않는다.

- synthetic/composite ID를 생성하지 않는다.

- fixture ID를 Production ID로 사용하지 않는다.

- Runtime/OMS에서 ID를 추측하거나 생성하지 않는다.

## 승인 조건

실제 owner가 위 5개 값을 authoritative하게 공급하고 있음을 확인한 뒤에만 source-specific adapter를 구현한다. Adapter contract test PASS 전에는 Runtime 통합을 수행하지 않는다.

## 현재 판정

실제 Standard instrument_id owner는 미확정이다. Identity blocker를 유지한다.

## 추가 검증 결과 — KIS 공식 Master 원본 구조

KIS 공식 종목마스터정보(지수선물옵션).h에서 shrn_iscd는 단축코드, stnd_iscd는 표준코드이며 kor_name, atm_cls_code, acpr, mmsc_cls_code, 기초자산 코드/명 등이 별도 필드로 정의된다.

Reference Exp_Detail_1의 shared/contracts/option_master.py도 실제 fo_idx_code_mts.mst를 상품종류 | symbol(shrn_iscd) | standard_code(stnd_iscd) | name 구조로 파싱하고 있다.

이 증거는 KIS Master가 shrn_iscd와 stnd_iscd를 별도 KIS Master 필드로 제공한다는 것은 확정하지만, 이 중 어느 값도 Standard OptionInstrumentIdentity.instrument_id라는 별도 도메인 ID임을 증명하지 않는다.

따라서 KIS Master를 Standard instrument_id owner로 승격하지 않는다.