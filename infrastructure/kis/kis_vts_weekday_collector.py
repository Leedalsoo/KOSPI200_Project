from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import time as time_module
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_market_transport import KISFuturesMarketTransport
from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
from infrastructure.kis.krx_kis_option_identity_resolver import load_kis_index_option_master, KRXKISOptionIdentityResolver, KISOptionIdentityResolver
from infrastructure.kis.kis_index_option_master_source import current_monthly_option_symbols
from infrastructure.kis.kis_rest_market_observation_collector import (
    CollectionTarget,
    KISRestMarketObservationCollector,
    KISRestMarketObservationTransport,
)
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.holiday_fallback_provider import (
    FallbackHolidayProvider,
    KRXHolidayProvider,
)
from infrastructure.kis.holiday_provider import KISHolidayProvider
from infrastructure.kis.trading_calendar import ProductionTradingCalendar
from infrastructure.krx.krx_marketplace_master import load_option_master
from infrastructure.krx.krx_option_master_store import (
    KRXOptionMasterRefreshRequired,
    discover_master_snapshot_dates,
    resolve_option_master_paths_for_day,
)
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

SESSION_START = time(8, 29)
SESSION_END = time(16, 1)
ALERT_CHECK_TIME = time(9, 10)
HEARTBEAT_INTERVAL_SECONDS = 60
RESTART_BACKOFF_INITIAL_SECONDS = 2
RESTART_BACKOFF_MAX_SECONDS = 60
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKET_DATA_DIR = "kis_market_data_restart"


def market_data_root_from_env() -> Path:
    configured = os.environ.get("PROJECT200_MARKET_DATA_DIR", DEFAULT_MARKET_DATA_DIR).strip()
    if not configured:
        configured = DEFAULT_MARKET_DATA_DIR
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / "data" / path


MARKET_DATA_ROOT = market_data_root_from_env()
# All dated KIS collection artifacts use the documented authoritative data root.
DATA_ROOT = MARKET_DATA_ROOT
LOG_PATH = DATA_ROOT / "logs" / "collector.log"


def _now_kst() -> datetime:
    return datetime.now(KST)


def _next_backoff(current: int) -> int:
    return min(current * 2, RESTART_BACKOFF_MAX_SECONDS)


def configure_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
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


def build_plan(day: date | None = None) -> CollectionPlan:
    """Build a plan for the requested day, defaulting to the current KST date."""
    return build_plan_for_day(day or _now_kst().date())


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
    """Compatibility entry point; use the date-independent daily orchestrator."""
    await run_daily_forever()


def main() -> None:
    daily_main()


# Date-independent daily REST-first orchestration additions.


class TradingDayStatus:
    TRADING = "TRADING"
    NO_TRADING_SESSION = "NO_TRADING_SESSION"
    UNKNOWN = "UNKNOWN"


@dataclass
class DateSessionManifest:
    schema_version: str
    trading_date: str
    session_status: str
    run_id: str
    collectors: dict[str, dict[str, object]] = field(default_factory=dict)
    targets: list[dict[str, object]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"SUCCESS": 0, "DUPLICATE": 0, "BLOCKED": 0})
    files: list[dict[str, str]] = field(default_factory=list)
    started_at: str = ""
    ended_at: str | None = None
    end_reason: str | None = None

    @classmethod
    def new(cls, day: date, run_id: str, status: str) -> "DateSessionManifest":
        return cls(
            schema_version="project200-kis-market-day-v1",
            trading_date=day.isoformat(), session_status=status, run_id=run_id,
            started_at=datetime.now(KST).isoformat(),
            collectors={"rest": {"status": "NOT_STARTED"}, "websocket": {"status": "NOT_STARTED"}},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "trading_date": self.trading_date,
            "session_status": self.session_status, "run_id": self.run_id,
            "collectors": self.collectors, "targets": self.targets, "counts": self.counts,
            "files": self.files, "started_at": self.started_at, "ended_at": self.ended_at,
            "end_reason": self.end_reason,
        }

    def write(self, day_dir: Path) -> Path:
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / "manifest.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> "DateSessionManifest":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


class DailySessionOrchestrator:
    """Date-independent KST session controller; REST is the primary collector."""

    kst = KST
    open_time = time(8, 29)
    close_time = time(16, 1)

    def __init__(self, market_data_root: str | Path, calendar: object, *, rest_collector=None):
        self.market_data_root = Path(market_data_root)
        self.calendar = calendar
        self.rest_collector = rest_collector

    def day_dir(self, day: date) -> Path:
        return self.market_data_root / day.isoformat()

    def store_for(self, day: date) -> HistoricalMarketStore:
        return HistoricalMarketStore(self.day_dir(day) / "historical_market_observations.jsonl")

    def classify(self, day: date) -> str:
        try:
            return TradingDayStatus.TRADING if self.calendar.is_trading_day(day) else TradingDayStatus.NO_TRADING_SESSION
        except Exception:
            return TradingDayStatus.UNKNOWN

    def prepare_day(self, day: date, *, run_id: str) -> DateSessionManifest:
        status = self.classify(day)
        manifest = DateSessionManifest.new(day, run_id, status)
        if status == TradingDayStatus.NO_TRADING_SESSION:
            manifest.collectors["rest"] = {"status": "NOT_RUN", "reason": "NO_TRADING_SESSION"}
            manifest.collectors["websocket"] = {"status": "NOT_RUN", "reason": "NO_TRADING_SESSION"}
        elif status == TradingDayStatus.UNKNOWN:
            manifest.collectors["calendar"] = {"status": "UNKNOWN", "reason": "AUTHORITATIVE_CALENDAR_UNAVAILABLE"}
        manifest.write(self.day_dir(day))
        self._write_status(day, manifest)
        return manifest

    def _write_status(self, day: date, manifest: DateSessionManifest) -> None:
        self.day_dir(day).mkdir(parents=True, exist_ok=True)
        (self.day_dir(day) / "daily_status.json").write_text(
            json.dumps({"trading_date": manifest.trading_date, "session_status": manifest.session_status,
                        "run_id": manifest.run_id, "reason": manifest.end_reason}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_before_open(self, now: datetime) -> bool:
        return now.astimezone(self.kst).time() < self.open_time

    def is_after_close(self, now: datetime) -> bool:
        return now.astimezone(self.kst).time() >= self.close_time

    def record_rest_results(self, manifest: DateSessionManifest, results: tuple[object, ...]) -> None:
        for result in results:
            status = str(getattr(result, "status", "BLOCKED"))
            manifest.counts[status] = manifest.counts.get(status, 0) + 1
        manifest.collectors["rest"] = {"status": "RUNNING", "last_result_count": len(results)}

    def _reconcile_websocket_evidence(self, manifest: DateSessionManifest) -> None:
        day_dir = self.day_dir(date.fromisoformat(manifest.trading_date))
        evidence = sorted(day_dir.glob("kis_vts_websocket*.jsonl"))
        evidence = [path for path in evidence if path.is_file() and path.stat().st_size > 0]
        websocket = dict(manifest.collectors.get("websocket", {}))
        if evidence:
            total_lines = 0
            for path in evidence:
                with path.open("r", encoding="utf-8") as handle:
                    total_lines += sum(1 for _ in handle)
            websocket.update({
                "status": "RECEIVED_WITH_EVIDENCE",
                "evidence_files": [str(path.relative_to(day_dir)) for path in evidence],
                "evidence_record_count": total_lines,
                "evidence_reconciled_at": datetime.now(KST).isoformat(),
            })
        elif websocket.get("status") == "NOT_STARTED":
            websocket.setdefault("reason", "NO_WEBSOCKET_RAW_EVIDENCE")
        manifest.collectors["websocket"] = websocket

    def finalize(self, manifest: DateSessionManifest, *, end_reason: str) -> None:
        self._reconcile_websocket_evidence(manifest)
        manifest.ended_at = datetime.now(KST).isoformat()
        manifest.end_reason = end_reason
        day_dir = self.market_data_root / manifest.trading_date
        files: list[dict[str, str]] = []
        for path in sorted(day_dir.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                files.append({"path": str(path.relative_to(day_dir)), "sha256": _sha256_file(path)})
        manifest.files = files
        manifest.write(day_dir)
        self._write_status(manifest_day := date.fromisoformat(manifest.trading_date), manifest)


REST_CYCLE_INTERVAL_SECONDS = 30
REST_ROUND_REQUESTS_PER_TARGET = 2
_KIS_OPTION_RESOLVER_CACHE: dict[date, KRXKISOptionIdentityResolver] = {}


def _kis_option_resolver_for_day(day: date) -> KRXKISOptionIdentityResolver:
    resolver = _KIS_OPTION_RESOLVER_CACHE.get(day)
    if resolver is None:
        resolver = KRXKISOptionIdentityResolver(load_kis_index_option_master())
        _KIS_OPTION_RESOLVER_CACHE[day] = resolver
    return resolver


def build_daily_targets(day: date) -> tuple[CollectionTarget, ...]:
    """Build REST option targets directly from the KIS broker master.

    KRX Marketplace Option Master is deliberately not a prerequisite for raw
    KIS collection. KIS supplies the broker symbol and contract identity used
    by the REST transport; KRX remains available downstream for reconciliation.
    """
    reference_price = Decimal(_latest_krx_spot_price())
    subscriptions = current_monthly_option_symbols(
        day, reference_price,
        (
            Decimal("-15.0"), Decimal("-12.5"), Decimal("-10.0"),
            Decimal("-7.5"), Decimal("-5.0"), Decimal("-2.5"), Decimal("0.0"),
            Decimal("2.5"), Decimal("5.0"), Decimal("7.5"), Decimal("10.0"),
            Decimal("12.5"), Decimal("15.0"),
        ),
    )
    kis_resolver = KISOptionIdentityResolver(load_kis_index_option_master())
    targets: list[CollectionTarget] = []
    for tr_id, symbol in subscriptions:
        if tr_id != "H0IOCNT0":
            continue
        identity = kis_resolver.get_contract_identity(symbol)
        if identity is None:
            raise ValueError(f"KIS_OPTION_IDENTITY_REQUIRED:{symbol}")
        targets.append(CollectionTarget(identity=identity))
    if not targets:
        raise ValueError(f"KIS_OPTION_TARGETS_REQUIRED:{day.isoformat()}")
    center = sum((Decimal(str(target.identity.strike)) for target in targets), Decimal("0")) / len(targets)
    targets.sort(key=lambda target: (abs(Decimal(str(target.identity.strike)) - center), str(target.identity.option_type), target.identity.symbol))
    return tuple(targets)

def build_plan_for_day(day: date) -> CollectionPlan:
    reference_price = _latest_krx_spot_price()
    monthly_paths, weekly_paths = resolve_option_master_paths_for_day(ROOT, day)
    try:
        return build_collection_plan(
            reference_price=Decimal(reference_price),
            option_master_paths=monthly_paths,
            weekly_master_paths=weekly_paths,
            standard_futures_symbol="A01609", mini_futures_symbol="A05609", as_of=day,
        )
    except ValueError as exc:
        if str(exc) != "NO_LISTED_OPTION_EXPIRY_AVAILABLE":
            raise
        snapshots = discover_master_snapshot_dates(ROOT, day)
        raise KRXOptionMasterRefreshRequired(
            f"KRX_OPTION_MASTER_REFRESH_REQUIRED:expiry:{day.isoformat()}:snapshots={snapshots}"
        ) from exc


def _daily_run_id(day: date) -> str:
    return f"vts-rest-daily-{day.isoformat()}"


def _manifest_target_rows(targets: tuple[CollectionTarget, ...]) -> list[dict[str, object]]:
    return [{
        "symbol": target.identity.symbol,
        "krx_isu_cd": getattr(target.identity, "instrument_id", ""),
        "expiry": target.identity.expiry,
        "strike": str(target.identity.strike), "option_type": target.identity.option_type,
        "selection_source": "KIS_INDEX_OPTION_MASTER",
        "selection_reason": "MONTHLY_ATM_PLUS_MINUS_15_POINTS",
    } for target in targets]

def _rest_collector_for_day(day: date, store: HistoricalMarketStore):
    auth = KISAuthManager.from_env(
        is_vts=True, env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    if not auth.has_credentials():
        raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")
    transport = KISRestMarketObservationTransport(auth)
    targets = build_daily_targets(day)
    identity_source = {target.identity.symbol: target.identity for target in targets}
    return KISRestMarketObservationCollector(
        identity_source=identity_source, transport=transport, store=store,
    )

def run_rest_cycle_for_day(day: date, manifest: DateSessionManifest, *, cycle_id: str) -> tuple[object, ...]:
    store = HistoricalMarketStore.for_trading_date(MARKET_DATA_ROOT, day)
    try:
        targets = build_daily_targets(day)
        manifest.targets = _manifest_target_rows(targets)
        collector = _rest_collector_for_day(day, store)
    except Exception as exc:
        manifest.collectors["rest"] = {"status": "BLOCKED", "reason": str(exc)}
        manifest.counts["BLOCKED"] += len(manifest.targets) or 1
        return ()
    started = _now_kst()
    results = collector.collect_cycle(list(targets), run_id=manifest.run_id, cycle_id=cycle_id)
    ended = _now_kst()
    manifest.collectors["rest"] = {
        "status": "RUNNING", "target_count": len(targets),
        "round_started_at": started.isoformat(), "round_ended_at": ended.isoformat(),
        "round_duration_seconds": max(0.0, (ended - started).total_seconds()),
        "request_budget_seconds": len(targets) * REST_ROUND_REQUESTS_PER_TARGET,
        "rate_limit_seconds_per_request": 1.0,
    }
    orchestrator = DailySessionOrchestrator(MARKET_DATA_ROOT, object())
    orchestrator.record_rest_results(manifest, results)
    blocked_path = MARKET_DATA_ROOT / day.isoformat() / 'rest_blocked_diagnostics.jsonl'
    for result in results:
        diagnostic = getattr(result, 'diagnostic', None)
        if str(getattr(result, 'status', '')) == 'BLOCKED':
            _write_json_line(blocked_path, {
                'trading_date': day.isoformat(),
                'run_id': manifest.run_id,
                'cycle_id': cycle_id,
                'symbol': getattr(result, 'symbol', None),
                'reason': getattr(result, 'reason', None),
                'diagnostic': diagnostic,
                'recorded_at': _now_kst().isoformat(),
            })
    return results


def _write_json_line(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def collect_underlying_futures_observation(day: date, manifest: DateSessionManifest) -> str:
    """Collect the front KOSPI200 futures contract from the KIS VTS futures board."""
    auth = KISAuthManager.from_env(
        is_vts=True,
        env_file=str(ROOT / ".env"),
        cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
    )
    tr_id = "FHPIF05030200"
    endpoint = "/uapi/domestic-futureoption/v1/quotations/display-board-futures"
    try:
        if not auth.has_credentials():
            raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")
        # KIS VTS REST limit is 1 request/second; the option cycle has its own limiter.
        # Keep the futures-board request outside that cycle but still honor the broker limit.
        time_module.sleep(1.1)
        query = urllib.parse.urlencode({
            "FID_COND_MRKT_DIV_CODE": "F",
            "FID_COND_SCR_DIV_CODE": "20503",
            "FID_COND_MRKT_CLS_CODE": "MKI",
        })
        request = urllib.request.Request(
            f"{auth.base_url}{endpoint}?{query}",
            headers=auth.get_auth_headers(tr_id=tr_id),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=10.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("rt_cd") != "0":
            raise RuntimeError(
                f"KIS_FUTURES_BOARD_ERROR:{payload.get('msg_cd')}:{payload.get('msg1')}"
            )
        rows = payload.get("output")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("KIS_FUTURES_BOARD_EMPTY")
        current_month = f"{day.year:04d}{day.month:02d}"
        candidates: list[dict[str, object]] = []
        for row in rows:
            name = str(row.get("hts_kor_isnm") or "")
            match = __import__("re").search(r"(20\d{4})$", name)
            if not match or match.group(1) < current_month:
                continue
            try:
                price = Decimal(str(row.get("futs_prpr") or ""))
                volume = Decimal(str(row.get("acml_vol") or ""))
            except Exception:
                continue
            if price <= 0 or volume < 0:
                continue
            candidates.append(row)
        if not candidates:
            raise RuntimeError("KIS_CURRENT_FUTURES_CONTRACT_NOT_FOUND")
        selected = min(
            candidates,
            key=lambda row: __import__("re").search(
                r"(20\d{4})$",
                str(row.get("hts_kor_isnm") or ""),
            ).group(1),
        )
        collected_at = _now_kst().isoformat()
        day_dir = MARKET_DATA_ROOT / day.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        _write_json_line(day_dir / "futures_underlying_rest.jsonl", {
            "collected_at": collected_at,
            "source": "KIS_VTS_REST",
            "tr_id": tr_id,
            "endpoint": endpoint,
            "instrument": {
                "symbol": str(selected.get("futs_shrn_iscd") or ""),
                "name": str(selected.get("hts_kor_isnm") or ""),
            },
            "observation": {
                "price": str(selected.get("futs_prpr")),
                "volume": str(selected.get("acml_vol")),
                "ask_price": str(selected.get("futs_askp")),
                "bid_price": str(selected.get("futs_bidp")),
                "high": str(selected.get("futs_hgpr")),
                "low": str(selected.get("futs_lwpr")),
                "theoretical_price": str(selected.get("hts_thpr")),
                "open_interest": str(selected.get("hts_otst_stpl_qty")),
            },
            "raw": selected,
        })
        manifest.collectors["futures_underlying_rest"] = {
            "status": "RUNNING",
            "tr_id": tr_id,
            "symbol": str(selected.get("futs_shrn_iscd") or ""),
            "contract_name": str(selected.get("hts_kor_isnm") or ""),
            "price": str(selected.get("futs_prpr") or ""),
            "volume": str(selected.get("acml_vol") or ""),
            "source": "KIS_VTS_REST",
        }
        manifest.counts["SUCCESS"] = manifest.counts.get("SUCCESS", 0) + 1
        return "SUCCESS"
    except Exception as exc:
        manifest.collectors["futures_underlying_rest"] = {
            "status": "BLOCKED",
            "reason": str(exc),
            "tr_id": tr_id,
        }
        manifest.counts["BLOCKED"] = manifest.counts.get("BLOCKED", 0) + 1
        return "BLOCKED"


def authoritative_calendar_for_today(day: date):
    kis_provider = KISHolidayProvider(
        auth_manager=KISAuthManager.from_env(
            is_vts=False, env_file=str(ROOT / ".env"),
            cache_file_path=str(ROOT / "data" / ".kis_token_cache_real.json"),
        ),
        auto_load=False,
        target_year=day.year,
        strict_mode=True,
    )
    krx_provider = KRXHolidayProvider(
        cache_dir=ROOT / "data" / "calendar",
    )
    provider = FallbackHolidayProvider(
        kis_provider=kis_provider,
        krx_provider=krx_provider,
        enable_kis=True,
    )
    return ProductionTradingCalendar(provider)


def pre_open_smoke(day: date, *, market_data_root: Path = MARKET_DATA_ROOT) -> DateSessionManifest:
    """Pre-open readiness check: credentials, Option Master target selection, dated manifest."""
    calendar = authoritative_calendar_for_today(day)
    orchestrator = DailySessionOrchestrator(market_data_root, calendar)
    manifest = orchestrator.prepare_day(day, run_id=_daily_run_id(day))
    try:
        targets = build_daily_targets(day)
        manifest.targets = _manifest_target_rows(targets)
        auth = KISAuthManager.from_env(
            is_vts=True, env_file=str(ROOT / ".env"),
            cache_file_path=str(ROOT / "data" / ".kis_token_cache_vts.json"),
        )
        if not auth.has_credentials():
            raise RuntimeError("KIS_VTS_CREDENTIALS_REQUIRED")
        auth.get_access_token()
        manifest.collectors["rest"] = {"status": "READY", "target_count": len(targets), "rate_limit_seconds": 1.0}
        manifest.collectors["websocket"] = {"status": "DEGRADED_REST_PRIMARY", "reason": "REST_IS_PRIMARY; WS_FRAME_EVIDENCE_NOT_REQUIRED_FOR_REST"}
        manifest.end_reason = "PRE_OPEN_SMOKE_PASS"
    except Exception as exc:
        manifest.collectors["rest"] = {"status": "BLOCKED", "reason": str(exc)}
        manifest.end_reason = "PRE_OPEN_SMOKE_BLOCKED"
    manifest.write(orchestrator.day_dir(day))
    orchestrator._write_status(day, manifest)
    return manifest


def run_daily_once(now: datetime | None = None, *, market_data_root: Path = MARKET_DATA_ROOT) -> DateSessionManifest:
    current = (now or _now_kst()).astimezone(KST)
    day = current.date()
    calendar = authoritative_calendar_for_today(day)
    orchestrator = DailySessionOrchestrator(market_data_root, calendar)
    manifest = orchestrator.prepare_day(day, run_id=_daily_run_id(day))
    if manifest.session_status == TradingDayStatus.NO_TRADING_SESSION:
        orchestrator.finalize(manifest, end_reason="NO_TRADING_SESSION")
        return manifest
    if current.time() < orchestrator.open_time:
        return pre_open_smoke(day, market_data_root=market_data_root)
    if current.time() >= orchestrator.close_time:
        orchestrator.finalize(manifest, end_reason="SESSION_ALREADY_CLOSED")
        return manifest
    manifest.collectors["websocket"] = {"status": "DEGRADED_REST_PRIMARY", "reason": "REST_CONTINUES_INDEPENDENTLY_OF_WS"}
    run_rest_cycle_for_day(day, manifest, cycle_id="cycle-0001")
    collect_underlying_futures_observation(day, manifest)
    orchestrator.finalize(manifest, end_reason="SINGLE_CYCLE_COMPLETE")
    return manifest


async def run_daily_forever() -> None:
    active_day: date | None = None
    manifest: DateSessionManifest | None = None
    cycle_number = 0
    smoke_done = False
    while True:
        now = _now_kst()
        if active_day != now.date():
            active_day = now.date()
            cycle_number = 0
            smoke_done = False
            try:
                calendar = authoritative_calendar_for_today(active_day)
                orchestrator = DailySessionOrchestrator(MARKET_DATA_ROOT, calendar)
                manifest = orchestrator.prepare_day(active_day, run_id=_daily_run_id(active_day))
                if manifest.session_status == TradingDayStatus.NO_TRADING_SESSION:
                    orchestrator.finalize(manifest, end_reason="NO_TRADING_SESSION")
                    manifest = None
            except Exception as exc:
                LOGGER.exception("DAILY_SESSION_ERROR date=%s error=%s", active_day, exc)
                manifest = None
        if manifest is not None:
            if now.time() < DailySessionOrchestrator.open_time:
                if not smoke_done:
                    pre_open_smoke(active_day)
                    smoke_done = True
            elif now.time() < DailySessionOrchestrator.close_time:
                cycle_number += 1
                run_rest_cycle_for_day(active_day, manifest, cycle_id=f"cycle-{cycle_number:04d}")
                collect_underlying_futures_observation(active_day, manifest)
                manifest.write(MARKET_DATA_ROOT / active_day.isoformat())
                _write_json_line(MARKET_DATA_ROOT / active_day.isoformat() / "heartbeat.jsonl", {
                    "trading_date": active_day.isoformat(), "run_id": manifest.run_id,
                    "heartbeat_at": now.isoformat(), "cycle_id": f"cycle-{cycle_number:04d}",
                    "rest_status": manifest.collectors.get("rest", {}).get("status"),
                })
            else:
                DailySessionOrchestrator(MARKET_DATA_ROOT, object()).finalize(manifest, end_reason="SESSION_END")
                manifest = None
        await asyncio.sleep(30)


def daily_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Project200 KIS daily REST-first collector")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    configure_logging()
    if args.smoke:
        result = pre_open_smoke(_now_kst().date())
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    if args.once:
        result = run_daily_once()
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    asyncio.run(run_daily_forever())


if __name__ == "__main__":
    daily_main()
