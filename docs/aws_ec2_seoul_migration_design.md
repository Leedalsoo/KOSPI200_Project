# AWS EC2 서울 리전 무인 운영 이전 설계안

- 문서 상태: **설계 전용 / 구현·프로비저닝 금지**
- 대상: Windows 작업 PC에서 실행 중인 KIS 수집기·Watchdog·Virtual Runtime의 AWS EC2 서울 리전 이전
- 기준: Project200 `AGENTS.md`, Notion No.717 / No.724
- 작성일: 2026-09-22
- 승인 게이트: 사용자의 명시적 구현 승인 전까지 AWS 자원 생성·설치·배포·credential 업로드를 수행하지 않는다.

## 0. 범위와 현재 상태

### 판정
- **확정**: 이번 문서는 설계만 다룬다. AWS EC2, EBS, S3, IAM, Secrets Manager 등의 실제 자원은 만들지 않는다.
- **확정**: 기존 Windows 운영 스크립트는 이번 단계에서 수정하지 않는다.
- **확정**: 실제 KIS 주문은 이전·검증 과정에서도 호출하지 않는다.
- **추가 확인 필요**: EC2에서 사용할 Linux 배포판, 인스턴스 크기, EBS 용량, S3 보존비용은 실제 배포 전 결정한다.
- **미정**: 최종 AWS 계정/네트워크/VPC 구성과 도메인 이름.

## 1. 사전 감사 — Windows 종속 요소 목록화

### 1.1 Watchdog의 Windows 종속

현재 `scripts/run_kis_daily_watchdog.ps1`는 다음 Windows 전용 요소에 의존한다.

- PowerShell 스크립트 실행 환경.
- `Get-CimInstance Win32_Process`를 이용한 `py.exe` 프로세스 탐지.
- `System.Threading.Mutex` named mutex로 Watchdog 중복 실행 방지.
- `Start-Process`, `Get-Process`, `WaitForExit`, `Start-Sleep` 사용.
- Python 실행 파일이 `C:\WINDOWS\py.exe`로 고정되어 있음.
- ProjectRoot가 Windows 절대경로로 고정되어 있음.
- 로그 경로가 Windows backslash 경로로 구성됨.

**판정: 확정 — EC2에서는 이 PowerShell Watchdog를 그대로 이식하지 않는다.**

### 1.2 Collector 실행 방식

현재 Collector의 표준 Python 모듈 실행점은 다음과 같다.

`py -m infrastructure.kis.kis_vts_weekday_collector`

실제 Collector 코드는 `pathlib`, `os.environ`, `asyncio`, `urllib`, `websockets` 등 Python 표준/패키지 기반이며, 확인한 핵심 Collector·REST collector·auth·historical store 코드에는 Windows 전용 API 호출이 없다.

따라서 **Python 애플리케이션 자체는 Linux 이식 가능성이 높다.** 다만 다음은 실제 EC2에서 검증해야 한다.

- Python 3.11+ 설치 및 패키지 호환성.
- `websockets` 등 의존성 설치.
- Linux 파일 권한과 timezone 처리.
- systemd가 전달하는 환경변수/작업 디렉터리.
- KIS REST/WS 네트워크 연결.

**판정: 추가 확인 필요 — 순수 Python 경계는 Linux 친화적이지만 실제 EC2 실행 PASS는 배포 후 검증이 필요하다.**

### 1.3 ProjectRoot 고정값

현재 Windows Watchdog의 `ProjectRoot`는 특정 사용자 PC의 절대경로로 고정되어 있다. EC2에서는 `/opt/project200` 같은 Linux 경로를 서비스의 `WorkingDirectory`로 지정하고 코드에는 PC의 절대경로를 전달하지 않는 구조를 사용한다.

**판정: 확정 — 배포 환경의 WorkingDirectory와 애플리케이션 상대경로를 분리한다.**

### 1.4 credential / `.env` 읽기

현재 `infrastructure/kis/auth.py`의 `KISAuthManager.from_env()`는 환경변수를 우선 사용하고, 지정된 `.env` 파일을 fallback으로 읽는다. 토큰 cache는 별도 JSON 파일로 저장하고 파일 권한을 `0600`으로 제한하려는 코드가 있다.

현재 `.gitignore`에는 `.env`, `.env.*`, `data/`, `*.log` 등이 제외되어 있다.

**판정: 확정 — EC2 운영에서는 Git의 `.env`에 credential을 넣지 않고 AWS 비밀 저장소에서 주입한다.**

### 1.5 시장데이터 경로

현재 Collector의 시장데이터 root는 `PROJECT200_MARKET_DATA_DIR` 환경변수로 override할 수 있다. 상대경로는 ProjectRoot의 `data/` 아래로 해석된다. 현재 Windows Watchdog는 `kis_market_data_restart`를 설정하므로 실제 활성 root는 ProjectRoot 기준 `data/kis_market_data_restart/`이다.

코드의 기본값은 `kis_market_data`이며 이것도 절대 Windows 경로가 아니라 ProjectRoot의 `data/kis_market_data/`로 해석된다. 따라서 `data/kis_market_data/YYYY-MM-DD/` 자체는 상대경로 기반이다.

**판정: 확정 — EC2에서는 `/var/lib/project200/data` 같은 명시적 데이터 디렉터리를 서비스 설계로 정하고, 코드에는 상대경로/환경변수만 전달한다. 기존 Windows 경로는 수정하지 않는다.**

## 2. Watchdog 재설계

### 2.1 선택지 A — Linux systemd

`project200-collector.service`를 하나의 systemd 서비스로 정의하고 Collector 프로세스를 직접 관리한다.

설계 핵심:

- `WorkingDirectory=/opt/project200`
- `ExecStart=/usr/bin/python3 -m infrastructure.kis.kis_vts_weekday_collector` 개념으로 실행
- `Restart=always`
- `RestartSec=10`
- `KillSignal=SIGTERM`
- stdout/stderr는 journald로 수집
- 별도 애플리케이션 heartbeat는 기존 운영 기준에 맞춰 파일/구조화 로그로 유지

**장점**: Linux 기본 운영체계에 가깝고 Docker 레이어가 없어 구조가 단순하다. `journalctl`로 시작·종료·재시작 원인을 확인하기 쉽다.

**단점**: systemd unit 파일과 Linux 서비스 권한을 처음 한 번 이해해야 한다.

### 2.2 선택지 B — Docker restart policy

Collector를 컨테이너 하나로 패키징하고 `restart: always` 또는 이에 준하는 restart policy로 재기동한다.

**장점**: Python/의존성/실행환경을 이미지로 고정하기 쉽고 향후 서버 이전성이 높다.

**단점**: Dockerfile, image, volume, container log, permission 등 관리 계층이 추가된다. 초보자에게 systemd보다 운영 요소가 많다.

### 2.3 권장안

**판정: 확정 — 1차 EC2 운영은 systemd를 권장한다.**

이유는 현재 목표가 컨테이너 플랫폼 구축이 아니라 **수집기를 안정적으로 무인 실행하고 휴대폰에서 상태를 확인하는 것**이며, systemd가 이 목적에 필요한 자동 재시작과 로그 조회를 가장 적은 계층으로 제공하기 때문이다.

기존 named mutex는 systemd 서비스가 Collector의 단일 운영 주체가 되는 것을 전제로 제거 대상이 될 수 있다. 다만 systemd가 임의로 실행된 별도 Python 프로세스까지 자동으로 찾아 제거하는 것은 아니므로, 운영 규칙상 Collector를 수동으로 직접 실행하지 않고 systemd만이 운영 프로세스를 시작하도록 한다.

**판정: 추가 확인 필요 — 중복 프로세스가 수동 실행될 가능성까지 차단해야 한다면 Linux file lock 또는 별도 PID/lock 정책을 후속 설계한다.**

### 2.4 재시작/heartbeat 기록

systemd의 시작·종료·재시작·비정상 종료는 journald에서 확인하고, Collector 자체의 heartbeat에는 날짜, run_id, cycle_id, REST 상태, 마지막 수신 시각 등을 기록한다. Watchdog 자체를 별도 장기 루프로 만들지 않고 systemd 상태를 운영 supervisor로 사용한다.

**판정: 확정 — OS supervision과 애플리케이션 heartbeat를 서로 다른 증거로 보존한다.**

## 3. Credential 보안 설계

### 3.1 옵션 비교

| 방식 | 보안/감사 | 운영 난이도 | 회전 | 판정 |
|---|---|---|---|---|
| AWS Secrets Manager + EC2 IAM Role | 높음 | 중간 | 용이 | **권장** |
| SSM Parameter Store SecureString | 높음 | 중간 | 가능 | **대안** |
| EC2 파일에 1회 scp | 중간 | 낮음 | 수동 | **비권장** |
| Git `.env` | 부적절 | 낮음 | 위험 | **금지** |

AWS 공식 문서는 API key/token 같은 secret에는 Secrets Manager를 권장하고, Parameter Store의 `SecureString`은 KMS로 암호화할 수 있다고 설명한다. citeturn0search1turn0search0

### 3.2 권장 구조

**판정: 확정 — AWS Secrets Manager를 1차 권장한다.**

구조는 다음과 같다.

`EC2 Instance Role → Secrets Manager → KIS credential → 런타임 환경변수/메모리`

Git에는 secret 값이 전혀 들어가지 않는다. EC2 인스턴스에는 최소 권한 IAM Role만 부여하고, 해당 Role이 Project200 운영용 secret 하나 또는 필요한 secret 항목만 읽도록 제한한다.

애플리케이션은 기존 `KISAuthManager.from_env()`의 환경변수 우선 구조와 맞물릴 수 있도록, 구현 단계에서 secret retrieval 결과를 프로세스 시작 시 환경변수로 주입하거나 별도의 안전한 credential provider를 설계한다. **이번 단계에서는 코드 변경을 하지 않는다.**

**판정: 추가 확인 필요 — 현재 auth.py에 AWS SDK/Secrets Manager 연동은 존재하지 않으므로 실제 주입 방식은 구현 단계에서 결정한다.**

### 3.3 SSM Parameter Store 대안

`SecureString`을 사용하면 KMS로 값을 암호화하고 EC2 IAM Role에 특정 parameter 읽기 권한을 부여할 수 있다. AWS 문서상 KMS decrypt 권한과 parameter 접근 권한을 IAM 정책으로 제한할 수 있다. citeturn0search0turn0search2

초기 규모가 작고 secret 종류가 적으면 SSM도 충분하지만, 향후 credential 자동 rotation·감사·비밀관리 확장이 중요해지면 Secrets Manager가 더 적합하다.

**판정: 확정 — SSM은 구현 시 비용/운영 단순성 비교 후 대안으로 선택 가능.**

### 3.4 scp 1회 전송

`.env`를 EC2에 한 번 복사하고 Git에는 넣지 않는 방식은 설정 자체는 쉽지만, 파일이 장기간 서버 디스크에 남고 회전·감사·권한관리가 수동이다.

**판정: 미정/비권장 — 긴급 임시 bootstrap 용도 외에는 운영 표준으로 채택하지 않는다.**

### 3.5 회전/만료 절차

1. 새 KIS credential 발급/재발급.
2. AWS Secrets Manager의 기존 secret version을 새 값으로 갱신.
3. Collector를 안전하게 재시작하여 새 credential을 읽는다.
4. read-only 인증/시장데이터 smoke를 수행한다.
5. 이전 credential을 폐기하거나 만료시킨다.
6. 로그와 Notion에는 secret 값 대신 회전 시각과 성공/실패 상태만 기록한다.

**판정: 확정 — secret 값 자체는 로그/Notion/Git에 기록하지 않는다.**

## 4. 네트워크·방화벽 설계

### 4.1 기본 원칙

EC2는 private subnet + NAT Gateway 구조를 우선 검토한다. 외부에서 EC2로 직접 들어오는 경로를 줄이고, 서버의 일반적인 인터넷 접근은 outbound로만 만든다.

**판정: 추가 확인 필요 — 비용을 줄이는 단일 public subnet 구조와 private subnet+NAT 구조 중 최종 선택은 AWS 비용/운영 수준을 보고 결정한다.**

### 4.2 아웃바운드

필요한 외부 통신은 최소한 다음으로 분류한다.

- KIS REST: HTTPS/TLS.
- KIS WebSocket: 현재 코드의 VTS endpoint는 `ws://ops.koreainvestment.com:31000`, Live endpoint는 `ws://ops.koreainvestment.com:21000`으로 확인되므로 HTTPS 443만으로 WebSocket이 완결된다고 가정하지 않는다.
- GitHub: HTTPS 443 — 코드 배포/업데이트 시 사용.
- Notion: HTTPS 443 — Notion API/연동이 서버에서 직접 필요한 경우.
- AWS Secrets Manager/SSM: AWS API endpoint 접근.
- DNS/NTP 등 서버 운영에 필요한 AWS/네트워크 서비스.

**판정: 확정 — 현재 실제 코드의 KIS WS 포트까지 고려해야 한다.**

중요한 보안 제한사항: AWS Security Group의 일반적인 egress 규칙은 IP/포트 중심이므로 "특정 HTTPS 도메인만 허용"을 Security Group 하나만으로 완전히 구현한다고 가정하지 않는다. 정말로 도메인 allowlist 수준의 outbound 제한이 필요하면 NAT/egress proxy 또는 AWS Network Firewall 등의 별도 계층을 추가한다.

**판정: 추가 확인 필요 — 비용과 관리 난이도를 고려한 최종 egress 통제 수준은 구현 전에 결정한다.**

### 4.3 인바운드

기본은 inbound deny에 가깝게 구성하고 SSH(22)는 다음 중 하나만 허용한다.

- 고정된 사무실/가정 공인 IP.
- VPN을 통해서만 SSH.
- 가능하면 AWS Systems Manager Session Manager를 사용하여 inbound SSH 자체를 운영 경로에서 제거.

휴대폰의 IP가 고정되지 않는다면 SSH를 0.0.0.0/0로 열어 두는 방식은 기본안으로 사용하지 않는다.

**판정: 확정 — 일상 관리에는 웹/SSM을 우선하고 SSH는 긴급 디버깅용으로 제한한다.**

### 4.4 Control Tower 외부 노출

Control Tower 웹 UI를 인터넷에 직접 노출한다면 TLS(HTTPS)뿐 아니라 애플리케이션 인증을 별도로 둔다. 최소한 강한 인증 토큰 또는 인증 프록시를 사용하고, 주문/운영 명령 endpoint는 별도 authorization을 적용한다.

가능하면 `Internet → HTTPS reverse proxy/auth → Control Tower` 구조를 사용하며 Control Tower 자체 포트는 public으로 열지 않는다.

**판정: 확정 — 무인 서버에서 인증 없는 Control Tower public 노출은 금지한다.**

## 5. 데이터 저장·백업 설계

### 5.1 EC2 로컬 데이터 위험

`data/.../YYYY-MM-DD/`가 EBS에만 존재하면 인스턴스 자체 장애, 파일시스템 손상, 운영 실수 등으로 수집 원본이 손실될 수 있다. 시장 원본은 단순 캐시가 아니라 Replay/검증 자산이므로 별도 백업이 필요하다.

**판정: 확정 — EC2 로컬 디스크만을 유일한 보존수단으로 사용하지 않는다.**

### 5.2 S3 동기화 권장

권장 구조:

`EC2 local data → 주기적 S3 sync → S3 versioning/lifecycle`

권장 초기 정책:

- 장중: 5~15분 주기 incremental sync 검토.
- 장 마감: 당일 partition 전체 무결성/해시 확인 후 final sync.
- 보존: 최소 1년의 원본/manifest 보존을 1차 기준으로 검토.
- 이후 오래된 데이터는 S3 Lifecycle로 저비용 storage class 전환.

S3 Lifecycle은 객체의 일정 기간 후 storage class 전환이나 만료를 지원한다. Versioning을 함께 사용하면 비정상 overwrite에 대한 복구 여지도 확보할 수 있다. citeturn0search3turn0search7

**판정: 확정 — S3를 장기 보존 원본 저장소로 사용한다.**
**추가 확인 필요 — 1년 보존기간과 5~15분 sync 주기는 비용/데이터량을 보고 최종 확정한다.**

### 5.3 EBS snapshot 대안

EBS snapshot은 디스크 전체 복구 관점의 대안/보조 수단으로 검토한다. 그러나 snapshot은 시장데이터 파일의 broker/date 단위 논리적 보존·검증을 대신하지 않으므로 S3 원본 보존을 우선하고 snapshot은 시스템 복구용으로 사용한다.

**판정: 추가 확인 필요 — snapshot 주기는 주 1회 또는 운영 변경 전후 등으로 후속 결정.**

## 6. 원격 관리·모니터링

### 6.1 휴대폰 중심 운영

목표 구조:

`휴대폰 브라우저 → HTTPS + 인증 → Control Tower → Runtime/Collector 상태`

Control Tower에는 최소 다음 read-only 상태를 표시하도록 설계한다.

- Collector: RUNNING / STOPPED / BLOCKED / UNKNOWN.
- 마지막 heartbeat.
- 마지막 수집 시각과 수집 계약 수.
- broker/transport 상태.
- 오늘 partition 경로.
- 최근 restart count/reason.
- 데이터 파일 크기 및 마지막 SHA 검증 상태.
- Virtual Runtime 상태.
- Live credential 상태는 값이 아니라 READY/INCOMPLETE 같은 상태만 표시.

**판정: 확정 — 일상 운영은 브라우저 UI 중심으로 설계한다.**

### 6.2 알림

초기 알림은 **Telegram Bot**을 1차 후보로 권장한다. 휴대폰에서 즉시 확인하기 쉽고, 운영자가 별도 메일함을 열 필요가 없기 때문이다.

알림 이벤트:

- Collector 시작.
- Collector 비정상 종료/재시작.
- heartbeat 장시간 미수신.
- KIS authentication failure.
- REST/WS transport failure.
- 저장/백업 실패.
- disk usage 임계치 초과.
- Control Tower/Runtime 비정상 상태.

Telegram token/chat id 역시 credential로 취급하여 AWS secret store에 보관하고 Git/로그/Notion에는 기록하지 않는다.

**판정: 추가 확인 필요 — Telegram 사용 여부와 정확한 heartbeat timeout은 구현 전 확정한다.**

### 6.3 SSH의 역할

SSH는 긴급 디버깅과 장애 복구에만 남긴다. 일상적인 프로세스 상태 확인과 시장데이터 확인은 Control Tower와 systemd/journald 관측 경계로 끝내는 것을 목표로 한다.

AWS Systems Manager Session Manager를 사용할 경우 EC2에 inbound SSH를 열지 않고도 관리 세션을 구성할 수 있으므로, SSH 고정 IP 제한의 대안으로 검토한다.

**판정: 확정 — SSH는 보조/비상 관리 경로다.**
**추가 확인 필요 — Session Manager를 최종 관리 경로로 채택할지는 AWS IAM/비용/초보자 운영 편의성을 보고 결정한다.**

## 7. 마이그레이션 절차 설계

실제 실행은 하지 않으며, 다음 순서를 운영 Runbook의 기준으로 삼는다.

### 7.1 1단계 — EC2 인스턴스 프로비저닝

설계: 서울 리전에 Linux EC2, 적절한 EBS, IAM instance role, Security Group, 필요시 private subnet/NAT 구성.

검증 기준: 인스턴스가 정상 부팅되고 관리 경로(SSM 또는 제한된 SSH)가 확보되며 시간대/디스크/네트워크 상태가 정상.

건너뛰기: 불가.

**판정: 추가 확인 필요**

### 7.2 2단계 — Project200 clone/deploy

설계: `Project200` branch를 기준으로 코드 배포. Git credential을 코드/파일에 저장하지 않는다.

검증 기준: commit SHA가 의도한 Project200 원격 HEAD와 일치하고 필요한 파일이 존재.

건너뛰기: 이미 동일 SHA가 안전하게 배포된 경우 재clone은 생략 가능하나 배포 검증은 생략하지 않는다.

**판정: 확정**

### 7.3 3단계 — 의존성 설치

설계: Python 3.11+와 `pyproject.toml`에 선언된 runtime/test 의존성을 환경에 맞게 설치한다.

검증 기준: `pyproject.toml` 의존성이 설치되고 `py -m pytest`에 해당하는 Linux Python 실행체계에서 smoke가 가능해야 한다. EC2에서는 Windows `py` launcher가 없으므로 실제 구현 시 Linux의 `python3`/venv 운영 명령으로 대체한다.

**판정: 추가 확인 필요 — 사용자의 Windows `py` 규칙은 Windows 검증에 적용하고, EC2 Linux에서는 Linux 표준 실행체계를 별도로 정의한다.**

### 7.4 4단계 — credential 설정

설계: Secrets Manager + IAM Role 기반으로 KIS VTS/Live credential을 주입한다. 초기 이전에서는 Live 주문 권한을 사용하지 않고 read-only/VTS 검증부터 한다.

검증 기준: secret 값 자체를 출력하지 않고 인증 성공 여부만 확인. 로그/Git/Notion에 secret이 남지 않는지 확인.

건너뛰기: 불가.

**판정: 확정**

### 7.5 5단계 — read-only REST dry-run

설계: 주문 endpoint를 전혀 호출하지 않고 KIS REST market-data/auth 경계만 검증한다.

검증 기준:

- 인증 성공.
- Option Master identity 정상.
- Price/OrderBook read-only 응답 정상.
- raw/canonical provenance 보존.
- 날짜 partition 저장 성공.
- 주문 endpoint 호출 로그가 없음.

**판정: 확정 — 실제 거래 이전 필수 단계.**

### 7.6 6단계 — PC/EC2 동시 교차검증

기존 Windows Collector와 EC2 Collector를 일정 기간 병행한다. 다만 동일 KIS credential에 대해 두 프로세스가 각각 동일한 전체 요청량을 발생시키면 rate limit을 초과할 수 있으므로, 실제 동시운영에서는 **계약 subset 분할 또는 rate-limit 총량을 공유하는 조정**을 먼저 설계한다.

권장 검증 방식:

- KIS: EC2와 PC가 서로 다른 계약 subset을 수집.
- 별도의 소수 control contract만 공통 관측하여 시간차를 보정한 가격/호가 비교.
- 동일 `canonical identity`, observed_at 근접성, last/bid/ask 범위, missing/error 비율을 비교.
- 한쪽이 누락될 때 다른 쪽 데이터가 존재하는지 확인.

검증 기준: 지정된 관측시간 window에서 양쪽 수집값이 허용 오차 범위 안에 들어오고, identity/provenance가 일치하며, 누락/오류율에 설명되지 않는 차이가 없어야 한다.

건너뛰기: 별도 KIS credential을 사용하여 충분한 독립 테스트를 완료했거나 기존 원본과 EC2 dry-run을 통해 동일성 증거가 충분하다고 승인된 경우에만 가능.

**판정: 확정 — 단, 실제 동시수집 rate-limit 계획은 추가 확인 필요.**

### 7.7 7단계 — EC2로 전환

설계: 교차검증 PASS 후 PC 수집을 중단하고 EC2 systemd service를 primary로 전환한다.

검증 기준: EC2에서 일정 시간 heartbeat/수집이 지속되고 S3 final sync까지 정상이며 Control Tower에서 상태가 확인된다.

**판정: 확정**

### 7.8 8단계 — PC Collector 종료

설계: EC2 primary 전환과 최소 안정화 기간 확인 후 Windows Watchdog/Collector를 종료한다. 기존 PC 데이터는 삭제하지 않고 보존한다.

검증 기준: PC 수집 중단 이후에도 EC2 partition이 계속 생성되고 backup이 정상이다.

**판정: 확정**

## 8. 장애 대응 메모

EC2가 중단되면 우선 Control Tower/Cloud 상태와 마지막 heartbeat를 확인하고, 실제 포지션이 존재하는 운용 단계라면 자동 복구만 기다리지 말고 포지션 상태를 확인하여 필요한 청산/위험축소 조치를 수동으로 결정한다. KIS 계좌/주문 상태 확인이 필요하면 KIS 공식 채널과 본인이 확보한 증권사 연락처를 사용한다. **자동 페일오버·비상 이중 서버·자동 포지션 청산은 이번 설계에 포함하지 않는다.**

**판정: 확정 — 최소 수동 대응만 정의.**
**미정 — 자동 failover/DR 및 비상 서버 이중화는 후속 과제.**

## 9. 최종 아키텍처 요약

```text
휴대폰 브라우저
      │ HTTPS + 인증
      ▼
Control Tower / Reverse Proxy
      │
      ├──────────────► 상태/알림
      │
      ▼
AWS EC2 서울 리전
  Linux + systemd
      │
      ├── KIS Collector
      │     ├── REST primary
      │     └── WS 보조(raw frame)
      │
      ├── Virtual Runtime
      │
      ├── local data/YYYY-MM-DD
      │
      └── S3 backup/sync

Credential:
EC2 IAM Role → AWS Secrets Manager → runtime secret injection

운영관리:
SSM Session Manager 또는 제한된 SSH → 긴급 디버깅
Telegram → restart/auth/heartbeat/backup 장애 알림
```

## 10. 구현 승인 게이트

- **확정**: 이 문서 자체는 설계 산출물이며 실제 AWS 자원을 생성하지 않는다.
- **확정**: 기존 Windows 운영 스크립트는 이번 설계 단계에서 수정하지 않는다.
- **확정**: `.env`, KIS credential, Telegram token 등 secret은 Git/Notion/로그에 기록하지 않는다.
- **확정**: 실제 주문 endpoint는 이전 검증에서 호출하지 않는다.
- **확정**: EC2 운영 supervisor는 1차로 systemd를 사용한다.
- **확정**: 장기 시장 원본은 S3를 우선 보존 대상으로 한다.
- **추가 확인 필요**: Linux 배포판/EC2 size/EBS/VPC/subnet/NAT/egress 통제/backup 비용/Control Tower 인증/Telegram timeout.
- **미정**: 자동 failover, DR, 다중 AZ/비상 서버 이중화.
- **승인 조건**: 사용자가 별도로 구현을 명시 승인한 이후에만 AWS 프로비저닝·배포·credential 연결 작업을 시작한다.
