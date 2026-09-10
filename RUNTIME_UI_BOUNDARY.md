## Runtime Controller Commands

- select_environment

- start

- stop

- restart

- get_status

## Controller Status

Environment-neutral RuntimeStatus만 외부에 공개한다.

## UI Flow

Control Tower UI

→ Runtime Command/Status Contract

→ Runtime Controller

UI는 Environment 내부 객체를 직접 보지 않는다.

## Live Safety

Live 선택은 일반 Start와 동일 취급하지 않는다.

Safety/Authorization/Guard 상태가 명시적으로 READY여야 실행 가능하도록 이후 Live Phase에서 강화한다.