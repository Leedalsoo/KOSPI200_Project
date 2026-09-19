from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_market_transport import KISFuturesMarketTransport
from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
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

WINDOW = CollectionWindow(
    start=date(2026, 9, 21),
    end=date(2026, 9, 23),
)
SESSION_START = time(8, 30)
SESSION_END = time(16, 0)

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "kis_realtime"
LOG_PATH = DATA_ROOT / "collector.log"


def configure_logging() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def _latest_krx_spot_price() -> str:
    candidates = sorted(
        (ROOT / "data" / "historical" / "krx_raw").glob("*_futures_daily.json")
    )
    if not candidates:
        raise RuntimeError("AUTHORITATIVE_KRX_FUTURES_DAILY_SOURCE_REQUIRED")
    path = candidates[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("OutBlock_1", [])
    matches = [
        row for row in rows
        if row.get("ISU_CD") == "A016C000"
        and row.get("SPOT_PRC")
    ]
    if not matches:
        raise RuntimeError("AUTHORITATIVE_KOSPI200_SPOT_PRICE_REQUIRED")
    return str(matches[-1]["SPOT_PRC"])


def build_plan() -> CollectionPlan:
    reference_price = _latest_krx_spot_price()
    return build_collection_plan(
        reference_price=Decimal(reference_price),
        option_master_paths=(ROOT / "data_2801_20260919.xlsx",),
        weekly_master_paths=(
            ROOT / "data_2923_20260919.xlsx",
            ROOT / "data_2935_20260919.xlsx",
        ),
        standard_futures_symbol="A01609",
        mini_futures_symbol="A05609",
        as_of=WINDOW.start,
    )


def _raw_store_for(day: date) -> KISRealtimeRawStore:
    return KISRealtimeRawStore(
        DATA_ROOT / day.isoformat() / "kis_vts_raw.jsonl"
    )


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
    collector = KISRealtimeCollector(
        transport,
        store,
        max_reconnects=1,
    )

    await collector.start(
        day.isoformat(),
        plan.subscriptions,
    )
    LOGGER.info(
        "DAY_STARTED date=%s subscriptions=%d monthly_expiry=%s weekly_expiry=%s monthly_strikes=%s weekly_strikes=%s",
        day.isoformat(),
        len(plan.subscriptions),
        plan.monthly_expiry,
        plan.weekly_expiry,
        plan.monthly_strikes,
        plan.weekly_strikes,
    )

    try:
        while True:
            now = datetime.now(KST)
            if now.date() != day or now.time() >= SESSION_END:
                break
            if now.time() < SESSION_START:
                await asyncio.sleep(5)
                continue

            try:
                await asyncio.wait_for(collector.capture_one(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                LOGGER.exception("RECEIVE_ERROR date=%s error=%s", day.isoformat(), exc)
                await collector.close()
                await asyncio.sleep(2)
                if datetime.now(KST).date() != day:
                    break
                await collector.start(day.isoformat(), plan.subscriptions)
    finally:
        await collector.close()

    manifest = store.write_manifest(
        source="KIS_VTS_WEBSOCKET_RAW",
        endpoint="ws://ops.koreainvestment.com:31000",
    )
    LOGGER.info(
        "DAY_FINISHED date=%s record_count=%d file_sha256=%s",
        day.isoformat(),
        manifest["record_count"],
        manifest["file_sha256"],
    )


async def run() -> None:
    configure_logging()
    LOGGER.info("COLLECTOR_PROCESS_STARTED window=%s..%s", WINDOW.start, WINDOW.end)
    plan = build_plan()
    LOGGER.info("COLLECTION_PLAN_READY subscriptions=%d", len(plan.subscriptions))

    while True:
        now = datetime.now(KST)
        if should_stop(now.isoformat(), WINDOW):
            LOGGER.info("COLLECTOR_AUTO_STOP reached=%s", now.isoformat())
            return

        if is_collection_day(now.date(), WINDOW):
            if SESSION_START <= now.time() < SESSION_END:
                await _collect_day(now.date(), plan)
            else:
                await asyncio.sleep(10)
        else:
            await asyncio.sleep(30)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
