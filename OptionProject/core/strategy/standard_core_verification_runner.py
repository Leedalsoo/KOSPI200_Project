"""Independent verification entry point for the Standard Core full integration test.

This file is a verification harness specification. It must not be treated as a
production Runtime component and must not import Legacy Runtime modules.
"""

from core.strategy.test_standard_strategy_orchestrator_full_integration import (
test_all_contexts_match_standard_identity_manifest,
test_all_nine_actual_strategies_complete_full_lifecycle,
test_registry_accepts_strategy_payloads_without_optional_identity_field,
test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing,
test_same_fresh_registry_and_fixture_is_deterministic,
)


def run_independent_verification() -> None:
    """Run the five Standard Core integration assertions directly."""
    test_all_contexts_match_standard_identity_manifest()
    test_all_nine_actual_strategies_complete_full_lifecycle()
    test_registry_accepts_strategy_payloads_without_optional_identity_field()
    test_same_fresh_registry_and_fixture_is_deterministic()
    test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing()
    print("STANDARD_CORE_FULL_INTEGRATION_PASS")


if __name__ == "__main__":
    pass
    run_independent_verification()
# No.064에서 지정한 다음 단계인 실제 실행 가능한 독립 검증 경로를 고정한다. 이 harness는 Production Runtime이나 Legacy Runtime에 편입하지 않고 Standard Core Test만 직접 호출한다.
# 권장 1차 경로:
# python -m core.strategy.standard_core_verification_runner
# pytest가 설치된 일반 개발환경에서는 기존 테스트도 별도로 실행한다.
# python -m pytest core/strategy/test_standard_strategy_orchestrator_full_integration.py -q
