from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

DAYS = (
    "20261002", "20261007", "20261008", "20261012", "20261013",
    "20261014", "20261015", "20261016", "20261020", "20261021",
    "20261022", "20261023", "20261026", "20261027", "20261028",
    "20261029", "20261030", "20261102", "20261103", "20261104",
    "20261105", "20261106", "20261109", "20261110", "20261111",
    "20261112", "20261113",
)
WINDOW_START = 9 * 3600 + 30
WINDOW_END = 9 * 3600 + 30 * 60
ADVANCE_CANDIDATES = (1.0, 2.0, 3.0, 5.0)
REVERSAL_CANDIDATES = (0.5, 1.0, 1.5, 2.0, 3.0)
PERSISTENCE_CANDIDATES = (2, 3, 5, 10)
DEFAULT_SOURCE_ROOT = Path(
    r"C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart"
)


def _to_seconds(value: str) -> int:
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"Invalid HHMMSS: {value!r}")
    return int(value[:2]) * 3600 + int(value[2:4]) * 60 + int(value[4:6])


def _to_hhmmss(value: int | None) -> str | None:
    if value is None:
        return None
    hour, rem = divmod(value, 3600)
    minute, second = divmod(rem, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def first_persistent_time(
    observations: list[dict],
    field: str,
    threshold: float,
    persistence_seconds: int,
    *,
    before_sec: int | None = None,
    after_sec: int | None = None,
) -> int | None:
    """Return the completion second of a consecutive observed threshold run.

    Missing seconds break a run. before_sec is exclusive; after_sec is inclusive.
    """
    streak = 0
    previous_second = None
    for observation in observations:
        second = int(observation["second"])
        if before_sec is not None and second >= before_sec:
            break
        if after_sec is not None and second < after_sec:
            streak = 0
            previous_second = None
            continue
        value = float(observation[field])
        if value >= threshold:
            if previous_second is not None and second == previous_second + 1:
                streak += 1
            else:
                streak = 1
            previous_second = second
            if streak >= persistence_seconds:
                return second
        else:
            streak = 0
            previous_second = None
    return None


def _add_peak_retracement(observations: list[dict], advance_second: int) -> list[dict]:
    result = []
    peak = float("-inf")
    for observation in observations:
        if int(observation["second"]) < advance_second:
            continue
        favorable = float(observation["favorable"])
        peak = max(peak, favorable)
        row = dict(observation)
        row["retrace"] = max(0.0, peak - favorable)
        result.append(row)
    return result


def _find_day_directory(source_root: Path, day: str) -> Path:
    compact = source_root / day
    if compact.is_dir():
        return compact
    dashed = source_root / f"{day[:4]}-{day[4:6]}-{day[6:]}"
    if dashed.is_dir():
        return dashed
    raise FileNotFoundError(f"Raw day directory not found for {day}")


def _read_day(source_root: Path, day: str) -> dict:
    day_dir = _find_day_directory(source_root, day)
    raw_path = day_dir / "kis_vts_websocket_raw.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    digest = hashlib.sha256()
    file_size = 0
    slots: dict[int, dict] = {}
    candidate_frames = 0
    with raw_path.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            file_size += len(raw_line)
            if b'"instrument":"2001"' not in raw_line or b'"tr_id":"H0UPCNT0"' not in raw_line:
                continue
            event = json.loads(raw_line)
            parts = str(event.get("payload", "")).split("|", 3)
            if len(parts) != 4 or parts[1] != "H0UPCNT0":
                continue
            fields = parts[3].split("^")
            if len(fields) < 5 or fields[0] != "2001":
                continue
            second = _to_seconds(fields[1])
            if second < WINDOW_START or second > WINDOW_END:
                continue
            candidate_frames += 1
            sequence = int(event["sequence"])
            row = {
                "second": second,
                "time": fields[1],
                "price": float(fields[2]),
                "day_change": float(fields[4]),
                "sequence": sequence,
                "payload_sha256": event["payload_sha256"],
            }
            previous = slots.get(second)
            if previous is None or sequence > previous["sequence"]:
                slots[second] = row

    if not slots:
        raise ValueError(f"No H0UPCNT0/2001 observations in opening window: {day}")
    ordered = [slots[key] for key in sorted(slots)]
    first = ordered[0]
    gap = float(first["day_change"])
    if gap == 0:
        raise ValueError(f"Zero opening-gap proxy cannot define direction: {day}")
    direction = 1.0 if gap > 0 else -1.0
    first_price = float(first["price"])
    observations = []
    for row in ordered:
        favorable = (float(row["price"]) - first_price) * direction
        observations.append({
            **row,
            "favorable": round(favorable, 6),
            "adverse": round(-favorable, 6),
        })

    expected_slots = WINDOW_END - WINDOW_START + 1
    missing = expected_slots - len(observations)
    if missing < 0:
        raise ValueError(f"More unique seconds than expected for {day}: {len(observations)}")
    return {
        "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "day_key": day,
        "gap_points": gap,
        "gap_abs": abs(gap),
        "gap_direction": "UP" if gap > 0 else "DOWN",
        "gap_regime": "SMALL_LT_5" if abs(gap) < 5 else ("MEDIUM_5_TO_15" if abs(gap) < 15 else "LARGE_GE_15"),
        "first_time": _to_hhmmss(observations[0]["second"]),
        "last_time": _to_hhmmss(observations[-1]["second"]),
        "unique_seconds": len(observations),
        "missing_seconds": missing,
        "complete_window": observations[-1]["second"] == WINDOW_END,
        "raw_candidate_frames": candidate_frames,
        "raw_file_size_bytes": file_size,
        "raw_sha256": digest.hexdigest(),
        "observations": observations,
    }


def _first_advance(observations: list[dict], threshold: float) -> int | None:
    for row in observations:
        if float(row["favorable"]) >= threshold:
            return int(row["second"])
    return None


def _split_counts(rows: list[dict], key: str) -> dict:
    return {
        "all_27": sum(bool(row.get(key)) for row in rows),
        "calibration_18": sum(bool(row.get(key)) for row in rows[:18]),
        "holdout_9": sum(bool(row.get(key)) for row in rows[18:]),
    }


def _candidate_table(rows: list[dict], *, phase: str, advance: float) -> list[dict]:
    result = []
    for magnitude in REVERSAL_CANDIDATES:
        for persistence in PERSISTENCE_CANDIDATES:
            triggered = []
            for row in rows:
                observations = row["observations"]
                advance_second = _first_advance(observations, advance)
                if phase == "PRE_ADVANCE":
                    trigger_second = first_persistent_time(
                        observations, "adverse", magnitude, persistence,
                        before_sec=advance_second,
                    )
                else:
                    if advance_second is None:
                        trigger_second = None
                    else:
                        post = _add_peak_retracement(observations, advance_second)
                        trigger_second = first_persistent_time(
                            post, "retrace", magnitude, persistence,
                            after_sec=advance_second,
                        )
                triggered.append(trigger_second is not None)
            result.append({
                "phase": phase,
                "advance_points": advance,
                "reversal_points": magnitude,
                "persistence_seconds": persistence,
                **{
                    "all_27": sum(triggered),
                    "calibration_18": sum(triggered[:18]),
                    "holdout_9": sum(triggered[18:]),
                },
            })
    return result


def run_analysis(source_root: Path) -> dict:
    rows = [_read_day(source_root, day) for day in DAYS]
    if len(rows) != 27:
        raise AssertionError("Expected 27 chronological sessions")
    if sum(row["gap_direction"] == "UP" for row in rows) != 11:
        raise AssertionError("Gap-up count differs from R8 baseline")
    if sum(row["gap_direction"] == "DOWN" for row in rows) != 16:
        raise AssertionError("Gap-down count differs from R8 baseline")
    if sum(row["missing_seconds"] for row in rows) != 73:
        raise AssertionError("Missing-second count differs from R8 baseline")
    if not all(row["complete_window"] for row in rows):
        raise AssertionError("One or more opening windows do not reach 09:30:00")

    for row in rows:
        observations = row["observations"]
        for advance in ADVANCE_CANDIDATES:
            second = _first_advance(observations, advance)
            row[f"advance_{advance:g}_time"] = _to_hhmmss(second)
        one_point_advance = _first_advance(observations, 1.0)
        row["pre_adverse_0_1pt_1s"] = _to_hhmmss(first_persistent_time(
            observations, "adverse", 0.1, 1, before_sec=one_point_advance
        ))
        row["pre_adverse_0_2pt_1s"] = _to_hhmmss(first_persistent_time(
            observations, "adverse", 0.2, 1, before_sec=one_point_advance
        ))
        row["pre_adverse_1pt_3s"] = _to_hhmmss(first_persistent_time(
            observations, "adverse", 1.0, 3, before_sec=one_point_advance
        ))
        if one_point_advance is None:
            row["post_retrace_1pt_3s"] = None
        else:
            post = _add_peak_retracement(observations, one_point_advance)
            row["post_retrace_1pt_3s"] = _to_hhmmss(first_persistent_time(
                post, "retrace", 1.0, 3, after_sec=one_point_advance
            ))

    baseline_01 = sum(row["pre_adverse_0_1pt_1s"] is not None for row in rows)
    baseline_02 = sum(row["pre_adverse_0_2pt_1s"] is not None for row in rows)
    advance_1 = sum(row["advance_1_time"] is not None for row in rows)
    if (baseline_01, baseline_02, advance_1) != (20, 20, 24):
        raise AssertionError(
            f"R8 baseline mismatch: adverse01={baseline_01}, adverse02={baseline_02}, advance1={advance_1}"
        )

    gap_filter = []
    for threshold in (1.0, 1.5, 2.0, 3.0, 5.0):
        included = [row["gap_abs"] >= threshold for row in rows]
        gap_filter.append({
            "minimum_gap_points": threshold,
            "all_27": sum(included),
            "calibration_18": sum(included[:18]),
            "holdout_9": sum(included[18:]),
        })
    advance_frequency = []
    for threshold in ADVANCE_CANDIDATES:
        included = [row[f"advance_{threshold:g}_time"] is not None for row in rows]
        advance_frequency.append({
            "advance_points": threshold,
            "all_27": sum(included),
            "calibration_18": sum(included[:18]),
            "holdout_9": sum(included[18:]),
        })

    pre_tables = {
        str(advance): _candidate_table(rows, phase="PRE_ADVANCE", advance=advance)
        for advance in (1.0, 2.0)
    }
    post_tables = {
        str(advance): _candidate_table(rows, phase="POST_ADVANCE_RETRACE", advance=advance)
        for advance in (1.0, 2.0)
    }

    regimes = []
    for regime in ("SMALL_LT_5", "MEDIUM_5_TO_15", "LARGE_GE_15"):
        subset = [row for row in rows if row["gap_regime"] == regime]
        regimes.append({
            "regime": regime,
            "sessions": len(subset),
            "advance_1pt": sum(row["advance_1_time"] is not None for row in subset),
            "pre_adverse_1pt_3s": sum(row["pre_adverse_1pt_3s"] is not None for row in subset),
            "post_retrace_1pt_3s": sum(row["post_retrace_1pt_3s"] is not None for row in subset),
        })

    return {
        "analysis_id": "Q25-A8-S5-REVERSAL-PERSISTENCE-20261117",
        "status": "READ_ONLY_OBSERVED_UNDERLYING_ANALYSIS_VALIDATION_ONLY",
        "strategy_policy_reference": "Notion No.1565: gap-up CALL BUY 1 / gap-down PUT BUY 1; adverse pre-advance reversal may add opposite option BUY 1; post-advance reversal is an original-option exit candidate, not a hedge",
        "source": {
            "source_root": str(source_root),
            "tr_id": "H0UPCNT0",
            "instrument": "2001",
            "window_kst": ["09:00:30", "09:30:00"],
            "date_count": len(rows),
            "total_file_bytes": sum(row["raw_file_size_bytes"] for row in rows),
            "total_unique_seconds": sum(row["unique_seconds"] for row in rows),
            "total_missing_seconds": sum(row["missing_seconds"] for row in rows),
            "raw_sha256_by_date": {row["day_key"]: row["raw_sha256"] for row in rows},
        },
        "method": {
            "gap_proxy": "signed H0UPCNT0 payload field[4] on the first available observation in the opening window; not independently certified official auction/open-to-prior-close gap",
            "favorable_move": "(current index price - first observed index price) * sign(gap)",
            "adverse_move": "negative favorable move relative to the first observed index price",
            "persistence": "N consecutive observed one-second slots; any missing second breaks the run; no interpolation",
            "chronological_split": {"calibration": "first 18 sessions", "holdout": "last 9 sessions"},
            "gap_regimes": "exploratory only: abs(gap)<5, 5<=abs(gap)<15, abs(gap)>=15",
            "no_option_pnl": True,
            "no_threshold_approval": True,
        },
        "baseline_reconciliation": {
            "gap_up": 11,
            "gap_down": 16,
            "missing_seconds": 73,
            "advance_1pt": advance_1,
            "adverse_0_1pt_before_advance_1pt": baseline_01,
            "adverse_0_2pt_before_advance_1pt": baseline_02,
        },
        "gap_filter_sensitivity": gap_filter,
        "advance_sensitivity": advance_frequency,
        "pre_advance_reversal_sensitivity": pre_tables,
        "post_advance_retracement_sensitivity": post_tables,
        "gap_regime_sensitivity": regimes,
        "per_session": [
            {key: value for key, value in row.items() if key != "observations"}
            for row in rows
        ],
        "limits": [
            "Underlying-index paths only; no option premium, strike/expiry identity, multiplier, fills, fees, slippage, or account-risk evidence.",
            "The 27-session sample and 9-session holdout are too small for statistical threshold acceptance.",
            "First-observation day-change is a gap proxy, not an independently verified official opening auction/prior-close pair.",
            "Missing seconds break persistence; no synthetic interpolation or future observation is used.",
            "All D2/D3 numeric thresholds remain UNSET/PROVISIONAL; no Production/Live permission is created.",
        ],
    }


def _md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row[key]) for key, _ in columns) + " |"
        for row in rows
    ]
    return "\n".join([head, rule, *body])


def render_report(result: dict) -> str:
    source = result["source"]
    lines = [
        "# Q25 A8 S5 reversal-persistence sensitivity analysis",
        "",
        "- Date: 2026-11-17",
        "- Status: READ-ONLY OBSERVED UNDERLYING ANALYSIS / VALIDATION ONLY",
        "- Source: existing KIS WS Raw, H0UPCNT0 / index 2001",
        f"- Dates: {source['date_count']}; bytes scanned: {source['total_file_bytes']:,}",
        f"- Unique second slots: {source['total_unique_seconds']:,}; missing slots: {source['total_missing_seconds']}",
        "",
        "## 1. Baseline reconciliation",
        "",
        f"- Gap-up/down: {result['baseline_reconciliation']['gap_up']}/{result['baseline_reconciliation']['gap_down']}.",
        f"- Favorable 1.0pt advance: {result['baseline_reconciliation']['advance_1pt']}/27.",
        f"- Adverse 0.1pt / 0.2pt before 1.0pt advance: {result['baseline_reconciliation']['adverse_0_1pt_before_advance_1pt']}/27 and {result['baseline_reconciliation']['adverse_0_2pt_before_advance_1pt']}/27.",
        "- All 27 sessions reconcile to the R8 baseline: 73 missing one-second slots, no interpolated observations, all windows reach 09:30:00.",
        "",
        "## 2. D2 gap-size and advance sensitivity",
        "",
        "These are underlying-index frequencies only; they do not validate option returns.",
        "",
        "### Minimum gap filter",
        "",
        _md_table(result["gap_filter_sensitivity"], [
            ("minimum_gap_points", "Minimum abs gap (pt)"),
            ("all_27", "All 27"),
            ("calibration_18", "First 18"),
            ("holdout_9", "Last 9"),
        ]),
        "",
        "### Favorable advance",
        "",
        _md_table(result["advance_sensitivity"], [
            ("advance_points", "Advance (pt)"),
            ("all_27", "All 27"),
            ("calibration_18", "First 18"),
            ("holdout_9", "Last 9"),
        ]),
        "",
        "## 3. D3 pre-advance adverse reversal candidates",
        "",
        "A candidate is counted only if adverse movement reaches the stated magnitude for N consecutive observed seconds and the confirmation completes strictly before the favorable advance. Missing seconds reset the confirmation streak. This is a candidate for the opposite-option hedge, not an approved trigger.",
        "",
    ]
    for advance, table in result["pre_advance_reversal_sensitivity"].items():
        lines += [
            f"### Before advance {advance}pt",
            "",
            _md_table(table, [
                ("reversal_points", "Adverse move (pt)"),
                ("persistence_seconds", "Persistence (s)"),
                ("all_27", "All 27"),
                ("calibration_18", "First 18"),
                ("holdout_9", "Last 9"),
            ]),
            "",
        ]
    lines += [
        "## 4. Post-advance peak-retracement candidates",
        "",
        "After the favorable advance, retracement is measured from the subsequent favorable peak. These are original-option exit candidates, not opposite-option hedge entries. No option premium or profit-lock calculation is implied.",
        "",
    ]
    for advance, table in result["post_advance_retracement_sensitivity"].items():
        lines += [
            f"### After advance {advance}pt",
            "",
            _md_table(table, [
                ("reversal_points", "Peak retracement (pt)"),
                ("persistence_seconds", "Persistence (s)"),
                ("all_27", "All 27"),
                ("calibration_18", "First 18"),
                ("holdout_9", "Last 9"),
            ]),
            "",
        ]
    lines += [
        "## 5. Exploratory gap-size regimes",
        "",
        _md_table(result["gap_regime_sensitivity"], [
            ("regime", "Gap regime"),
            ("sessions", "Sessions"),
            ("advance_1pt", "Advance 1pt"),
            ("pre_adverse_1pt_3s", "Pre-advance adverse 1pt/3s"),
            ("post_retrace_1pt_3s", "Post-advance retrace 1pt/3s"),
        ]),
        "",
        "Regime boundaries (<5pt, 5–15pt, >=15pt) are exploratory buckets only, not approved operating filters.",
        "",
        "## 6. Decision and limitations",
        "",
        "- Keep the No.1565 policy mapping: gap-up CALL BUY 1 / gap-down PUT BUY 1; opposite option BUY 1 is considered only for an objectively confirmed adverse reversal before the required favorable advance; after advance, manage/close the original option rather than adding the hedge.",
        "- The tables compare candidate magnitude/persistence combinations on a chronological 18-session calibration / 9-session holdout split. The holdout is too small for statistical acceptance; do not select an operating threshold from these counts.",
        "- The gap value is the first available H0UPCNT0 day-change payload field, not an independently certified official opening-auction/prior-close pair.",
        "- No option premium, strike/expiry identity, option multiplier, fills, fees, slippage, account margin, or option PnL was available in this analysis. No profitability claim is made.",
        "- All D2/D3 numeric thresholds remain UNSET/PROVISIONAL. No strategy code, manifest, Risk/OMS, Runtime, production setting, or original source data was changed.",
        "- No new collection, collector/API calls, KIS Live/REAL_VTS/real-account/order API calls, or Project200 merge.",
        "",
        "## 7. Source SHA-256 by date",
        "",
        _md_table([
            {"date": day, "sha256": value}
            for day, value in source["raw_sha256_by_date"].items()
        ], [("date", "Date"), ("sha256", "Raw SHA-256")]),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=Path("reports/synth"))
    args = parser.parse_args()
    result = run_analysis(args.source_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    json_path = args.output_root / "Q25_A8_S5_REVERSAL_PERSISTENCE_20261117.json"
    md_path = args.output_root / "Q25_A8_S5_REVERSAL_PERSISTENCE_20261117.md"
    json_bytes = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    json_path.write_bytes(json_bytes)
    json_hash = hashlib.sha256(json_bytes).hexdigest()
    json_path.with_suffix(json_path.suffix + ".sha256").write_text(json_hash + "\n", encoding="ascii")
    report = render_report(result)
    md_path.write_text(report, encoding="utf-8")
    print(f"JSON={json_path}")
    print(f"JSON_SHA256={json_hash}")
    print(f"REPORT={md_path}")
    print(f"SESSIONS={len(result['per_session'])} MISSING={result['source']['total_missing_seconds']}")
    print("BASELINE=" + json.dumps(result["baseline_reconciliation"], sort_keys=True))
    print("GAP_FILTER=" + json.dumps(result["gap_filter_sensitivity"], sort_keys=True))
    print("ADVANCE=" + json.dumps(result["advance_sensitivity"], sort_keys=True))
    print("REGIMES=" + json.dumps(result["gap_regime_sensitivity"], sort_keys=True))


if __name__ == "__main__":
    main()
