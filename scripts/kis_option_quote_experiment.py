from __future__ import annotations
"""KST scheduled KIS option-quote experiment. Default mode is strictly offline."""
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, date, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "verification" / "evidence"
EXPIRY_EVIDENCE = EVIDENCE / "kis_expiry_crosscheck_20261014.json"
MASTER_EVIDENCE = EVIDENCE / "kis_master_identity_join_20261014.json"
SUBSCRIPTION_EVIDENCE = EVIDENCE / "kis_subscription_plan_dry_run_v2_20261014.json"

# Editable KST schedule constants
PREFLIGHT_AFTER = dtime(8, 30)
SUBSCRIBE_AT = dtime(8, 55)
REGULAR_START = dtime(9, 0)
REST_QUOTE_AT = dtime(9, 10)
DEFAULT_END = dtime(9, 15)
MIN_OBSERVATION_MINUTES = 10
MAX_OBSERVATION_MINUTES = 30
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
MAX_SUBSCRIPTIONS = 41
BASE_SUBSCRIPTIONS_EXPECTED = 29
USER_CONFIRMED_TRADING_DATE = "2026-10-15"

CANDIDATE_TARGETS = (
    {"side": "CALL", "strike": "1057.5", "channels": ("H0IOCNT0", "H0IOASP0")},
    {"side": "CALL", "strike": "1060.0", "channels": ("H0IOCNT0", "H0IOASP0")},
    {"side": "PUT", "strike": "1032.5", "channels": ("H0IOCNT0", "H0IOASP0")},
    {"side": "PUT", "strike": "1030.0", "channels": ("H0IOCNT0", "H0IOASP0")},
)
ATM_TARGETS = (
    {"side": "CALL", "strike": "ATM_FROM_APPROVED_REFERENCE", "channels": ("H0IOASP0",)},
    {"side": "PUT", "strike": "ATM_FROM_APPROVED_REFERENCE", "channels": ("H0IOASP0",)},
)


def now_kst() -> datetime:
    return datetime.now(KST)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create guarantees that this script never overwrites evidence.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def schedule_rows(day: date, observation_minutes: int) -> list[dict]:
    end_dt = datetime.combine(day, REGULAR_START, KST) + timedelta(minutes=observation_minutes)
    return [
        {"at_kst": f"{day.isoformat()} 08:30+", "stage": "A", "action": "read-only process/session/subscription check and cached exact-expiry evidence review"},
        {"at_kst": f"{day.isoformat()} 08:55", "stage": "B-1", "action": "subscribe only if all execute gates pass; frames labelled PREOPEN"},
        {"at_kst": f"{day.isoformat()} 09:00", "stage": "B-2", "action": f"observe regular session for {observation_minutes} minutes; PREOPEN excluded from freshness"},
        {"at_kst": f"{day.isoformat()} 09:10", "stage": "REST", "action": "at most one REST quote request per resolved instrument; stop on EGW00201"},
        {"at_kst": end_dt.strftime("%Y-%m-%d %H:%M"), "stage": "C", "action": "unsubscribe, record ACK, verify the original 29 subscriptions restored"},
        {"at_kst": "immediately after C", "stage": "REPORT", "action": "write JSON and Markdown findings"},
    ]


def candidate_plan() -> list[dict]:
    plan = []
    for item in CANDIDATE_TARGETS + ATM_TARGETS:
        for tr_id in item["channels"]:
            plan.append({
                "tr_id": tr_id, "side": item["side"], "strike": item["strike"],
                "expiry": "20261015", "symbol": None,
                "identity_status": "UNRESOLVED_NO_PER_SYMBOL_EXACT_EXPIRY_EVIDENCE",
            })
    return plan


def inspect_evidence() -> dict:
    result = {
        "expiry_evidence": str(EXPIRY_EVIDENCE.relative_to(ROOT)),
        "master_evidence": str(MASTER_EVIDENCE.relative_to(ROOT)),
        "subscription_evidence": str(SUBSCRIPTION_EVIDENCE.relative_to(ROOT)),
        "expiry_file_sha256": None, "master_file_sha256": None,
        "subscription_file_sha256": None, "exact_expiry_for_requested_strikes": False,
        "expiry_candidate_symbols": [], "errors": [],
    }
    for path, key in (
        (EXPIRY_EVIDENCE, "expiry_file_sha256"),
        (MASTER_EVIDENCE, "master_evidence_file_sha256"),
        (SUBSCRIPTION_EVIDENCE, "subscription_file_sha256"),
    ):
        if not path.is_file():
            result["errors"].append("MISSING_EVIDENCE:" + path.name)
        else:
            result[key] = digest(path)
    if MASTER_EVIDENCE.is_file():
        master_data = json.loads(MASTER_EVIDENCE.read_text(encoding="utf-8-sig"))
        result["master_archive"] = master_data.get("master_archive")
        result["master_archive_sha256"] = master_data.get("master_sha256")
    if EXPIRY_EVIDENCE.is_file():
        data = json.loads(EXPIRY_EVIDENCE.read_text(encoding="utf-8-sig"))
        result["expiry_evidence_generated_at"] = data.get("generated_at")
        result["cached_exact_expiry_records_joined"] = data.get("cached_exact_expiry_records_joined")
        rows = data.get("weekly_label_weekday_comparison", [])
        observed = {(r.get("series"), r.get("expiry"), r.get("strike")) for r in rows}
        required = {("THURSDAY_WEEKLY", "2026-10-15", strike) for strike in ("1030.00", "1032.50", "1057.50", "1060.00")}
        result["exact_expiry_for_requested_strikes"] = required.issubset(observed)
        result["expiry_candidate_symbols"] = [
            r.get("symbol") for r in rows
            if r.get("series") == "THURSDAY_WEEKLY" and r.get("expiry") == "2026-10-15"
        ]
        result["evidence_note"] = "Cached evidence contains summary rows, not exact per-symbol mappings for all requested strikes."
    return result


def find_active_collectors() -> list[str]:
    # Read-only process inspection. Never terminate or modify a process.
    command = [
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -notmatch '^powershell.exe$' -and "
        "$_.CommandLine -match 'kis_vts_websocket_collector|kis_vts_weekday_collector|kis_vts_websocket_orderbook_collector' "
        "} | ForEach-Object { \"$($_.ProcessId):$($_.Name)\" }",
    ]
    try:
        cp = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        return [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    except Exception as exc:
        return ["PROCESS_CHECK_FAILED:" + type(exc).__name__]


def validate_schedule(observation_minutes: int, current: datetime) -> list[str]:
    errors = []
    if not MIN_OBSERVATION_MINUTES <= observation_minutes <= MAX_OBSERVATION_MINUTES:
        errors.append("OBSERVATION_MINUTES_OUT_OF_RANGE_10_TO_30")
    # B-1 at 08:55 is the explicitly requested PREOPEN subscription phase;
    # the regular observation phase B-2 must start within market hours.
    if not (MARKET_OPEN <= REGULAR_START < MARKET_CLOSE and MARKET_OPEN <= DEFAULT_END <= MARKET_CLOSE):
        errors.append("B2_STAGE_TIME_OUTSIDE_MARKET_HOURS")
    if current.date().isoformat() != USER_CONFIRMED_TRADING_DATE:
        errors.append("TRADING_DAY_NOT_CONFIRMED_FOR_CURRENT_DATE")
    if current.weekday() >= 5:
        errors.append("NON_BUSINESS_WEEKDAY")
    return errors


def markdown_report(data: dict) -> str:
    lines = [
        "# KIS 옵션 호가 통제 실험 — 예약 실행 계획", "",
        f"- 생성 KST: {data['generated_at_kst']}",
        f"- 모드: {data['mode']}",
        f"- 구독 상한: {data['subscription_limit']}",
        f"- 기존 구독 예상: {data['expected_base_subscription_count']}",
        f"- 후보 추가 수(심볼 미확정 포함): {len(data['candidate_subscription_plan'])}",
        f"- 이론상 합계: {data['theoretical_total_if_all_symbols_verified']}",
        f"- 상한 이내: {data['theoretical_total_within_limit']}", "",
        "## 일정", "", "| KST | 단계 | 작업 |", "|---|---|---|",
    ]
    for row in data["schedule"]:
        lines.append(f"| {row['at_kst']} | {row['stage']} | {row['action']} |")
    lines += ["", "## 후보 구독 목록 (심볼 미확정 — 실행 불가)", "",
              "| TR ID | 권리 | 행사가 | 만기 | 심볼 | 상태 |", "|---|---|---:|---|---|---|"]
    for item in data["candidate_subscription_plan"]:
        lines.append(f"| {item['tr_id']} | {item['side']} | {item['strike']} | {item['expiry']} | UNKNOWN | {item['identity_status']} |")
    lines += ["", "## 실행 차단 사유", ""]
    lines += ["- " + error for error in data["execute_blockers"]] or ["- 없음"]
    lines += ["", "## 시각 의미", "",
              "UNKNOWN unless independently proven. 수신시각을 원천시각으로 대체하지 않는다.",
              "WS/REST 차이는 임계값 제안 없이 관측 분포만 기록한다.", ""]
    return "\n".join(lines)


def run_with_args() -> int:
    parser = argparse.ArgumentParser(description="KST scheduled option quote experiment; default is offline dry-run")
    parser.add_argument("--execute", action="store_true", help="request the experiment; safety gates remain mandatory")
    parser.add_argument("--now-offset", type=int, default=0, help="dry-run simulated minutes from current KST")
    parser.add_argument("--observation-minutes", type=int, default=15)
    args = parser.parse_args()
    system_now = now_kst()
    simulated_now = system_now + timedelta(minutes=args.now_offset)
    print("SYSTEM_TIME_KST=" + system_now.isoformat())
    print("MODE=" + ("EXECUTE_REQUEST" if args.execute else "DRY_RUN"))
    evidence = inspect_evidence()
    active = find_active_collectors()
    plan = candidate_plan()
    blockers = validate_schedule(args.observation_minutes, simulated_now)
    blockers.extend(evidence["errors"])
    if not evidence["exact_expiry_for_requested_strikes"]:
        blockers.append("EXACT_EXPIRY_NOT_PROVEN_FOR_ALL_REQUESTED_STRIKES")
    if active:
        blockers.append("ACTIVE_COLLECTOR_PRESENT_OR_PROCESS_CHECK_UNCERTAIN")
    if BASE_SUBSCRIPTIONS_EXPECTED + len(plan) > MAX_SUBSCRIPTIONS:
        blockers.append("SUBSCRIPTION_CAP_EXCEEDED")
    # Actual transport is intentionally not enabled until identities and single-session
    # unsubscribe/ACK/base-restoration semantics can be proven from the approved evidence.
    if args.execute:
        blockers.append("EXECUTION_ADAPTER_NOT_ENABLED_UNTIL_IDENTITY_AND_SESSION_LIFECYCLE_ARE_PROVEN")
    data = {
        "schema_version": "kis-option-quote-experiment-controller-v1",
        "generated_at_kst": system_now.isoformat(),
        "mode": "DRY_RUN" if not args.execute else "EXECUTE_REQUEST_BLOCKED_OR_GATED",
        "system_time_kst": system_now.isoformat(),
        "simulated_time_kst": simulated_now.isoformat(),
        "schedule": schedule_rows(simulated_now.date(), args.observation_minutes),
        "subscription_limit": MAX_SUBSCRIPTIONS,
        "expected_base_subscription_count": BASE_SUBSCRIPTIONS_EXPECTED,
        "candidate_subscription_plan": plan,
        "theoretical_total_if_all_symbols_verified": BASE_SUBSCRIPTIONS_EXPECTED + len(plan),
        "theoretical_total_within_limit": BASE_SUBSCRIPTIONS_EXPECTED + len(plan) <= MAX_SUBSCRIPTIONS,
        "evidence": evidence,
        "active_collector_processes": active,
        "execute_blockers": sorted(set(blockers)),
        "rest_policy": {"at_kst": "09:10", "max_calls_per_instrument": 1, "stop_on": "EGW00201"},
        "time_semantics": "UNKNOWN unless independently proven; receive timestamp is never substituted for source time",
        "safety": {
            "network_called_by_this_run": False, "websocket_opened": False,
            "orders_accounts_balance_margin_apis_imported": False,
            "existing_files_modified": False, "subscription_count_hard_cap_enforced": True,
            "secret_values_emitted": False,
        },
    }
    stamp = system_now.strftime("%Y%m%dT%H%M%S")
    json_path = EVIDENCE / f"kis_option_quote_experiment_plan_{stamp}.json"
    md_path = EVIDENCE / f"kis_option_quote_experiment_plan_{stamp}.md"
    unique_write(json_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    unique_write(md_path, markdown_report(data) + "\n")
    print("PLAN_JSON=" + str(json_path.relative_to(ROOT)))
    print("PLAN_MD=" + str(md_path.relative_to(ROOT)))
    print("MASTER_ARCHIVE_SHA256=" + str(evidence.get("master_archive_sha256")))
    print(f"THEORETICAL_SUBSCRIPTIONS={data['theoretical_total_if_all_symbols_verified']}/{MAX_SUBSCRIPTIONS}")
    for row in data["schedule"]:
        print(f"{row['at_kst']} [{row['stage']}] {row['action']}")
    for item in plan:
        print(f"  {item['tr_id']} {item['side']} strike={item['strike']} expiry={item['expiry']} symbol=UNKNOWN")
    if data["execute_blockers"]:
        print("EXECUTION_BLOCKED=" + ";".join(data["execute_blockers"]))
    else:
        print("PREFLIGHT_CLEAR")
    print("PLAN_JSON_SHA256=" + digest(json_path))
    print("PLAN_MD_SHA256=" + digest(md_path))
    return 2 if args.execute and data["execute_blockers"] else 0


def main() -> int:
    # One-process lock is created only in the approved evidence directory.
    lock_path = EVIDENCE / "kis_option_quote_experiment.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("EXECUTION_BLOCKED=ANOTHER_EXPERIMENT_SCRIPT_INSTANCE_HOLDS_LOCK")
        return 4
    try:
        os.write(lock_fd, f"pid={os.getpid()} started={now_kst().isoformat()}\n".encode("utf-8"))
        os.close(lock_fd)
        lock_fd = -1
        return run_with_args()
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
