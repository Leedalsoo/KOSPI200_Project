## No.160 구현 — OptionProject KIS 인증·Calendar Composition 실제 경로 조사

### 조사 결과

No.159의 다음 단계에 따라 OptionProject의 Application composition root, KIS 인증/HTTP Adapter, Runtime public entrypoint를 실제 페이지 기준으로 확인했다.

### 1. Application composition

현재 구현된 Application 계층은 다음과 같다.

- application/runtime_controller/controller.py: EnvironmentHub를 받아 start/stop/status만 담당

- application/environment_hub/factory.py: Virtual/High-Speed/Paper/Live EnvironmentBundle 선택 및 builder 주입 담당

- 독립적인 application/bootstrap.py 실제 코드 페이지는 아직 없음

즉 현재 Application에는 Production Calendar를 조립해 OptionContractMaster에 주입하는 composition root가 아직 구현되어 있지 않다.

### 2. KIS 인증/HTTP Adapter

OptionProject/infrastructure에는 broker 폴더가 존재하지만 실제 KIS OAuth 인증 구현은 아직 이식되지 않았다.

최신 Reference option_program/broker/kis_auth.py에는 다음 재사용 대상이 존재한다.

- KISAuthManager

- KISAuthToken

- KISAuthError

- from_env()

- get_auth_headers(tr_id=...)

- OAuth token cache / expiry handling

따라서 OptionProject에 새 인증 체계를 만들면 Reference 기능 중복 및 credential semantics 분기가 발생한다.

### 3. Runtime public entrypoint

Reference의 실제 기본 Runtime 경로는:

OptionProgramRuntime()

→ create_default_krx_calendar(auto_load_kis=True)

→ create_default_option_master(calendar=self.calendar, auto_load_kis=True)

이다.

반면 OptionProject의 현재 RuntimeController는 EnvironmentBundle lifecycle만 관리하며 OptionContractMaster/TradingCalendar를 직접 생성하지 않는다.

따라서 현재 OptionProject에서 Production Calendar의 실제 조립 위치는 기존 RuntimeController 내부가 아니라 별도의 Application composition function/factory로 두는 것이 구조상 안전하다.

### 확정 이식 위치

다음 구조를 기준으로 구현한다.

```plain text
OptionProject/
├─ infrastructure/
│  └─ kis/
│     ├─ auth.py              # Reference KISAuthManager 기능 이식/재사용 경계
│     └─ holiday_provider.py  # KIS chk-holiday API Provider
└─ application/
   └─ composition/
      └─ option_master_factory.py
          create_production_trading_calendar(...)
          create_production_option_master(...)
```

의존 방향:

application composition

→ infrastructure.kis

→ contracts.TradingCalendar

→ core.oms.OptionContractMaster

Core는 Infrastructure를 import하지 않는다.

### 구현 판단

이번 조사 결과 기존 OptionProject에는 재사용 가능한 KISAuthManager가 아직 존재하지 않는다. 따라서 다음 구현 단계에서는 최신 Reference의 인증 기능을 OptionProject Infrastructure 경계로 선별 이식해야 한다.

단, orjson 등 Reference 구현의 부수 의존성을 그대로 복제하지 않고 OptionProject의 현재 pyproject.toml 및 dependency rules와 먼저 대조해야 한다.

### 원격 Git 검증

- Reference branch: Exp_Detail_1

- 확인 파일:
    - option_program/broker/kis_auth.py
    - option_program/runtime/program_runtime.py
    - shared/calendar/krx_calendar.py

- 원격 Git 수정 없음

### 다음 단계

No.161에서는 OptionProject의 pyproject.toml, dependency rules 및 Infrastructure 계층의 기존 import 규칙을 확인한 뒤:

1. KISAuthManager 최소 이식 범위 확정

1. infrastructure/kis/auth.py 생성

1. holiday_provider.py가 요구하는 인증 interface 확정

을 수행한다.

Calendar Provider 구현보다 인증 의존성의 단일 책임을 먼저 확정하여 중복 OAuth 구현을 방지한다.

n## No.164 실제 구현 반영n- infrastructure/kis/trading_calendar.py: ProductionTradingCalendar 구현n- application/composition/option_master_factory.py: Auth → Holiday Provider → Calendar → OptionMaster compositionn- Core는 기존 TradingCalendar Contract 주입 구조를 유지n- 테스트 페이지: test_production_trading_calendar.py, test_option_master_factory.pyn- 원격 Git Reference 수정 없음n

## No.165 정합성 점검 반영

- infrastructure.kis.trading_calendar 및 application.composition.option_master_factory의 실제 Notion 경로를 확인했다.

- ProductionTradingCalendar는 기존 TradingCalendar Protocol의 is_trading_day, prev_trading_day, trading_days_between를 모두 제공한다.

- Factory는 create_default_option_master(calendar=calendar, auto_load_kis=...)로 Calendar를 명시 주입한다.

- test_option_master_factory.py는 composition 경계와 Calendar 주입 여부를 mock 기반으로 검증하도록 작성되어 있다.

- 현재 Notion은 파일 페이지 저장소이므로 실제 Python package directory/__init__.py 존재 여부와 pytest 실행 PASS는 물리 workspace materialization 전까지 확정하지 않는다.

## No.166 실행 검증 반영

- Notion 코드 페이지에서 ProductionTradingCalendar와 test_production_trading_calendar.py의 동일 코드를 임시 Python workspace로 materialize했다.

- 임시 workspace의 package marker는 검증용으로만 추가했으며 OptionProject 원본 구조 변경이 아니다.

- python -m unittest discover -s tests -v 결과 3 tests PASS.

- Factory는 실제 외부 KIS 네트워크 없이 import dependency를 stub/mock으로 대체한 isolated composition 검증에서 Auth → Provider → Calendar → create_default_option_master(calendar=...) 전달을 PASS했다.

- 따라서 검증 가능한 순수/격리 경계는 실행 PASS로 승격하되, 실제 OptionProject 전체 physical package tree 및 실제 KIS HTTP 통합은 여전히 별도 검증 대상이다.