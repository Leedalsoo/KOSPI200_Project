"""Test Live Runtime Production Composition Identity Boundary — 테스트 사양 문서.

목적
LiveRuntimeProductionFactory → LiveRuntimeLifecycleCoordinator → RuntimeController/LiveEnvironmentBundle → Bootstrap 하나의 injected composition에서 caller-supplied dependency identity와 lifecycle ordering을 실제 경계 기준으로 검증한다.
검증 범위
production factory가 caller-supplied runtime_transport, tick_entry, broker, position_aggregate를 교체·복제하지 않는지 확인
/tmp/optionproject_verify_508
실제 KIS credential/network/account/order는 생성하지 않고, OptionProject의 현재 production assembly 경계를 최소 stub으로 재구성하여 terminal pytest로 검증했다.
PASS
현재 production factory/bootstrap/controller 구조에서 caller-supplied dependency를 다른 객체로 바꾸는 경로를 확인하지 못했다. 별도 production code 수정은 필요하지 않았다.
Market CanonicalMarketTick.source_sequence BLOCKED와 H0IFCNI0/REST cross-source execution identity BLOCKED는 이 검증과 독립적으로 유지한다.
"""
