from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

import websockets

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_market_transport import KISWebSocketApprovalKeyProvider
from infrastructure.kis.kis_weekday_collection_plan import FUTURES_TRADE_TR_ID, STRATEGY_MONTHLY_OFFSETS
from infrastructure.kis.kis_vts_weekday_collector import market_data_root_from_env
from infrastructure.kis.kis_index_option_master_source import current_kospi200_futures_symbols, current_monthly_option_symbols
from infrastructure.kis.index_price_source import KISKOSPI200IndexPriceSource
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
SESSION_START = dtime(8, 29)
SESSION_END = dtime(16, 1)
HEARTBEAT_SECONDS = 1.0
SUBSCRIBE_INTERVAL_SECONDS = 0.12
RECONNECT_BACKOFF_SECONDS = 5.0
MAX_SUBSCRIPTIONS = 41
LOG_PATH = market_data_root_from_env() / "logs" / "websocket_collector.log"
LOGGER = logging.getLogger("kis_vts_websocket_collector")


def now_kst() -> datetime:
    return datetime.now(KST)


def configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    if LOGGER.handlers:
        return
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(console)


def build_subscriptions(day: date) -> tuple[tuple[str, str], ...]:
    """Build raw KIS realtime subscriptions from the KIS instrument master.

    KIS is the broker-symbol source at the raw WebSocket boundary. KRX contract
    identity reconciliation remains downstream and does not block frame capture.
    """
    reference_price = KISKOSPI200IndexPriceSource(KISAuthManager.from_env(is_vts=True)).refresh().price
    subscriptions = list(current_monthly_option_symbols(day, reference_price, STRATEGY_MONTHLY_OFFSETS))
    for _, futures_symbol in current_kospi200_futures_symbols(day):
        subscriptions.append((FUTURES_TRADE_TR_ID, futures_symbol))
    subscriptions.append(("H0UPCNT0", "2001"))
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")
    return tuple(subscriptions)

def _approval_key(auth: KISAuthManager) -> str:
    provider = KISWebSocketApprovalKeyProvider(auth, timeout=10.0)
    return provider.issue()


def _message(approval_key: str, tr_id: str, symbol: str) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "1",
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
    })


def _is_control_frame(payload: str) -> bool:
    text = payload.strip()
    if not text.startswith("{"):
        return False
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(message, dict) and (
        isinstance(message.get("header"), dict)
        or isinstance(message.get("body"), dict)
    )


def _frame_identity(payload: str) -> tuple[str, str] | None:
    parts = payload.split("|")
    if len(parts) < 4 or parts[0].strip() not in {"0", "1"}:
        return None
    tr_id = parts[1].strip()
    if not tr_id:
        return None
    symbol = parts[3].split("^", 1)[0].strip()
    if not symbol:
        return None
    return tr_id, symbol


async def _subscribe_all(ws, approval_key: str, subscriptions: tuple[tuple[str, str], ...]) -> None:
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")
    for index, (tr_id, symbol) in enumerate(subscriptions, 1):
        await ws.send(_message(approval_key, tr_id, symbol))
        if index < len(subscriptions):
            await asyncio.sleep(SUBSCRIBE_INTERVAL_SECONDS)


async def collect_day(day: date, *, market_data_root: Path) -> None:
    auth = KISAuthManager.from_env(
        is_vts=True,
        env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    if not auth.has_credentials():
        raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")

    subscriptions = build_subscriptions(day)
    day_dir = market_data_root / day.isoformat()
    raw_store = KISRealtimeRawStore(day_dir / "kis_vts_websocket_raw.jsonl")
    sequence = raw_store.count()
    ws_url = "ws://ops.koreainvestment.com:31000"

    LOGGER.info("WS_DAY_START date=%s subscriptions=%d raw=%s", day, len(subscriptions), raw_store.path)

    while True:
        now = now_kst()
        if now.date() != day or now.time() >= SESSION_END:
            break
        if now.time() < SESSION_START:
            await asyncio.sleep(1)
            continue

        try:
            # One persistent WebSocket session for the whole collection window.
            approval_key = _approval_key(auth)
            async with websockets.connect(ws_url, proxy=None, ping_interval=20, ping_timeout=20, open_timeout=10) as ws:
                await _subscribe_all(ws, approval_key, subscriptions)
                LOGGER.info("WS_CONNECTED date=%s subscriptions=%d", day, len(subscriptions))
                last_heartbeat = time.monotonic()

                while True:
                    now = now_kst()
                    if now.date() != day or now.time() >= SESSION_END:
                        break

                    try:
                        payload = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        payload = None

                    if payload is not None:
                        if isinstance(payload, bytes):
                            payload = payload.decode("utf-8")
                        payload = str(payload)
                        if not _is_control_frame(payload):
                            identity = _frame_identity(payload)
                            if identity is None:
                                LOGGER.warning("WS_FRAME_UNPARSEABLE prefix=%r", payload[:160])
                            else:
                                tr_id, symbol = identity
                                sequence += 1
                                raw_store.append(
                                    received_at=datetime.now(timezone.utc),
                                    trading_date=day.isoformat(),
                                    instrument=symbol,
                                    tr_id=tr_id,
                                    payload=payload,
                                    sequence=sequence,
                                )

                    if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                        LOGGER.info("WS_HEARTBEAT date=%s raw_count=%d", day, raw_store.count())
                        last_heartbeat = time.monotonic()

                LOGGER.info("WS_SESSION_END date=%s raw_count=%d", day, raw_store.count())
                break
        except Exception as exc:
            LOGGER.exception("WS_SESSION_ERROR date=%s error=%s", day, exc)
            await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)

    if raw_store.path.exists():
        raw_store.write_manifest(
            source="KIS_VTS_WEBSOCKET_RAW",
            endpoint=ws_url,
            tolerate_truncated_tail=True,
        )
    LOGGER.info("WS_DAY_END date=%s raw_count=%d", day, raw_store.count())


async def run_forever() -> None:
    market_data_root = market_data_root_from_env()
    active_day: date | None = None
    while True:
        now = now_kst()
        if active_day != now.date():
            active_day = now.date()
            LOGGER.info("WS_WATCH_DAY date=%s", active_day)
        if now.time() < SESSION_START:
            await asyncio.sleep(1)
            continue
        if now.time() >= SESSION_END:
            await asyncio.sleep(30)
            if now.date() != active_day:
                continue
            continue
        try:
            await collect_day(active_day, market_data_root=market_data_root)
        except Exception as exc:
            LOGGER.exception("WS_DAY_FATAL date=%s error=%s", active_day, exc)
            await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
        await asyncio.sleep(1)


def preflight() -> int:
    configure_logging()
    auth = KISAuthManager.from_env(
        is_vts=True,
        env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    if not auth.has_credentials():
        print("KIS_VTS_CREDENTIALS_REQUIRED")
        return 2
    day = now_kst().date()
    try:
        subscriptions = build_subscriptions(day)
    except Exception as exc:
        print(f"PLAN_BLOCKED:{type(exc).__name__}:{exc}")
        return 3
    print(f"WS_PREFLIGHT_OK date={day} subscriptions={len(subscriptions)} limit={MAX_SUBSCRIPTIONS}")
    for tr_id, symbol in subscriptions:
        print(f"  {tr_id} {symbol}")
    print(f"raw_root={market_data_root_from_env()}")
    print(f"session={SESSION_START.isoformat()}-{SESSION_END.isoformat()} KST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    configure_logging()
    if args.preflight:
        return preflight()
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
