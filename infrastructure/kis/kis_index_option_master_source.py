from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

KIS_INDEX_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"
KOSPI200_UNDERLYING = "2001"
OPTION_KINDS = {"5": "CALL", "6": "PUT"}


def load_kis_index_option_rows() -> tuple[dict[str, str | Decimal], ...]:
    request = Request(KIS_INDEX_MASTER_URL, headers={"User-Agent": "OptionProject/200"})
    with urlopen(request, timeout=15) as response:
        payload = response.read()
    with ZipFile(BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".mst")]
        if not members:
            raise RuntimeError("KIS_INDEX_OPTION_MASTER_FILE_REQUIRED")
        raw = archive.read(members[0]).decode("cp949", errors="replace")

    rows: list[dict[str, str | Decimal]] = []
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) < 9 or fields[0] not in OPTION_KINDS or fields[7].strip() != KOSPI200_UNDERLYING:
            continue
        short_code = fields[1].strip()
        name = fields[3].strip()
        strike_raw = fields[5].strip()
        if not short_code or not strike_raw or len(name) < 8:
            continue
        try:
            strike = Decimal(strike_raw)
        except Exception:
            continue
        month = name.split()[1] if len(name.split()) >= 2 else ""
        if len(month) != 6 or not month.isdigit():
            continue
        rows.append({
            "short_code": short_code,
            "option_type": OPTION_KINDS[fields[0]],
            "month": month,
            "strike": strike,
        })
    if not rows:
        raise RuntimeError("KIS_KOSPI200_OPTION_MASTER_EMPTY")
    return tuple(rows)



def current_kospi200_futures_symbols(day: date) -> tuple[tuple[str, str], ...]:
    # The KIS index master contains futures alongside options; use its current
    # KOSPI200 standard/mini broker symbols rather than a stale local snapshot.
    request = Request(KIS_INDEX_MASTER_URL, headers={"User-Agent": "OptionProject/200"})
    with urlopen(request, timeout=15) as response:
        payload = response.read()
    with ZipFile(BytesIO(payload)) as archive:
        member = next((name for name in archive.namelist() if name.lower().endswith(".mst")), None)
        if member is None:
            raise RuntimeError("KIS_INDEX_MASTER_FILE_REQUIRED")
        raw = archive.read(member).decode("cp949", errors="replace")
    candidates = []
    current_month = f"{day.year:04d}{day.month:02d}"
    for line in raw.splitlines():
        fields = line.split("|")
        if len(fields) < 9 or fields[7].strip() != KOSPI200_UNDERLYING:
            continue
        kind, short_code, name = fields[0].strip(), fields[1].strip(), fields[3].strip()
        if kind not in {"1", "B"} or not short_code or not name:
            continue
        parts = name.split()
        month = parts[-2] if len(parts) >= 2 and parts[-1].startswith("(") else (parts[1] if len(parts) > 1 else "")
        if len(month) == 6 and month.isdigit() and month >= current_month:
            candidates.append((month, kind, short_code))
    result=[]
    for kind in ("1", "B"):
        matches=sorted((x for x in candidates if x[1] == kind), key=lambda x:x[0])
        if not matches:
            raise RuntimeError(f"KIS_KOSPI200_FUTURES_REQUIRED:{kind}:{current_month}")
        result.append(("STANDARD" if kind == "1" else "MINI", matches[0][2]))
    return tuple(result)
def current_monthly_option_symbols(day: date, reference_price: Decimal, offsets: tuple[Decimal, ...]) -> tuple[tuple[str, str], ...]:
    rows = load_kis_index_option_rows()
    current_month = f"{day.year:04d}{day.month:02d}"
    future_months = sorted({str(row["month"]) for row in rows if str(row["month"]) >= current_month})
    if not future_months:
        raise RuntimeError(f"KIS_MONTHLY_OPTION_MONTH_REQUIRED:{current_month}")
    month = future_months[0]
    month_rows = [row for row in rows if str(row["month"]) == month]
    strikes = sorted({row["strike"] for row in month_rows if isinstance(row["strike"], Decimal)})
    if not strikes:
        raise RuntimeError(f"KIS_MONTHLY_OPTION_STRIKES_REQUIRED:{month}")
    atm = min(strikes, key=lambda strike: abs(strike - Decimal(reference_price)))
    result: list[tuple[str, str]] = []
    for offset in offsets:
        strike = atm + offset
        for option_type in ("PUT", "CALL"):
            matches = [row for row in month_rows if row["option_type"] == option_type and row["strike"] == strike]
            if len(matches) != 1:
                raise RuntimeError(f"KIS_OPTION_SYMBOL_REQUIRED:{month}:{option_type}:{strike}:{len(matches)}")
            result.append(("H0IOCNT0", str(matches[0]["short_code"])))
    return tuple(result)
