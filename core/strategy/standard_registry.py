"""Versioned standard Strategy registry and configuration injection."""
from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
import inspect
import re
from pathlib import Path
from typing import Any

from core.strategy.contracts import ConfiguredStrategyPlugin
from core.strategy.definition import StrategyDefinition, load_strategy_manifest
from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping
from core.strategy.track5_gap_divergence import Track5GapDivergence
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance


STANDARD_STRATEGY_TYPES = (
    Track1TailDefense,
    Track2AsymmetricTrap,
    Track3StatisticalArbitrage,
    Track4GammaScalping,
    Track5GapDivergence,
    Track6DailyTailInsurance,
    Track7VolatilitySkewWeeklyInsurance,
    Track8MacroRegimeMonthlyStrangle,
    Track9EventOvernightInsurance,
)
STANDARD_STRATEGY_TYPE_BY_ID = {item.strategy_id: item for item in STANDARD_STRATEGY_TYPES}
STANDARD_STRATEGY_KEYS = tuple((item.strategy_id, item.version) for item in STANDARD_STRATEGY_TYPES)
STANDARD_STRATEGY_IDS = tuple(strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS)


def _coerce_config_value(value: Any, current: Any) -> Any:
    if isinstance(current, Decimal):
        return Decimal(str(value))
    if isinstance(current, timedelta):
        if not isinstance(value, str):
            raise ValueError("STRATEGY_DURATION_CONFIG_MUST_BE_ISO8601")
        match = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", value)
        if not match:
            raise ValueError(f"STRATEGY_DURATION_CONFIG_INVALID:{value}")
        hours, minutes, seconds = (float(part or 0) for part in match.groups())
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if isinstance(current, time):
        return time.fromisoformat(str(value))
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise ValueError("STRATEGY_BOOLEAN_CONFIG_INVALID")
        return value
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)
    return value


def _instantiate_strategy(strategy_type: type, definition: StrategyDefinition):
    signature = inspect.signature(strategy_type)
    constructor_values: dict[str, Any] = {}
    instance_overrides: dict[str, Any] = {}
    configurable = set(getattr(strategy_type, "CONFIGURABLE_PARAMETERS", ()))

    for key, raw_value in definition.parameters.items():
        if key in signature.parameters and key != "self":
            default = signature.parameters[key].default
            constructor_values[key] = _coerce_config_value(raw_value, default)
            continue
        if key not in configurable or not hasattr(strategy_type, key):
            raise ValueError(f"STRATEGY_CONFIG_PARAMETER_UNSUPPORTED:{definition.strategy_id}:{key}")
        instance_overrides[key] = _coerce_config_value(raw_value, getattr(strategy_type, key))

    strategy = strategy_type(**constructor_values)
    for key, value in instance_overrides.items():
        setattr(strategy, key, value)
    # Reinitialize state after applying instance-level parameters so state defaults
    # (for example Track1's initial fence distance) match the pinned config.
    strategy.reset()

    strategy.config_version = definition.config_version
    strategy.config_hash = definition.config_hash
    strategy.definition = definition
    if not isinstance(strategy, ConfiguredStrategyPlugin):
        raise ValueError(f"CONFIGURED_STRATEGY_PLUGIN_CONTRACT_INVALID:{definition.strategy_id}")

    requirements_method = getattr(strategy, "feature_requirements", None)
    actual_requirements = tuple(
        item.metric_key for item in requirements_method()
    ) if callable(requirements_method) else ()
    if actual_requirements != definition.required_analytics:
        raise ValueError(f"STRATEGY_ANALYTICS_CONTRACT_MISMATCH:{definition.strategy_id}")
    return strategy


def build_standard_strategy_registry(
    config_path: str | Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> StrategyRegistry:
    """Build strategies from a pinned manifest; code and config versions stay distinct."""
    manifest = load_strategy_manifest(config_path, expected_sha256=expected_sha256)
    definitions = manifest.by_id()
    code_ids = set(STANDARD_STRATEGY_TYPE_BY_ID)
    config_ids = set(definitions)
    if code_ids != config_ids:
        raise ValueError(
            f"STRATEGY_MANIFEST_CODE_SET_MISMATCH:missing_config={sorted(code_ids-config_ids)};"
            f"unknown_config={sorted(config_ids-code_ids)}"
        )

    registry = StrategyRegistry()
    for strategy_type in STANDARD_STRATEGY_TYPES:
        definition = definitions[strategy_type.strategy_id]
        if definition.code_version != strategy_type.version:
            raise ValueError(
                f"STRATEGY_CODE_VERSION_MISMATCH:{strategy_type.strategy_id}:"
                f"manifest={definition.code_version}:code={strategy_type.version}"
            )
        strategy = _instantiate_strategy(strategy_type, definition)
        registry.register(strategy, definition=definition)
    return registry
