## 목적

Reference Exp_Detail_1/option_program/broker/kis_auth.py의 OAuth2 인증 기능을 OptionProject의 Infrastructure 경계로 선별 이식하기 위한 구현 기준이다.

## 확정 책임

- KISAuthManager: OAuth2 access token 발급·캐시·만료 관리·인증 헤더 생성

- KISAuthToken: token DTO 및 유효성 판정

- KISAuthError: 인증 실패 의미 보존

- Holiday Provider는 OAuth 구현을 직접 보유하지 않고 인증 Adapter를 통해 헤더만 공급받는다.

## 이식 위치

OptionProject/infrastructure/kis/auth.py

## Reference 보존 원칙

- KIS endpoint와 token semantics는 Reference를 기준으로 유지한다.

- 기존 기능을 임의 단순화하지 않는다.

- orjson은 OptionProject dependency 기준이 확정되지 않았으므로 표준 json 사용 가능 여부를 구현 단계에서 검증한다.

- Core는 infrastructure.kis를 import하지 않는다.

## 구현 전제

DEPENDENCY_RULES.md의 infrastructure → contracts 방향과 Core의 외부 API 비의존 원칙을 유지한다.

## 구현 대상 최소 API

- from_env(...)

- has_credentials()

- issue_token()

- get_access_token(...)

- get_auth_headers(tr_id=..., ...)

## 후속 연결

infrastructure/kis/holiday_provider.py는 이 Adapter의 인증 헤더 공급 경계를 사용하며, Production Calendar Factory는 Application composition에서 Provider를 조립한다.

## No.162 실제 구현 반영

- 실제 코드 페이지: auth.py

- 최소 단위 테스트 페이지: test_kis_auth.py

- 표준 라이브러리 json을 사용하여 orjson 신규 의존성을 추가하지 않았다.

- urlopen 주입점을 두어 실제 KIS 네트워크 호출 없이 단위 테스트 대체가 가능하도록 했다.

- cache load/save, KST 만료시각 해석, EGW00133 유효 캐시 재사용 의미를 Reference와 동일한 책임 범위로 유지한다.