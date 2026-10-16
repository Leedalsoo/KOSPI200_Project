from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from infrastructure.kis.collector_instance_lock import acquire_process_lock
from infrastructure.kis.futures_market_transport import KISWebSocketApprovalKeyProvider
from infrastructure.kis.kis_weekday_collection_plan import OPTION_TRADE_TR_ID, STRATEGY_MONTHLY_OFFSETS
from infrastructure.kis.kis_index_option_master_source import current_monthly_option_symbols
from infrastructure.kis.index_price_source import KISKOSPI200IndexPriceSource
from infrastructure.kis.websocket_index_price_source import KISWebSocketIndexPriceSource
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore
from scripts.kis_vts_subscription_ack import (
    ACK_SCHEMA,
    ACK_SCHEMA_TODO,
    State as SubscriptionState,
    SubscriptionAckController,
    build_request_payload,
)

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]

def market_data_root_from_env() -> Path:
    configured = os.environ.get("PROJECT200_MARKET_DATA_DIR", "kis_market_data_restart").strip()
    if not configured:
        configured = "kis_market_data_restart"
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / "data" / path
SESSION_START = dtime(8, 29)
SESSION_END = dtime(16, 1)
HEARTBEAT_SECONDS = 1.0
SUBSCRIBE_INTERVAL_SECONDS = 0.12
RECONNECT_BACKOFF_SECONDS = 5.0
MAX_SUBSCRIPTIONS = 41
ACK_CONTROLLER_ENABLED = os.environ.get("PROJECT200_WS_ACK_CONTROLLER_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
OPTION_QUOTE_TR_ID = "H0IOASP0"
# Verified against KIS master/VTS REST for 2026-10-15 only. Rollover is unverified.
WEEKLY_PINNED_VALID_DATE = date(2026, 10, 15)
WEEKLY_PINNED_SUBSCRIPTIONS = tuple(
    (OPTION_QUOTE_TR_ID, symbol)
    for symbol in (
        "B09FGW860", "C09FGW860",
        "B09FGW862", "C09FGW862",
        "B09FGW865", "C09FGW865",
        "B09FGW867", "C09FGW867",
        "B09FGW870", "C09FGW870",
    )
)
LOG_PATH = market_data_root_from_env() / "logs" / "websocket_collector.log"
LOGGER = logging.getLogger("kis_vts_websocket_collector_v2")
COLLECTOR_BLOCK_LOGGED: set[str] = set()


def format_trading_date(day: date) -> str:
    """Canonical date-only identifier: YYYYMMDD. Datetime timestamps stay ISO 8601."""
    return day.strftime("%Y%m%d")


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


def build_orderbook_subscriptions(
    day: date, reference_price: Decimal
) -> tuple[tuple[str, str], ...]:
    """Build KIS KOSPI200 option order-book subscriptions from official KIS symbols."""
    return tuple(
        (OPTION_QUOTE_TR_ID, symbol)
        for tr_id, symbol in current_monthly_option_symbols(
            day, reference_price, STRATEGY_MONTHLY_OFFSETS
        )
        if tr_id == OPTION_TRADE_TR_ID
    )


def build_base_subscriptions(day: date) -> tuple[tuple[str, str], ...]:
    """Build the original 26 monthly option quotes plus the index reference."""
    reference_price = KISKOSPI200IndexPriceSource(KISAuthManager.from_env(is_vts=True)).refresh().price
    options = list(build_orderbook_subscriptions(day, reference_price))
    if len(options) != 26:
        raise RuntimeError(f"KIS_WEBSOCKET_BASELINE_OPTION_COUNT_UNEXPECTED:{len(options)}")
    base = tuple(options + [("H0UPCNT0", "2001")])
    if len(base) != 27:
        raise RuntimeError(f"KIS_WEBSOCKET_BASELINE_COUNT_UNEXPECTED:{len(base)}")
    return base


def build_subscriptions(
    day: date,
    *,
    base_subscriptions: tuple[tuple[str, str], ...] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Build base subscriptions plus the date-validated pinned weekly set."""
    if day != WEEKLY_PINNED_VALID_DATE:
        raise RuntimeError(
            f"KIS_WEEKLY_PINNED_SET_DATE_UNVERIFIED:{format_trading_date(day)}:"
            f"valid_only={format_trading_date(WEEKLY_PINNED_VALID_DATE)}"
        )
    base = tuple(base_subscriptions) if base_subscriptions is not None else build_base_subscriptions(day)
    subscriptions = tuple(dict.fromkeys((*base, *WEEKLY_PINNED_SUBSCRIPTIONS)))
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")
    return subscriptions


def startup_gate_reason(day: date, *, ack_enabled: bool = ACK_CONTROLLER_ENABLED) -> str | None:
    """Offline-testable startup gate; ACK protocol gating is opt-in."""
    if ack_enabled and not ACK_SCHEMA.configured:
        return "KIS_WS_ACK_SCHEMA_UNVERIFIED"
    if ack_enabled and day != WEEKLY_PINNED_VALID_DATE:
        return f"KIS_WEEKLY_PINNED_SET_DATE_UNVERIFIED:{format_trading_date(day)}"
    return None


def _legacy_subscription_message(approval_key: str, tr_id: str, symbol: str, *, unsubscribe: bool = False) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "2" if unsubscribe else "1",
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
    })


async def _legacy_subscribe_all(ws, approval_key: str, subscriptions: tuple[tuple[str, str], ...]) -> None:
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")
    for index, (tr_id, symbol) in enumerate(subscriptions, 1):
        await ws.send(_legacy_subscription_message(approval_key, tr_id, symbol))
        if index < len(subscriptions):
            await asyncio.sleep(SUBSCRIBE_INTERVAL_SECONDS)


async def _legacy_rotate(ws, approval_key: str, active: set[tuple[str, str]], desired: tuple[tuple[str, str], ...]) -> set[tuple[str, str]]:
    desired_set = set(desired)
    if len(desired_set) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(desired_set)}")
    # Unsubscribe first: prevents transient subscription count from exceeding the cap.
    removals = sorted(active - desired_set)
    additions = sorted(desired_set - active)
    for tr_id, symbol in removals:
        await ws.send(_legacy_subscription_message(approval_key, tr_id, symbol, unsubscribe=True))
        active.discard((tr_id, symbol))
        await asyncio.sleep(SUBSCRIBE_INTERVAL_SECONDS)
    if len(active) + len(additions) > MAX_SUBSCRIPTIONS:
        raise RuntimeError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(active) + len(additions)}")
    for tr_id, symbol in additions:
        await ws.send(_legacy_subscription_message(approval_key, tr_id, symbol))
        active.add((tr_id, symbol))
        await asyncio.sleep(SUBSCRIBE_INTERVAL_SECONDS)
    return active


def _approval_key(auth: KISAuthManager) -> str:
    provider = KISWebSocketApprovalKeyProvider(auth, timeout=10.0)
    return provider.issue()


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


def _append_jsonl(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def _is_valid_hhmmss(value: str) -> bool:
    if len(value) != 6 or not value.isdigit():
        return False
    hour, minute, second = int(value[:2]), int(value[2:4]), int(value[4:6])
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59

def _source_time_from_frame(payload: str, tr_id: str) -> str | None:
    """Return the raw HHMMSS field for TRs whose official schemas name it bsop_hour."""
    if tr_id not in {"H0IOCNT0", "H0IFCNT0", "H0UPCNT0"}:
        return None
    parts = payload.split("|", 3)
    if len(parts) != 4:
        return None
    fields = parts[3].split("^")
    if len(fields) < 2:
        return None
    value = fields[1].strip()
    return value if _is_valid_hhmmss(value) else None


def _source_time_candidate_from_frame(payload: str, tr_id: str) -> str | None:
    """Expose the raw HHMMSS-shaped candidate without asserting official field semantics."""
    if tr_id != "H0IOASP0":
        return None
    parts = payload.split("|", 3)
    if len(parts) != 4:
        return None
    fields = parts[3].split("^")
    if len(fields) < 2:
        return None
    value = fields[1].strip()
    return value if _is_valid_hhmmss(value) else None

def _append_subscription_event(path: Path, *, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_subscription_events_manifest(day_dir: Path, *, initial_subscriptions: tuple[tuple[str, str], ...], raw_manifest: dict[str, object]) -> Path:
    events_path = day_dir / "kis_vts_subscription_events.jsonl"
    event_count = 0
    if events_path.is_file():
        with events_path.open("r", encoding="utf-8") as handle:
            event_count = sum(1 for line in handle if line.strip())
    manifest = {
        "schema_version": "kis-vts-subscription-events-manifest-v1",
        "trading_date": day_dir.name,
        "source": "KIS:H0UPCNT0:2001",
        "recenter_trigger": "absolute_live_index_move_gte_5.0_from_last_center",
        "subscription_cap": MAX_SUBSCRIPTIONS,
        "initial_subscriptions": [{"tr_id": tr, "symbol": symbol} for tr, symbol in initial_subscriptions],
        "initial_subscription_count": len(initial_subscriptions),
        "event_file": events_path.name,
        "event_count": event_count,
        "event_file_sha256": _sha256_file(events_path) if events_path.is_file() else None,
        "raw_manifest_schema": raw_manifest.get("schema"),
        "raw_file": "kis_vts_websocket_raw.jsonl",
        "raw_file_sha256": raw_manifest.get("file_sha256"),
        "raw_record_count": raw_manifest.get("record_count"),
    }
    path = day_dir / "kis_vts_subscription_events.manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


async def _dispatch_next_subscription_request(
    ws,
    approval_key: str,
    controller: SubscriptionAckController,
    *,
    events_path: Path,
    day: date,
) -> None:
    request = controller.prepare_next()
    if request is None:
        return
    try:
        # Preserve the existing minimum spacing between subscription requests.
        await asyncio.sleep(SUBSCRIBE_INTERVAL_SECONDS)
        payload = build_request_payload(approval_key=approval_key, request=request, schema=controller.schema)
        await ws.send(payload)
        controller.mark_sent(request.request_id)
        _append_subscription_event(events_path, event={
            "schema_version": "kis-vts-subscription-event-v1",
            "event": "SUBSCRIPTION_REQUEST_SENT",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "trading_date": format_trading_date(day),
            "session_generation": request.session_generation,
            "request_id": request.request_id,
            "action": request.action.value,
            "tr_id": request.tr_id,
            "symbol": request.symbol,
            "ack_deadline_seconds": controller.timeout_seconds,
            "confirmed_subscription_count": len(controller.confirmed),
        })
    except Exception as exc:
        controller.mark_send_error(request.request_id)
        _append_subscription_event(events_path, event={
            "schema_version": "kis-vts-subscription-event-v1",
            "event": "SUBSCRIPTION_SEND_UNKNOWN",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "trading_date": format_trading_date(day),
            "request_id": request.request_id,
            "action": request.action.value,
            "tr_id": request.tr_id,
            "symbol": request.symbol,
            "error_type": type(exc).__name__,
            "state": controller.state.value,
            "result": controller.last_result,
        })
        LOGGER.error("WS_SUBSCRIPTION_STATE_UNKNOWN request_id=%s error_type=%s",
                     request.request_id, type(exc).__name__)


async def collect_day(day: date, *, market_data_root: Path) -> None:
    # ACK protocol gate is opt-in; default collector startup preserves data-capture operation.
    reason = startup_gate_reason(day)
    if reason is not None:
        if reason not in COLLECTOR_BLOCK_LOGGED:
            LOGGER.error("WS_ACK_PROTOCOL_BLOCKED reason=%s detail=%s", reason, ACK_SCHEMA_TODO)
            COLLECTOR_BLOCK_LOGGED.add(reason)
        await asyncio.sleep(5)
        return

    auth = KISAuthManager.from_env(
        is_vts=True,
        env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    if not auth.has_credentials():
        raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")

    base_subscriptions = build_base_subscriptions(day)
    subscriptions = (
        build_subscriptions(day, base_subscriptions=base_subscriptions)
        if ACK_CONTROLLER_ENABLED
        else base_subscriptions
    )
    initial_subscriptions = subscriptions
    day_dir = market_data_root / format_trading_date(day)
    raw_store = KISRealtimeRawStore(day_dir / "kis_vts_websocket_raw.jsonl")
    control_events_path = day_dir / "kis_vts_websocket_control_events.jsonl"
    timing_path = day_dir / "kis_vts_websocket_timing.jsonl"
    sequence = raw_store.count()
    ws_url = "ws://ops.koreainvestment.com:31000"

    LOGGER.info("WS_DAY_START date=%s subscriptions=%d raw=%s", format_trading_date(day), len(subscriptions), raw_store.path)

    while True:
        now = now_kst()
        if now.date() != day or now.time() >= SESSION_END:
            break
        if now.time() < SESSION_START:
            await asyncio.sleep(1)
            continue

        ack_controller: SubscriptionAckController | None = None
        try:
            # One persistent WebSocket session for the whole collection window.
            approval_key = _approval_key(auth)
            async with websockets.connect(ws_url, proxy=None, ping_interval=20, ping_timeout=20, open_timeout=10) as ws:
                events_path = day_dir / "kis_vts_subscription_events.jsonl"
                if ACK_CONTROLLER_ENABLED:
                    ack_controller = SubscriptionAckController(
                        baseline=set(base_subscriptions),
                        pinned=set(WEEKLY_PINNED_SUBSCRIPTIONS),
                        cap=MAX_SUBSCRIPTIONS,
                        schema=ACK_SCHEMA,
                    )
                    ack_controller.start_initial(set(subscriptions))
                    await _dispatch_next_subscription_request(
                        ws, approval_key, ack_controller, events_path=events_path, day=day,
                    )
                    active_subscriptions = set(subscriptions)
                else:
                    ack_controller = None
                    await _legacy_subscribe_all(ws, approval_key, subscriptions)
                    active_subscriptions = set(subscriptions)
                    LOGGER.info(
                        "WS_SUBSCRIPTION_SENDS_COMPLETED status=OBSERVATION_ONLY count=%d ack_controller=OFF",
                        len(active_subscriptions),
                    )
                index_price_source = KISWebSocketIndexPriceSource(session_date=day)
                initial_price = KISKOSPI200IndexPriceSource(auth).refresh().price
                center_price = initial_price
                pending_rotation: dict[str, object] | None = None
                last_heartbeat = time.monotonic()
                connected_at = datetime.now(timezone.utc)
                _append_jsonl(control_events_path, {
                    "schema_version": "kis-vts-websocket-control-event-v1",
                    "event": "SESSION_CONNECTED",
                    "recorded_at": connected_at.isoformat(),
                    "trading_date": format_trading_date(day),
                    "endpoint": ws_url,
                    "subscription_count": len(subscriptions),
                    "subscription_status": "ACK_PENDING" if ACK_CONTROLLER_ENABLED else "OBSERVATION_ONLY_ACK_DISABLED",
                    "subscriptions": [{"tr_id": tr_id, "symbol": symbol} for tr_id, symbol in subscriptions],
                })
                LOGGER.info(
                    "WS_CONNECTED date=%s planned_subscriptions=%d subscription_status=ACK_PENDING center_price=%s",
                    format_trading_date(day), len(subscriptions), center_price,
                )

                while True:
                    now = now_kst()
                    if now.date() != day or now.time() >= SESSION_END:
                        break

                    try:
                        payload = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        payload = None
                        if ack_controller is not None and ack_controller.check_timeout():
                            _append_subscription_event(events_path, event={
                                "schema_version": "kis-vts-subscription-event-v1",
                                "event": "SUBSCRIPTION_ACK_TIMEOUT",
                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                                "trading_date": format_trading_date(day),
                                "request_id": ack_controller.pending.request_id if ack_controller.pending else None,
                                "state": ack_controller.state.value,
                                "result": ack_controller.last_result,
                                "confirmed_subscription_count": len(ack_controller.confirmed),
                            })
                            LOGGER.error(
                                "WS_SUBSCRIPTION_UNKNOWN state=%s result=%s confirmed_count=%d",
                                ack_controller.state.value, ack_controller.last_result, len(ack_controller.confirmed),
                            )

                    if payload is not None:
                        if isinstance(payload, bytes):
                            payload = payload.decode("utf-8")
                        payload = str(payload)
                        received_at = datetime.now(timezone.utc)
                        if _is_control_frame(payload):
                            _append_jsonl(control_events_path, {
                                "schema_version": "kis-vts-websocket-control-event-v1",
                                "event": "CONTROL_FRAME",
                                "recorded_at": received_at.isoformat(),
                                "trading_date": format_trading_date(day),
                                "payload": payload,
                            })
                            if ack_controller is not None:
                                ack_result = ack_controller.handle_frame(payload)
                                if ack_result != "NOT_ACK":
                                    event = dict(ack_controller.last_event or {})
                                    event.update({
                                        "schema_version": "kis-vts-subscription-event-v1",
                                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                                        "trading_date": format_trading_date(day),
                                        "ack_handler_result": ack_result,
                                        "state": ack_controller.state.value,
                                        "result": ack_controller.last_result,
                                    })
                                    _append_subscription_event(events_path, event=event)
                                    if ack_result == "ACK_SUCCESS":
                                        if ack_controller.last_completed_kind == "INITIAL":
                                            LOGGER.info(
                                                "WS_INITIAL_SUBSCRIPTIONS_ACKNOWLEDGED count=%d",
                                                len(ack_controller.confirmed),
                                            )
                                            ack_controller.last_completed_kind = None
                                        elif ack_controller.last_completed_kind == "ROTATION":
                                            if pending_rotation is not None:
                                                center_price = pending_rotation["center_price"]
                                                subscriptions = tuple(pending_rotation["desired"])
                                                LOGGER.info(
                                                    "WS_RECENTERED_ACK_VERIFIED date=%s price=%s subscriptions=%d",
                                                    format_trading_date(day), center_price, len(ack_controller.confirmed),
                                                )
                                                pending_rotation = None
                                            ack_controller.last_completed_kind = None
                                    if ack_controller.state in {SubscriptionState.APPLYING, SubscriptionState.ROLLING_BACK}:
                                        await _dispatch_next_subscription_request(
                                            ws, approval_key, ack_controller, events_path=events_path, day=day,
                                        )
                                    elif ack_controller.state in {SubscriptionState.UNKNOWN, SubscriptionState.BLOCKED}:
                                        LOGGER.error(
                                            "WS_SUBSCRIPTION_BLOCKED state=%s result=%s confirmed_count=%d",
                                            ack_controller.state.value, ack_controller.last_result,
                                            len(ack_controller.confirmed),
                                        )
                        else:
                            identity = _frame_identity(payload)
                            if identity is None:
                                _append_jsonl(control_events_path, {
                                    "schema_version": "kis-vts-websocket-control-event-v1",
                                    "event": "UNPARSEABLE_FRAME",
                                    "recorded_at": received_at.isoformat(),
                                    "trading_date": format_trading_date(day),
                                    "payload": payload,
                                })
                                LOGGER.warning("WS_FRAME_UNPARSEABLE prefix=%r", payload[:160])
                            else:
                                tr_id, symbol = identity
                                sequence += 1
                                raw_store.append(
                                    received_at=received_at,
                                    trading_date=format_trading_date(day),
                                    instrument=symbol,
                                    tr_id=tr_id,
                                    payload=payload,
                                    sequence=sequence,
                                )
                                source_time_raw = _source_time_from_frame(payload, tr_id)
                                source_time_candidate_raw = _source_time_candidate_from_frame(payload, tr_id)
                                _append_jsonl(timing_path, {
                                    "schema_version": "kis-vts-websocket-timing-v1",
                                    "trading_date": format_trading_date(day),
                                    "sequence": sequence,
                                    "tr_id": tr_id,
                                    "symbol": symbol,
                                    "source_timestamp_field": "bsop_hour" if source_time_raw is not None else None,
                                    "source_timestamp_raw": source_time_raw,
                                    "source_timestamp_candidate_raw": source_time_candidate_raw,
                                    "source_timestamp_candidate_status": "UNVERIFIED_FIELD_POSITION_AND_SEMANTICS" if source_time_candidate_raw is not None else None,
                                    "source_timestamp_format": "HHMMSS" if source_time_raw is not None else None,
                                    "source_capability_status": (
                                        "UNVERIFIED_FOR_VTS_OFFICIAL_SAMPLE_SAYS_LIVE_ONLY"
                                        if tr_id == "H0IOCNT0" else "NOT_ASSESSED"
                                    ),
                                    "received_at_utc": received_at.isoformat(),
                                    "received_at_kst": received_at.astimezone(KST).isoformat(),
                                    "raw_payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                                    "raw_payload_file": "kis_vts_websocket_raw.jsonl",
                                    "source_clock_timezone": "UNVERIFIED",
                                    "source_date_semantics": "UNVERIFIED",
                                })
                                if tr_id == "H0UPCNT0" and symbol == "2001":
                                    observation = index_price_source.update_frame(payload, received_at=received_at)
                                    # ACK mode requires READY; default capture mode recenters on the observed index.
                                    if (
                                        (ack_controller is None or ack_controller.ready)
                                        and abs(observation.price - center_price) >= Decimal("5.0")
                                    ):
                                        new_subscriptions = list(build_orderbook_subscriptions(day, observation.price))
                                        new_subscriptions.append(("H0UPCNT0", "2001"))
                                        if ACK_CONTROLLER_ENABLED:
                                            new_subscriptions.extend(WEEKLY_PINNED_SUBSCRIPTIONS)
                                        desired = tuple(dict.fromkeys(new_subscriptions))
                                        if len(desired) > MAX_SUBSCRIPTIONS:
                                            if ack_controller is not None:
                                                ack_controller._block(
                                                    f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(desired)}"
                                                )
                                            LOGGER.error(
                                                "KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED desired=%d cap=%d",
                                                len(desired), MAX_SUBSCRIPTIONS,
                                            )
                                            _append_subscription_event(events_path, event={
                                                "schema_version": "kis-vts-subscription-event-v1",
                                                "event": "ROTATION_BLOCKED",
                                                "recorded_at": datetime.now(timezone.utc).isoformat(),
                                                "reason": "DESIRED_SET_EXCEEDS_CAP",
                                                "desired_count": len(desired),
                                                "subscription_cap": MAX_SUBSCRIPTIONS,
                                            })
                                        elif ack_controller is None:
                                            try:
                                                active_subscriptions = await _legacy_rotate(
                                                    ws, approval_key, active_subscriptions, desired,
                                                )
                                                previous_center = center_price
                                                center_price = observation.price
                                                subscriptions = desired
                                                _append_subscription_event(events_path, event={
                                                    "schema_version": "kis-vts-subscription-event-v1",
                                                    "event": "ROTATION_SENT_OBSERVATION_ONLY",
                                                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                                                    "trading_date": format_trading_date(day),
                                                    "reference_price": str(observation.price),
                                                    "previous_center_price": str(previous_center),
                                                    "active_count": len(active_subscriptions),
                                                    "subscription_cap": MAX_SUBSCRIPTIONS,
                                                    "ack_status": "NOT_USED",
                                                })
                                                LOGGER.info(
                                                    "WS_RECENTERED_OBSERVED date=%s price=%s subscriptions=%d ack_controller=OFF",
                                                    format_trading_date(day), center_price, len(active_subscriptions),
                                                )
                                            except Exception as exc:
                                                LOGGER.error("WS_RECENTER_BLOCKED ack_controller=OFF error_type=%s", type(exc).__name__)
                                        else:
                                            try:
                                                ack_controller.start_rotation(set(desired))
                                                pending_rotation = {
                                                    "center_price": observation.price,
                                                    "desired": desired,
                                                    "observed_at": observation.observed_at.isoformat(),
                                                }
                                                _append_subscription_event(events_path, event={
                                                    "schema_version": "kis-vts-subscription-event-v1",
                                                    "event": "ROTATION_STARTED_ACK_GATED",
                                                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                                                    "reference_price": str(observation.price),
                                                    "previous_center_price": str(center_price),
                                                    "desired_count": len(desired),
                                                    "confirmed_count_before": len(ack_controller.confirmed),
                                                    "state": ack_controller.state.value,
                                                })
                                                await _dispatch_next_subscription_request(
                                                    ws, approval_key, ack_controller,
                                                    events_path=events_path, day=day,
                                                )
                                                if ack_controller.ready and ack_controller.last_completed_kind == "ROTATION":
                                                    center_price = observation.price
                                                    subscriptions = desired
                                                    pending_rotation = None
                                                    ack_controller.last_completed_kind = None
                                                    LOGGER.info(
                                                        "WS_RECENTERED_ACK_VERIFIED date=%s price=%s subscriptions=%d",
                                                        format_trading_date(day), center_price, len(ack_controller.confirmed),
                                                    )
                                            except Exception as exc:
                                                _append_subscription_event(events_path, event={
                                                    "schema_version": "kis-vts-subscription-event-v1",
                                                    "event": "ROTATION_BLOCKED",
                                                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                                                    "error_type": type(exc).__name__,
                                                    "error": str(exc),
                                                    "state": ack_controller.state.value,
                                                    "result": ack_controller.last_result,
                                                })
                                                LOGGER.error(
                                                    "WS_ROTATION_BLOCKED state=%s result=%s error_type=%s",
                                                    ack_controller.state.value, ack_controller.last_result,
                                                    type(exc).__name__,
                                                )

                    if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                        LOGGER.info("WS_HEARTBEAT date=%s raw_count=%d", format_trading_date(day), raw_store.count())
                        last_heartbeat = time.monotonic()

                ended_at = datetime.now(timezone.utc)
                _append_jsonl(control_events_path, {
                    "schema_version": "kis-vts-websocket-control-event-v1",
                    "event": "SESSION_ENDED",
                    "recorded_at": ended_at.isoformat(),
                    "trading_date": format_trading_date(day),
                    "raw_count": raw_store.count(),
                })
                LOGGER.info("WS_SESSION_END date=%s raw_count=%d", format_trading_date(day), raw_store.count())
                break
        except Exception as exc:
            if ack_controller is not None:
                ack_controller.mark_session_lost()
                _append_subscription_event(
                    day_dir / "kis_vts_subscription_events.jsonl",
                    event={
                        "schema_version": "kis-vts-subscription-event-v1",
                        "event": "SESSION_LOST_SUBSCRIPTION_STATE_UNKNOWN",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "trading_date": format_trading_date(day),
                        "state": ack_controller.state.value,
                        "result": ack_controller.last_result,
                        "confirmed_subscription_count": len(ack_controller.confirmed),
                    },
                )
            _append_jsonl(control_events_path, {
                "schema_version": "kis-vts-websocket-control-event-v1",
                "event": "SESSION_ERROR",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "trading_date": format_trading_date(day),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            LOGGER.exception("WS_SESSION_ERROR date=%s error=%s", format_trading_date(day), exc)
            await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)

    if raw_store.path.exists():
        raw_manifest = raw_store.write_manifest(
            source="KIS_VTS_WEBSOCKET_RAW",
            endpoint=ws_url,
            tolerate_truncated_tail=True,
        )
        events_manifest_path = write_subscription_events_manifest(
            day_dir, initial_subscriptions=initial_subscriptions, raw_manifest=raw_manifest,
        )
        LOGGER.info("WS_SUBSCRIPTION_MANIFEST_WRITTEN path=%s", events_manifest_path)
    LOGGER.info("WS_DAY_END date=%s raw_count=%d", format_trading_date(day), raw_store.count())


async def run_forever() -> None:
    market_data_root = market_data_root_from_env()
    active_day: date | None = None
    while True:
        now = now_kst()
        if active_day != now.date():
            active_day = now.date()
            LOGGER.info("WS_WATCH_DAY date=%s", format_trading_date(active_day))
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
            LOGGER.exception("WS_DAY_FATAL date=%s error=%s", format_trading_date(active_day), exc)
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
        # Preflight mirrors the active runtime plan: weekly symbols are opt-in
        # with the ACK controller and are never part of the default legacy path.
        subscriptions = (
            build_subscriptions(day)
            if ACK_CONTROLLER_ENABLED
            else build_base_subscriptions(day)
        )
    except Exception as exc:
        print(f"PLAN_BLOCKED:{type(exc).__name__}:{exc}")
        return 3
    print(f"WS_PREFLIGHT_OK date={format_trading_date(day)} subscriptions={len(subscriptions)} limit={MAX_SUBSCRIPTIONS}")
    for tr_id, symbol in subscriptions:
        print(f"  {tr_id} {symbol}")
    print(f"raw_root={market_data_root_from_env()}")
    print(f"session={SESSION_START.isoformat()}-{SESSION_END.isoformat()} KST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--offline-startup-check", action="store_true")
    args = parser.parse_args()
    if args.offline_startup_check:
        reason = startup_gate_reason(now_kst().date())
        if reason is not None:
            print(f"WS_OFFLINE_STARTUP_BLOCKED reason={reason}")
            return 5
        print(
            f"WS_OFFLINE_STARTUP_OK ack_controller={'ON' if ACK_CONTROLLER_ENABLED else 'OFF'} "
            f"gate=OPEN planned_subscription_count=27 weekly_included=false network=NOT_USED"
        )
        return 0
    configure_logging()
    if args.preflight:
        return preflight()
    lock_path = market_data_root_from_env() / "logs" / "kis_vts_websocket_collector.lock"
    lock_handle = acquire_process_lock(lock_path)
    if lock_handle is None:
        LOGGER.error("COLLECTOR_INSTANCE_BLOCKED reason=ANOTHER_WEBSOCKET_COLLECTOR_HOLDS_LOCK")
        return 4
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
