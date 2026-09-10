"""Test Live Runtime Production Factory Identity — 테스트 사양 문서.

검증 목적
create_live_runtime_lifecycle_coordinator()가 caller-supplied tick_entry, runtime_transport, broker, position_aggregate를 교체·복제하지 않고 production dependency graph에 전달하는지 검증한다.
/tmp/optionproject_verify_507
production factory source를 임시 workspace에 재구성하고 assembly dependency만 최소 stub으로 대체하여 targeted pytest 실행.
결과: 2 passed.
실제 KIS 인증·네트워크·계좌·주문은 사용하지 않았다.
"""
