from __future__ import annotations

from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner


ROOT = "data/derived_scenario/q25_strategy7_8_v2"


def main() -> None:
    cases = (
        (
            "strategy7_weekly",
            "track7_volatility_skew_weekly_insurance",
            "1.0",
        ),
        (
            "strategy8_monthly",
            "track8_macro_regime_monthly_strangle",
            "2.0",
        ),
    )
    for folder, strategy_id, version in cases:
        base = f"{ROOT}/{folder}"
        report = HighSpeedVirtualRuntimeReplayRunner(
            base,
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=f"{base}/manifest.json",
            strategy_keys=((strategy_id, version),),
        ).run(max_events=1)
        print(
            f"{folder}: events={report.events} signals={report.signals} "
            f"strategy_status={report.strategy_status}"
        )


if __name__ == "__main__":
    main()
