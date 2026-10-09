"""Acquire and validate one date of authoritative KRX derivatives daily data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS = {
    "options": "https://data-dbg.krx.co.kr/svc/apis/drv/opt_bydd_trd",
    "futures": "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd",
}
REQUIRED_FIELDS = {
    "options": {"BAS_DD", "ISU_CD", "ISU_NM", "PROD_NM", "RGHT_TP_NM"},
    "futures": {"BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "SPOT_PRC"},
}


class KRXAcquisitionError(RuntimeError):
    """Raised when authoritative KRX data cannot be safely acquired."""


def load_auth_key(root: Path = ROOT) -> str:
    """Read the KRX key from the process environment or local .env without logging it."""
    value = os.environ.get("KRX_AUTH_KEY", "").strip()
    if value:
        return value.strip('"').strip("'")
    env_path = root / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("KRX_AUTH_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise KRXAcquisitionError("KRX_AUTH_KEY_REQUIRED")


def parse_response(kind: str, trading_date: str, raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if kind not in REQUIRED_FIELDS:
        raise KRXAcquisitionError(f"KRX_KIND_INVALID:{kind}")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KRXAcquisitionError(f"KRX_RESPONSE_INVALID_JSON:{kind}") from exc
    if not isinstance(payload, dict):
        raise KRXAcquisitionError(f"KRX_RESPONSE_INVALID_OBJECT:{kind}")
    rows = payload.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise KRXAcquisitionError(f"KRX_RESPONSE_ROWS_EMPTY:{kind}")
    if any(not isinstance(row, dict) for row in rows):
        raise KRXAcquisitionError(f"KRX_RESPONSE_ROW_INVALID:{kind}")
    expected_date = trading_date.replace("-", "")
    if any(str(row.get("BAS_DD", "")).replace("-", "") != expected_date for row in rows):
        raise KRXAcquisitionError(f"KRX_RESPONSE_DATE_MISMATCH:{kind}:{expected_date}")
    missing = sorted(REQUIRED_FIELDS[kind] - set().union(*(set(row) for row in rows)))
    if missing:
        raise KRXAcquisitionError(f"KRX_RESPONSE_SCHEMA_MISSING:{kind}:{','.join(missing)}")
    return payload, rows


def fetch_daily(kind: str, trading_date: str, auth_key: str, *, timeout: float = 25.0) -> tuple[bytes, int, int]:
    endpoint = ENDPOINTS[kind]
    url = endpoint + "?" + urllib.parse.urlencode({"basDd": trading_date})
    request = urllib.request.Request(url, headers={"AUTH_KEY": auth_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise KRXAcquisitionError(f"KRX_HTTP_ERROR:{kind}:{exc.code}") from None
    except Exception as exc:
        raise KRXAcquisitionError(f"KRX_REQUEST_FAILED:{kind}:{type(exc).__name__}") from None
    if status != 200:
        raise KRXAcquisitionError(f"KRX_HTTP_ERROR:{kind}:{status}")
    _, rows = parse_response(kind, trading_date, raw)
    return raw, status, len(rows)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def acquire_snapshot(trading_date: str, *, root: Path = ROOT, overwrite: bool = False) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", trading_date):
        raise KRXAcquisitionError("KRX_TRADING_DATE_FORMAT_REQUIRED_YYYYMMDD")
    auth_key = load_auth_key(root)
    fetched: dict[str, tuple[bytes, int, int]] = {}
    for kind in ("options", "futures"):
        fetched[kind] = fetch_daily(kind, trading_date, auth_key)

    raw_dir = root / "data" / "historical" / "krx_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    items = []
    targets: dict[str, Path] = {}
    for kind, (raw, status, row_count) in fetched.items():
        filename = f"{trading_date}_{kind}_daily.json"
        target = raw_dir / filename
        targets[kind] = target
        items.append({
            "file": str(target.relative_to(root)).replace("\\", "/"),
            "source": "KRX_OPEN_API",
            "endpoint": "/" + ENDPOINTS[kind].split("/svc/apis/", 1)[1],
            "basDd": trading_date,
            "http_status": status,
            "row_count": row_count,
            "sha256": sha256_bytes(raw),
        })
    manifest_path = raw_dir / f"manifest_{trading_date}.json"
    existing = [path for path in (*targets.values(), manifest_path) if path.exists()]
    if existing and not overwrite:
        same = all(target.exists() and sha256_bytes(target.read_bytes()) == sha256_bytes(fetched[kind][0])
                   for kind, target in targets.items())
        if same and manifest_path.exists():
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            if prior.get("items") == items:
                return {"status": "ALREADY_PRESENT", "trading_date": trading_date, "items": items}
        raise KRXAcquisitionError("KRX_TARGET_EXISTS_USE_OVERWRITE")

    manifest = {
        "schema": "krx-historical-acquisition-manifest-v1",
        "acquired_via": "KRX OPEN API",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    temp_paths: list[Path] = []
    try:
        for kind, target in targets.items():
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(fetched[kind][0])
            temp_paths.append(temp)
        manifest_temp = manifest_path.with_suffix(".json.tmp")
        manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_paths.append(manifest_temp)
        for kind, target in targets.items():
            target.with_suffix(target.suffix + ".tmp").replace(target)
        manifest_temp.replace(manifest_path)
    finally:
        for temp in temp_paths:
            if temp.exists():
                temp.unlink()
    return {"status": "ACQUIRED", "trading_date": trading_date, "items": items, "manifest": str(manifest_path.relative_to(root))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="KRX trading date in YYYYMMDD format")
    parser.add_argument("--overwrite", action="store_true", help="replace existing snapshot files after full response validation")
    args = parser.parse_args()
    try:
        result = acquire_snapshot(args.date, overwrite=args.overwrite)
    except KRXAcquisitionError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
