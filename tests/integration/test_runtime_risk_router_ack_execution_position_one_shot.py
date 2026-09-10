"""Test Runtime Risk Router Ack Execution Position One Shot — 테스트 사양 문서.

목적
Risk → Router → ACK → OMS → Execution → Position 전체 seam을 하나의 injected one-shot 흐름으로 검증한다.
검증 항목
/tmp/optionproject_verify_509
현재 OptionProject의 실제 계약을 기준으로 최소 production seam을 재구성하여 pytest를 실행했다.
실제 KIS credential/network/account/order는 사용하지 않았다.
ExecutionReport에는 side가 없으며, side와 originating BrokerOrderCommand는 OMS-owned state에서 공급된다. BrokerOrderCommand에 broker order id를 synthetic field로 추가하지 않는다. LiveExecutionPositionBridge는 OMS 상태에서 원 주문을 조회한다.
PASS
Market source_sequence blocker 및 H0IFCNI0/REST cross-source execution identity blocker는 별도로 유지한다.
"""
