from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from application.strategy_hub.hub import StrategyHub
from contracts.types import CanonicalMarketTick
from core.domain.market_models import MarketState
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from environments.high_speed.validation_only_track1_input import S1ValidationOnlyRuntimeInputAdapter

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "config/validation_only/q25_a5_s15a_s1_runtime_input/manifest.json"
STRATEGY_ID = "TRACK1_TAIL_DEFENSE"
STRATEGY_KEY = (STRATEGY_ID, "1.2.0")


def _run_scenario(scenario_id: str):
    adapter = S1ValidationOnlyRuntimeInputAdapter(manifest_path=MANIFEST, root=ROOT)
    registry = StrategyRegistry()
    strategy = Track1TailDefense()
    registry.register(strategy)
    adapter.apply_to_strategy(strategy)
    hub = StrategyHub(registry, (STRATEGY_KEY,))
    rows = [
        row for row in adapter.events.values()
        if row["scenario_id"] == scenario_id
    ]
    rows.sort(key=lambda row: row["event_index"])
    signals = []
    for row in rows:
        observed = datetime.fromisoformat(row["timestamp"])
        tick = CanonicalMarketTick(
            instrument_id="KOSPI200_SYNTHETIC",
            observed_at=observed,
            price=Decimal(str(row["underlying_price"])),
        )
        built = adapter.build(tick=tick, as_of=observed)
        assert built.payload is not None, built.missing_sources
        context = StrategyContext(
            market_state=MarketState(
                as_of=observed,
                ticks={tick.instrument_id: tick},
                quality={},
            ),
            strategy_id=STRATEGY_ID,
            input=StrategyInput(payload=built.payload),
        )
        result = hub.run({STRATEGY_ID: context})
        assert not result.failures
        signals.extend(result.signals)
    return adapter, signals


@pytest.mark.parametrize(
    ("scenario_id", "option_type", "expected_strikes"),
    [
        ("S1_S15A_U28_UP", "PUT", [Decimal("92.5"), Decimal("95.0"), Decimal("97.5")]),
        ("S1_S15A_U28_DOWN", "CALL", [Decimal("107.5"), Decimal("105.0"), Decimal("102.5")]),
    ],
)
def test_strategy_hub_emits_natural_s1_short_signals_from_manifest_input(
    scenario_id, option_type, expected_strikes
):
    adapter, signals = _run_scenario(scenario_id)
    assert len(signals) == 3
    assert [signal.execution_proposal.option_type for signal in signals] == [option_type] * 3
    assert [signal.execution_proposal.strike for signal in signals] == expected_strikes
    assert all(signal.execution_proposal.side == "SELL" for signal in signals)
    assert adapter.evidence.event_count == 8
    assert adapter.evidence.dataset_sha256 == "05b16ad7aded564becf24b0c317f48756578e0c86b8b03568735c7eb19c16dcf"


def test_validation_input_rejects_market_price_mismatch():
    adapter = S1ValidationOnlyRuntimeInputAdapter(manifest_path=MANIFEST, root=ROOT)
    row = next(iter(adapter.events.values()))
    observed = datetime.fromisoformat(row["timestamp"])
    tick = CanonicalMarketTick(
        instrument_id="KOSPI200_SYNTHETIC",
        observed_at=observed,
        price=Decimal("999"),
    )
    result = adapter.build(tick=tick, as_of=observed)
    assert result.payload is None
    assert result.missing_sources == ("s1_validation_underlying_price_match",)


def test_validation_adapter_does_not_enable_non_s1_strategy():
    adapter = S1ValidationOnlyRuntimeInputAdapter(manifest_path=MANIFEST, root=ROOT)
    class OtherStrategy:
        strategy_id = "track2_asymmetric_trap"
    with pytest.raises(ValueError, match="S1_VALIDATION_STRATEGY_ID_MISMATCH"):
        adapter.apply_to_strategy(OtherStrategy())


def test_validation_adapter_rejects_dataset_hash_mismatch(tmp_path):
    import json
    import shutil
    source_root = ROOT
    for relative in (
        "config/validation_only/q25_a5_s15a_s1_runtime_input/manifest.json",
        "config/validation_only/q25_a5_s15a_s1_runtime_input/risk_profile.json",
        "data/derived_scenario/q25_a5_s15a_s1_runtime_input/events.jsonl",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, target)
    dataset = tmp_path / "data/derived_scenario/q25_a5_s15a_s1_runtime_input/events.jsonl"
    dataset.write_text(dataset.read_text(encoding="utf-8") + " ", encoding="utf-8")
    manifest = tmp_path / "config/validation_only/q25_a5_s15a_s1_runtime_input/manifest.json"
    with pytest.raises(ValueError, match="S1_VALIDATION_DATASET_HASH_MISMATCH"):
        S1ValidationOnlyRuntimeInputAdapter(manifest_path=manifest, root=tmp_path)


def test_validation_adapter_rejects_manifest_marked_runtime_eligible(tmp_path):
    import json
    import shutil
    for relative in (
        "config/validation_only/q25_a5_s15a_s1_runtime_input/manifest.json",
        "config/validation_only/q25_a5_s15a_s1_runtime_input/risk_profile.json",
        "data/derived_scenario/q25_a5_s15a_s1_runtime_input/events.jsonl",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    manifest = tmp_path / "config/validation_only/q25_a5_s15a_s1_runtime_input/manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["runtime_eligible"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="S1_VALIDATION_MANIFEST_INVALID"):
        S1ValidationOnlyRuntimeInputAdapter(manifest_path=manifest, root=tmp_path)
