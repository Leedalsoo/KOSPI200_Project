from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_market_transport import KISFuturesMarketTransport
from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
from infrastructure.kis.kis_vts_collection_diagnostic import diagnose_collection, write_human_report, write_report
from infrastructure.kis.kis_weekday_collection_plan import (
    CollectionPlan,
    CollectionWindow,
    build_collection_plan,
    is_collection_day,
    should_stop,
)
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore


KST = timezone(timedelta(hours=9))
LOGGER = logging.getLogger("kis_vts_weekday_collector")

WINDOW = CollectionWindow(start=date(2026, 9, 21), end=date(2026, 9, 23))
SESSION_START = time(8, 30)
SESSION_END = time(16, 0)
ALERT_CHECK_TIME = time(9, 10)
HEARTBEAT_INTERVAL_SECONDS = 60
RESTART_BACKOFF_INITIAL_SECONDS = 2
RESTART_BACKOFF_MAX_SECONDS = 60
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "kis_realtime"
LOG_PATH = DATA_ROOT / "collector.log"


def _now_kst() -> datetime:
    return datetime.now(KST)


def _next_backoff(current: int) -> int:
    return min(current * 2, RESTART_BACKOFF_MAX_SECONDS)


def configure_logging() -> logging.Logger:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    for handler in list(LOGGER.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            LOGGER.removeHandler(handler)
            handler.close()
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    return LOGGER


def _latest_krx_spot_price() -> str:
    candidates = sorted((ROOT / "data" / "historical" / "krx_raw").glob("*_futures_daily.json"))
    if not candidates:
        raise RuntimeError("AUTHORITATIVE_KRX_FUTURES_DAILY_SOURCE_REQUIRED")
    path = candidates[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("OutBlock_1", [])
    matches = [row for row in rows if row.get("ISU_CD") == "A016C000" and row.get("SPOT_PRC")]
    if not matches:
        raise RuntimeError("AUTHORITATIVE_KOSPI200_SPOT_PRICE_REQUIRED")
    return str(matches[-1]["SPOT_PRC"])


def build_plan() -> CollectionPlan:
    reference_price = _latest_krx_spot_price()
    return build_collection_plan(
        reference_price=Decimal(reference_price),
        option_master_paths=(ROOT / "data_2801_20260919.xlsx",),
        weekly_master_paths=(ROOT / "data_2923_20260919.xlsx", ROOT / "data_2935_20260919.xlsx"),
        standard_futures_symbol="A01609",
        mini_futures_symbol="A05609",
        as_of=WINDOW.start,
    )


def write_daily_collection_diagnostic(day: date, plan: CollectionPlan) -> dict[str, Path]:
    raw_path = _raw_store_for(day).path
    report = diagnose_collection(raw_path, LOG_PATH, plan)
    json_path = DATA_ROOT / day.isoformat() / "collection_report.json"
    text_path = DATA_ROOT / day.isoformat() / "collection_report.txt"
    write_report(report, json_path)
    write_human_report(report, text_path)
    LOGGER.info(
        "COLLECTION_DIAGNOSTIC date=%s overall=%s missing=%d reconnects=%d errors=%d hash=%s",
        day.isoformat(), report.overall, len(report.missing_contracts), report.reconnect_count,
        report.error_frames, report.hash_validation,
    )
    return {"json": json_path, "text": text_path}


def _raw_store_for(day: date) -> KISRealtimeRawStore:
    return KISRealtimeRawStore(DATA_ROOT / day.isoformat() / "kis_vts_raw.jsonl")


def _write_option_alert(day: date, data_root: Path, tr_counts: Counter[str] | dict[str, int]) -> Path:
    day_dir = data_root / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "ALERT_NO_OPTION_FRAMES.txt"
    path.write_text(
        "KIS VTS 조기 경보\n"
        f"date={day.isoformat()}\n"
        "원인 후보: 옵션 TR(H0IOCNT0) 미수신, KIS VTS 옵션 실시간 데이터 미지원/지연, 구독·인증·네트워크 문제.\n"
        "다음 조치: 수집을 중단하지 않고 계속 수집하며, 일 마감 진단에서 실제 수신 TR/종목 및 원본 해시를 확인한다.\n"
        f"TR_COUNTS={dict(sorted(tr_counts.items()))}\n",
        encoding="utf-8",
    )
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_day(day: date, day_dir: Path, *, source_root: Path) -> bool:
    configured = os.environ.get("PROJECT200_BACKUP_DIR", "").strip()
    if not configured:
        LOGGER.warning("BACKUP_SKIPPED reason=PROJECT200_BACKUP_DIR_UNSET date=%s", day.isoformat())
        return False
    if not day_dir.exists():
        raise FileNotFoundError(day_dir)
    backup_root = Path(configured).expanduser().resolve()
    source = day_dir.resolve()
    if backup_root == source or source.is_relative_to(backup_root):
        raise ValueError("BACKUP_DESTINATION_MUST_NOT_CONTAIN_SOURCE")
    destination = backup_root / day.isoformat()
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for src in source.rglob("*"):
        if src.is_file():
            rel = src.relative_to(source)
            dst = destination / rel
            if not dst.exists() or _sha256_file(src) != _sha256_file(dst):
                raise ValueError(f"BACKUP_SHA256_MISMATCH:{rel}")
    LOGGER.info("BACKUP_VERIFIED date=%s destination=%s", day.isoformat(), destination)
    return True


def _safe_write_daily_diagnostics(day: date, plan: CollectionPlan) -> None:
    try:
        store = _raw_store_for(day)
        manifest = store.write_manifest(
            source="KIS_VTS_WEBSOCKET_RAW",
            endpoint="ws://ops.koreainvestment.com:31000",
            tolerate_truncated_tail=True,
        )
        LOGGER.info("DAY_FINISHED date=%s record_count=%d file_sha256=%s", day.isoformat(), manifest["record_count"], manifest["file_sha256"])
    except Exception as exc:
        LOGGER.error("MANIFEST_WRITE_ERROR date=%s error=%s", day.isoformat(), exc, exc_info=True)
    try:
        paths = write_daily_collection_diagnostic(day, plan)
        LOGGER.info("COLLECTION_REPORT_WRITTEN date=%s json=%s text=%s", day.isoformat(), paths["json"], paths["text"])
    except Exception as exc:
        LOGGER.error("COLLECTION_DIAGNOSTIC_ERROR date=%s error=%s", day.isoformat(), exc, exc_info=True)
    try:
        _backup_day(day, DATA_ROOT / day.isoformat(), source_root=DATA_ROOT)
    except Exception as exc:
        LOGGER.error("BACKUP_ERROR date=%s error=%s", day.isoformat(), exc, exc_info=True)


async def _collect_day(day: date, plan: CollectionPlan) -> None:
    auth = KISAuthManager.from_env(
        is_vts=True,
        env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    if not auth.has_credentials():
        raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")

    store = _raw_store_for(day)
    transport = KISFuturesMarketTransport(auth)
    collector = KISRealtimeCollector(transport, store, max_reconnects=1)

    await collector.start(day.isoformat(), plan.subscriptions)
    LOGGER.info(
        "DAY_STARTED date=%s subscriptions=%d monthly_expiry=%s weekly_expiry=%s monthly_strikes=%s weekly_strikes=%s",
        day.isoformat(), len(plan.subscriptions), plan.monthly_expiry, plan.weekly_expiry,
        plan.monthly_strikes, plan.weekly_strikes,
    )

    tr_counts: Counter[str] = Counter()
    received_count = 0
    last_received_at: str | None = None
    session_started_at = _now_kst()
    last_heartbeat_at = session_started_at
    alert_checked = False
    try:
        while True:
            now = _now_kst()
            if now.date() != day or now.time() >= SESSION_END:
                break
            if now.time() < SESSION_START:
                await asyncio.sleep(5)
                continue

            if not alert_checked and now.time() >= ALERT_CHECK_TIME:
                alert_checked = True
                if tr_counts.get("H0IOCNT0", 0) == 0:
                    LOGGER.warning("ALERT_NO_OPTION_FRAMES date=%s", day.isoformat())
                    _write_option_alert(day, DATA_ROOT, tr_counts)

            if (now - last_heartbeat_at).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS:
                LOGGER.info(
                    "HEARTBEAT date=%s received_count=%d tr_counts=%s last_received_at=%s",
                    day.isoformat(), received_count, dict(sorted(tr_counts.items())), last_received_at,
                )
                last_heartbeat_at = now

            try:
                record = await asyncio.wait_for(collector.capture_one(), timeout=5.0)
                received_count += 1
                tr_counts[str(record["tr_id"])] += 1
                last_received_at = str(record["received_at"])
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                LOGGER.exception("RECEIVE_ERROR date=%s error=%s", day.isoformat(), exc)
                await collector.close()
                await asyncio.sleep(2)
                if _now_kst().date() != day:
                    break
                await collector.start(day.isoformat(), plan.subscriptions)
    finally:
        await collector.close()

    _safe_write_daily_diagnostics(day, plan)


async def run() -> None:
    configure_logging()
    LOGGER.info("COLLECTOR_PROCESS_STARTED window=%s..%s", WINDOW.start, WINDOW.end)
    plan = build_plan()
    LOGGER.info("COLLECTION_PLAN_READY subscriptions=%d", len(plan.subscriptions))
    restart_backoff = RESTART_BACKOFF_INITIAL_SECONDS

    while True:
        now = _now_kst()
        if should_stop(now.isoformat(), WINDOW):
            LOGGER.info("COLLECTOR_AUTO_STOP reached=%s", now.isoformat())
            return

        if is_collection_day(now.date(), WINDOW):
            if SESSION_START <= now.time() < SESSION_END:
                try:
                    await _collect_day(now.date(), plan)
                    restart_backoff = RESTART_BACKOFF_INITIAL_SECONDS
                except Exception as exc:
                    LOGGER.exception("COLLECTION_SESSION_ERROR date=%s error=%s", now.date().isoformat(), exc)
                    await asyncio.sleep(restart_backoff)
                    restart_backoff = _next_backoff(restart_backoff)
            else:
                await asyncio.sleep(10)
        else:
            await asyncio.sleep(30)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
